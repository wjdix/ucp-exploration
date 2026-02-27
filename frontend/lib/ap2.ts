/**
 * AP2 Platform Crypto — key management, mandate generation, and usage tracking.
 *
 * The platform (frontend backend) acts as a Trusted Platform Provider:
 * it holds a signing key, generates SD-JWT+kb mandates, and enforces
 * usage limits for intent mandates.
 */

import * as jose from 'jose';

// ---------------------------------------------------------------------------
// Platform key pair (generated once on startup, lives in memory)
// ---------------------------------------------------------------------------

let _platformPrivateKey: CryptoKey | null = null;
let _platformPublicJwk: jose.JWK | null = null;
const PLATFORM_KID = 'platform_2026';

async function ensureKeyPair() {
  if (_platformPrivateKey) return;
  const { publicKey, privateKey } = await jose.generateKeyPair('ES256', {
    extractable: true,
  });
  _platformPrivateKey = privateKey;
  const pub = await jose.exportJWK(publicKey);
  pub.kid = PLATFORM_KID;
  pub.alg = 'ES256';
  pub.use = 'sig';
  _platformPublicJwk = pub;
}

export async function getPlatformPublicJwk(): Promise<jose.JWK> {
  await ensureKeyPair();
  return _platformPublicJwk!;
}

export async function getPlatformJwks(): Promise<{ keys: jose.JWK[] }> {
  const jwk = await getPlatformPublicJwk();
  return { keys: [jwk] };
}

// ---------------------------------------------------------------------------
// Holder (agent) key pair — used for key binding JWTs
// ---------------------------------------------------------------------------

let _holderPrivateKey: CryptoKey | null = null;
let _holderPublicJwk: jose.JWK | null = null;

async function ensureHolderKeyPair() {
  if (_holderPrivateKey) return;
  const { publicKey, privateKey } = await jose.generateKeyPair('ES256', {
    extractable: true,
  });
  _holderPrivateKey = privateKey;
  _holderPublicJwk = await jose.exportJWK(publicKey);
  _holderPublicJwk.alg = 'ES256';
}

// ---------------------------------------------------------------------------
// Cart Mandate (SD-JWT+kb for user-present interactive purchases)
// ---------------------------------------------------------------------------

export async function generateCheckoutMandate(
  checkoutSession: Record<string, unknown>,
): Promise<string> {
  await ensureKeyPair();
  await ensureHolderKeyPair();

  const sessionId = checkoutSession.id as string;

  // Build issuer JWT payload
  const now = Math.floor(Date.now() / 1000);
  const issuerPayload = {
    iss: 'platform',
    sub: 'user_demo',
    iat: now,
    exp: now + 3600, // 1 hour
    checkout: checkoutSession,
    cnf: { jwk: _holderPublicJwk },
  };

  // Sign issuer JWT
  const issuerJwt = await new jose.SignJWT(issuerPayload)
    .setProtectedHeader({
      alg: 'ES256',
      typ: 'checkout-mandate+sd-jwt',
      kid: PLATFORM_KID,
    })
    .sign(_platformPrivateKey!);

  // Build key binding JWT
  const sdHash = jose.base64url.encode(
    new Uint8Array(
      await crypto.subtle.digest(
        'SHA-256',
        new TextEncoder().encode(issuerJwt),
      ),
    ),
  );

  const kbJwt = await new jose.SignJWT({
    aud: sessionId,
    iat: now,
    nonce: crypto.randomUUID(),
    sd_hash: sdHash,
  })
    .setProtectedHeader({ alg: 'ES256', typ: 'kb+jwt' })
    .sign(_holderPrivateKey!);

  // SD-JWT+kb format: <issuer_jwt>~<kb_jwt>
  return `${issuerJwt}~${kbJwt}`;
}

// ---------------------------------------------------------------------------
// Intent Mandate — for autonomous agent purchases
// ---------------------------------------------------------------------------

interface IntentMandateConstraints {
  maxAmount: number; // cents, per-transaction
  maxTotal: number; // cents, aggregate
  currency: string;
  merchantIds: string[];
  maxUses: number;
  expiresAt: number; // unix timestamp
}

interface IntentMandateEntry {
  issuerJwt: string;
  constraints: IntentMandateConstraints;
  totalSpent: number;
  useCount: number;
}

// In-memory storage for intent mandates
const _intentMandates = new Map<string, IntentMandateEntry>();

export async function createIntentMandate(params: {
  maxAmount: number;
  maxTotal: number;
  currency: string;
  merchantIds: string[];
  maxUses: number;
  expiresInHours: number;
  conversation: { model: string; turns: Array<{ role: string; content: string }>; turnCount: number };
  summary: string;
}): Promise<{
  mandateId: string;
  summary: string;
  expiresAt: number;
  constraints: IntentMandateConstraints;
}> {
  await ensureKeyPair();
  await ensureHolderKeyPair();

  const now = Math.floor(Date.now() / 1000);
  const expiresAt = now + Math.floor(params.expiresInHours * 3600);

  const constraints: IntentMandateConstraints = {
    maxAmount: params.maxAmount,
    maxTotal: params.maxTotal,
    currency: params.currency,
    merchantIds: params.merchantIds,
    maxUses: params.maxUses,
    expiresAt,
  };

  const issuerPayload = {
    iss: 'platform',
    sub: 'user_demo',
    iat: now,
    exp: expiresAt,
    authorization: {
      max_amount: params.maxAmount,
      max_total: params.maxTotal,
      currency: params.currency,
      merchant_ids: params.merchantIds,
      max_uses: params.maxUses,
    },
    intent: {
      summary: params.summary,
      conversation: params.conversation,
      created_at: new Date().toISOString(),
    },
    cnf: { jwk: _holderPublicJwk },
  };

  const issuerJwt = await new jose.SignJWT(issuerPayload)
    .setProtectedHeader({
      alg: 'ES256',
      typ: 'intent-mandate+sd-jwt',
      kid: PLATFORM_KID,
    })
    .sign(_platformPrivateKey!);

  // Generate mandate ID from hash of issuer JWT
  const hashBuf = await crypto.subtle.digest(
    'SHA-256',
    new TextEncoder().encode(issuerJwt),
  );
  const mandateId = jose.base64url.encode(new Uint8Array(hashBuf)).slice(0, 16);

  _intentMandates.set(mandateId, {
    issuerJwt,
    constraints,
    totalSpent: 0,
    useCount: 0,
  });

  return { mandateId, summary: params.summary, expiresAt, constraints };
}

export async function bindIntentMandate(
  mandateId: string,
  sessionId: string,
  amountCents: number,
): Promise<{ mandate: string } | { error: string }> {
  await ensureHolderKeyPair();

  const entry = _intentMandates.get(mandateId);
  if (!entry) return { error: `Unknown mandate: ${mandateId}` };

  const now = Math.floor(Date.now() / 1000);
  const { constraints } = entry;

  // Layer 1 checks (platform)
  if (now >= constraints.expiresAt) {
    return { error: 'mandate_expired' };
  }
  if (amountCents > constraints.maxAmount) {
    return { error: `amount ${amountCents} exceeds max_amount ${constraints.maxAmount}` };
  }
  if (entry.useCount >= constraints.maxUses) {
    return { error: `use_count ${entry.useCount} >= max_uses ${constraints.maxUses}` };
  }
  if (entry.totalSpent + amountCents > constraints.maxTotal) {
    return { error: `cumulative spend would exceed max_total ${constraints.maxTotal}` };
  }

  // Create key binding JWT
  const sdHash = jose.base64url.encode(
    new Uint8Array(
      await crypto.subtle.digest(
        'SHA-256',
        new TextEncoder().encode(entry.issuerJwt),
      ),
    ),
  );

  const kbJwt = await new jose.SignJWT({
    aud: sessionId,
    iat: now,
    nonce: crypto.randomUUID(),
    sd_hash: sdHash,
    amount: amountCents,
    use_index: entry.useCount,
  })
    .setProtectedHeader({ alg: 'ES256', typ: 'kb+jwt' })
    .sign(_holderPrivateKey!);

  // Update usage ledger
  entry.totalSpent += amountCents;
  entry.useCount += 1;

  return { mandate: `${entry.issuerJwt}~${kbJwt}` };
}
