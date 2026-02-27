# AP2 Integration Implementation Plan

## Context

The current example has no cryptographic security — the Credential Provider issues unsigned tokens, the Business accepts any token, and the PSP approves everything starting with `tok_`. AP2 adds ECDSA-signed merchant authorization on checkout responses and SD-JWT mandates on completion, creating non-repudiable proof of what was offered and what was agreed to.

We implement the **Trusted Platform Provider** model: the platform (frontend backend) holds a signing key and generates mandates server-side.

This plan covers two mandate types:
1. **Cart Mandate** (`checkout_mandate`) — Standard AP2. User is present, confirms a specific checkout.
2. **Intent Mandate** (`intent_mandate`) — Our extension. User authorizes a class of future purchases; agent can complete them autonomously without per-transaction confirmation.

---

## Intent Mandate Wire Protocol (Spike Design)

### Motivation

Cart mandates require the user to confirm every purchase. For autonomous agent commerce — "reorder printer paper when we're low" — the agent needs pre-authorization with bounded scope. The intent mandate captures *what* was authorized, *why* (full conversation), and *within what limits*, signed cryptographically so every participant can verify it.

### Format: SD-JWT+kb (same envelope as cart mandates)

```
Intent Mandate
├── Issuer JWT (signed by platform)
│   ├── Header
│   │   ├── alg: "ES256"
│   │   ├── typ: "intent-mandate+sd-jwt"
│   │   └── kid: "platform_2026"
│   └── Payload
│       ├── iss: "https://platform.example"
│       ├── sub: "user_abc123"
│       ├── iat: 1740000000
│       ├── exp: 1740086400                       # User-specified expiration
│       │
│       ├── authorization:
│       │   ├── max_amount: 5000                  # Cents, per-transaction cap
│       │   ├── max_total: 20000                  # Cents, aggregate spend cap
│       │   ├── currency: "USD"
│       │   ├── merchant_ids: ["electronics"]     # Restrict to specific merchants
│       │   └── max_uses: 10                      # Transaction count limit
│       │
│       ├── intent:
│       │   ├── summary: "Buy printer paper..."   # Model-generated summary
│       │   ├── conversation:                     # Full conversation history
│       │   │   ├── model: "claude-sonnet-4-20250514"
│       │   │   ├── turns: [                      # Every message
│       │   │   │   { role: "user", content: "..." },
│       │   │   │   { role: "assistant", content: "..." },
│       │   │   │   ...
│       │   │   ]
│       │   │   └── turn_count: 12
│       │   └── created_at: "2026-02-26T..."
│       │
│       └── cnf: { jwk: { ... } }                # Agent/holder public key
│
└── Key Binding JWT (signed by agent per-use)
    ├── Header: { alg: "ES256", typ: "kb+jwt" }
    └── Payload
        ├── aud: "chk_session_456"                # Bound to specific checkout
        ├── iat: 1740050000
        ├── nonce: "random123"
        ├── sd_hash: "hash_of_issuer_jwt"
        ├── amount: 2499                          # Actual transaction amount
        └── use_index: 3                          # Which use number this is
```

### Defense in Depth: Three-Layer Verification

Every participant independently enforces the mandate's constraints:

**Layer 1 — Platform (frontend backend)**
- Maintains usage ledger: `{ mandate_id -> { total_spent, use_count } }`
- Before each autonomous checkout:
  - Checks `exp` not passed
  - Checks `use_count < max_uses`
  - Checks `total_spent + this_amount <= max_total`
  - Checks `this_amount <= max_amount`
- Generates key binding JWT with `use_index` and `amount`
- Refuses to bind if any limit exceeded

**Layer 2 — Merchant (business service)**
- Receives intent mandate on `complete_checkout`
- Verifies issuer JWT signature (platform's key)
- Verifies key binding JWT signature and `aud` matches session
- Checks `exp` not passed
- Checks `amount` in key binding <= `authorization.max_amount`
- Checks own `store_id` is in `authorization.merchant_ids`
- Maintains own usage counter per mandate (by mandate hash/ID)
- Rejects if `use_index` > `max_uses` or cumulative spend exceeds `max_total`

**Layer 3 — PSP (payment processor)**
- Receives the mandate (or a derivative) alongside the payment token
- Independently verifies:
  - Platform signature is valid
  - `exp` not passed
  - Transaction amount <= `max_amount`
  - Maintains its own usage ledger per mandate
  - Rejects if aggregate spend exceeds `max_total`
- This is the last line of defense — even if platform and merchant are compromised or buggy, the PSP independently enforces limits

### Conversation Inclusion

The full conversation history is embedded in the signed mandate. This means:
- **Auditability**: In a dispute, any party can read exactly what the user asked for
- **Tamper-proof**: The conversation is signed by the platform — it can't be altered after issuance
- **Transparency**: Merchants can inspect the intent before accepting autonomous orders
- **Size**: Conversations can be large; mandate size is unbounded but practical limits apply (~100KB is reasonable for most conversations)

The model generates the `summary` field as a concise human-readable description of the authorization. This is what UIs display; the full conversation is available for drill-down.

### Lifecycle

```
1. User initiates: "Set up automatic reordering..."
2. Agent confirms parameters with user (amount, expiration, scope)
3. Platform calls model to generate summary
4. Platform creates and signs intent mandate (issuer JWT)
5. Platform stores mandate + initializes usage ledger
6. [Time passes — agent operates autonomously]
7. Agent detects need to purchase
8. Platform checks usage limits, creates key binding JWT
9. Agent calls create_checkout → update_checkout → complete_checkout with intent mandate
10. Merchant verifies mandate + limits
11. PSP verifies mandate + limits
12. Transaction completes, all three layers update usage counters
```

---

## Stages

## Stage 1: Cryptographic Utilities

**Goal**: Shared Python crypto module for ECDSA, JCS, JWS, SD-JWT. TypeScript equivalent for frontend.

**Files**: New `services/shared/ap2_crypto.py`

### Python (`ap2_crypto.py`)
- `generate_ec_key(kid) -> (private_key, public_jwk)` — P-256 key pair
- `export_public_jwk(private_key, kid) -> dict` — JWK with kid, kty, crv, x, y, alg
- `jcs_canonicalize(obj) -> bytes` — RFC 8785
- `sign_detached(payload_bytes, private_key, kid) -> str` — JWS Detached Content
- `verify_detached(jws, payload_bytes, public_jwk) -> bool`
- `create_jwt(header, payload, private_key) -> str` — Standard compact JWT with ES256
- `verify_jwt(token, public_jwk) -> dict` — Verify and return payload
- `create_sd_jwt_kb(claims, issuer_key, issuer_kid, holder_key, holder_kid, audience) -> str`
- `verify_sd_jwt_kb(token, issuer_public_jwk, expected_aud) -> dict`

### TypeScript (`frontend/lib/ap2.ts`)
- Same operations using `jose` npm package
- `generateKeyPair()`, `exportPublicJwk()`, `signDetached()`, `verifyDetached()`
- `createSdJwtKb()`, `verifySdJwtKb()`
- `createIntentMandate()` — builds the intent mandate issuer JWT
- `bindIntentMandate()` — creates per-use key binding JWT

**Dependencies**: `cryptography` (Python), `jose` (npm)
**Success Criteria**: Round-trip sign/verify for JWS detached, cart mandate SD-JWT+kb, and intent mandate SD-JWT+kb.
**Status**: Complete

## Stage 2: Business Service — Merchant Authorization

**Goal**: Business signs all checkout responses with `ap2.merchant_authorization`.

**Files**: `services/business/ap2.py` (new), `services/business/sessions.py`, `services/business/models.py`, `services/business/main.py`

- Generate merchant key pair on startup
- `sign_checkout_response(checkout_dict)` — remove `ap2`, JCS canonicalize, sign with detached JWS, add `ap2.merchant_authorization`
- All session return paths (create, update, get) include the signature
- `/.well-known/ucp` declares `dev.ucp.shopping.ap2_mandate` capability and `signing_keys`

**Success Criteria**: Every checkout response includes valid `ap2.merchant_authorization`.
**Status**: Complete (both business and business-2)

## Stage 3: Platform — Cart Mandate Generation

**Goal**: Frontend generates checkout_mandate for interactive (user-present) purchases.

**Files**: `frontend/lib/ap2.ts` (new), `frontend/lib/tools.ts`, `frontend/app/api/chat/route.ts`, `frontend/app/api/ap2/jwks/route.ts` (new)

- Platform key pair generated on startup
- New `generateCheckoutMandate` tool: fetches session, verifies merchant auth, creates SD-JWT+kb
- `complete_checkout` MCP tool gains optional `checkout_mandate` parameter
- System prompt updated with mandate step
- `GET /api/ap2/jwks` publishes platform public key

**Success Criteria**: Interactive checkout flow includes mandate generation and verification.
**Status**: Complete

## Stage 4: Business Service — Mandate Verification

**Goal**: Business verifies both cart mandates and intent mandates before authorizing payment.

**Files**: `services/business/ap2.py`, `services/business/sessions.py`, `services/business/mcp_tools.py`

### Cart mandate verification
- Verify platform signature on issuer JWT
- Verify key binding `aud` matches session ID
- Verify embedded checkout matches current session (ID, totals)
- Verify embedded merchant_authorization is own valid signature

### Intent mandate verification
- Verify platform signature on issuer JWT
- Check `typ` header is `intent-mandate+sd-jwt`
- Verify `exp` not passed
- Verify `authorization.merchant_ids` includes this store
- Verify key binding `amount` <= `authorization.max_amount`
- Maintain usage ledger: `{ mandate_hash -> { total_spent, use_count } }`
- Reject if `use_index` > `max_uses` or cumulative `total_spent + amount > max_total`

### `complete_checkout` accepts either mandate type
- `checkout_mandate: str | None = None` — cart mandate (user-present)
- `intent_mandate: str | None = None` — intent mandate (user-not-present)
- At least one required; reject with `mandate_required` if neither provided

**Success Criteria**: Business rejects missing/invalid mandates, accepts valid ones, tracks intent mandate usage.
**Status**: Complete (verification logic in both business and business-2, pending integration test with Stage 3)

## Stage 5: PSP — Independent Mandate Verification

**Goal**: PSP independently verifies intent mandates as last line of defense.

**Files**: `services/psp/main.py`

### Changes to `/authorize`
- Accept optional `intent_mandate` field in authorization request
- If present:
  - Verify platform signature (fetch platform JWKS)
  - Check `exp` not passed
  - Check transaction amount <= `authorization.max_amount`
  - Maintain own usage ledger per mandate
  - Reject if cumulative spend exceeds `max_total`
- Cart mandates: PSP trusts merchant verification (no change needed)
- Intent mandates: PSP does full independent verification (defense in depth)

### Business passes mandate to PSP
- `complete_session` includes the intent mandate in the PSP `/authorize` call

**Success Criteria**: PSP independently rejects over-limit intent mandate usage even if merchant doesn't.
**Status**: Complete

## Stage 6: Platform — Intent Mandate Creation & Autonomous Flow

**Goal**: Platform can issue intent mandates and use them for autonomous purchases.

**Files**: `frontend/lib/ap2.ts`, `frontend/lib/tools.ts`, `frontend/app/api/chat/route.ts`

### New `createIntentMandate` tool
- AI calls this when user requests autonomous purchasing
- Parameters: `max_amount`, `max_total`, `currency`, `merchant_ids`, `max_uses`, `expires_in_hours`
- Tool implementation:
  1. Captures full conversation history from the chat messages
  2. Calls the model to generate a summary of the authorization
  3. Builds the intent mandate issuer JWT with all constraints + full conversation
  4. Signs with platform key
  5. Stores mandate + initializes usage ledger in memory
  6. Returns `{ mandate_id, summary, expires_at, constraints }`

### Modified checkout flow with intent mandate
- New `completeCheckoutWithIntent` tool (or modify existing flow):
  1. Platform looks up stored intent mandate by merchant
  2. Checks usage limits (Layer 1)
  3. Creates key binding JWT with `use_index` and `amount`
  4. Calls `complete_checkout` with `intent_mandate` parameter
- AI can complete purchases without asking for user confirmation

### System prompt update
- Describe the two modes: interactive (ask user, cart mandate) vs autonomous (intent mandate)
- When user sets up autonomous ordering, use `createIntentMandate`
- For subsequent autonomous purchases, use intent mandate flow

### Usage ledger (in-memory)
```typescript
Map<string, {
  mandate: string,           // The signed issuer JWT
  totalSpent: number,        // Cumulative cents spent
  useCount: number,          // Number of transactions
  constraints: {             // Extracted from mandate for quick checks
    maxAmount: number,
    maxTotal: number,
    maxUses: number,
    merchantIds: string[],
    expiresAt: number,
  }
}>
```

**Success Criteria**: User can say "set up automatic reordering", agent creates intent mandate, then completes a purchase autonomously using it.
**Status**: Complete

## Stage 7: Business-2 & Aggregator & Multi-Store

**Goal**: Full AP2 + intent mandate support across all services.

**Files**: `services/business-2/*`, `services/aggregator/mcp_tools.py`, `frontend-multi/*`

- Business-2: mirror all business AP2 changes (own key pair)
- Aggregator: pass through `checkout_mandate` and `intent_mandate` parameters, pass through `ap2` in responses
- Frontend-multi: same AP2/intent tools, `generateCheckoutMandate` takes `store_id`

**Success Criteria**: Full AP2 + intent mandate flow works through aggregator with both stores.
**Status**: Complete

## Dependency Summary

| Service | New Dependencies |
|---------|-----------------|
| Business services | `cryptography` (Python) |
| Frontend services | `jose` (npm) |
| PSP | `cryptography` (Python) — for intent mandate verification |
| Aggregator | None (pass-through) |
| Credential Provider | None |

## File Summary

| File | Change |
|------|--------|
| `services/shared/ap2_crypto.py` | New — ECDSA, JCS, JWS, SD-JWT utilities |
| `services/business/ap2.py` | New — merchant signing, mandate verification, usage ledger |
| `services/business/models.py` | Add AP2 to CheckoutSession |
| `services/business/sessions.py` | Sign responses, verify mandates |
| `services/business/mcp_tools.py` | Add checkout_mandate + intent_mandate params |
| `services/business/main.py` | Discovery with AP2 + signing_keys |
| `services/business-2/*` | Mirror all business changes |
| `services/psp/main.py` | Intent mandate verification + usage ledger |
| `services/aggregator/mcp_tools.py` | Pass through mandate params + ap2 fields |
| `frontend/lib/ap2.ts` | New — platform crypto, mandate generation, usage ledger |
| `frontend/lib/tools.ts` | Add generateCheckoutMandate + createIntentMandate tools |
| `frontend/app/api/chat/route.ts` | Update system prompt for both flows |
| `frontend/app/api/ap2/jwks/route.ts` | New — platform public key endpoint |
| `frontend-multi/*` | Mirror frontend changes |
