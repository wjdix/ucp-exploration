import os
import uuid

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from shared.ap2_crypto import verify_sd_jwt_kb, verify_jwt

app = FastAPI(title="UCP Payment Service Provider")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Platform JWKS URL for intent mandate verification (Layer 3)
PLATFORM_JWKS_URL = os.environ.get("PLATFORM_JWKS_URL", "http://host.docker.internal:3000/api/ap2/jwks")

# Cache for platform public keys
_platform_jwks_cache: dict | None = None

# Usage ledger for intent mandates: mandate_hash -> {total_spent, use_count}
_intent_usage: dict[str, dict] = {}


async def _fetch_platform_jwks() -> dict:
    global _platform_jwks_cache
    if _platform_jwks_cache is not None:
        return _platform_jwks_cache
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(PLATFORM_JWKS_URL)
            resp.raise_for_status()
            _platform_jwks_cache = resp.json()
            return _platform_jwks_cache
    except Exception:
        return {"keys": []}


async def _verify_intent_mandate(mandate_str: str, amount: float) -> tuple[bool, str]:
    """Layer 3 (PSP) intent mandate verification.

    Independently verifies the mandate and enforces spending limits.
    """
    jwks = await _fetch_platform_jwks()
    keys = jwks.get("keys", [])
    if not keys:
        return False, "Cannot fetch platform signing keys"

    platform_jwk = keys[0]

    # We use an empty aud for PSP verification since we don't know the session ID
    # The key binding JWT's aud was already verified by the merchant (Layer 2)
    try:
        claims = verify_sd_jwt_kb(mandate_str, platform_jwk, None)
    except ValueError as e:
        return False, f"mandate_invalid_signature: {e}"

    # Check expiration
    import time
    exp = claims.get("exp", 0)
    if time.time() >= exp:
        return False, "mandate_expired"

    auth = claims.get("authorization", {})
    max_amount = auth.get("max_amount")
    max_total = auth.get("max_total")
    max_uses = auth.get("max_uses")

    amount_cents = int(round(amount * 100))

    if max_amount is not None and amount_cents > max_amount:
        return False, f"amount {amount_cents} exceeds max_amount {max_amount}"

    # Usage tracking
    parts = mandate_str.split("~")
    if len(parts) == 2:
        issuer_jwt = parts[0]
        import hashlib
        mandate_id = hashlib.sha256(issuer_jwt.encode()).hexdigest()[:16]

        usage = _intent_usage.get(mandate_id, {"total_spent": 0, "use_count": 0})

        if max_uses is not None and usage["use_count"] >= max_uses:
            return False, f"use count {usage['use_count']} >= max_uses {max_uses}"

        if max_total is not None and (usage["total_spent"] + amount_cents) > max_total:
            return False, f"cumulative spend would exceed max_total {max_total}"

        usage["total_spent"] += amount_cents
        usage["use_count"] += 1
        _intent_usage[mandate_id] = usage

    return True, ""


class AuthorizeRequest(BaseModel):
    token: str
    amount: float
    currency: str
    merchant_id: str
    intent_mandate: str | None = None


class AuthorizeResponse(BaseModel):
    authorization_id: str
    status: str
    amount: float
    currency: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/authorize", response_model=AuthorizeResponse)
async def authorize(request: AuthorizeRequest):
    if not request.token.startswith("tok_"):
        raise HTTPException(status_code=400, detail="Invalid token: must start with 'tok_'")

    # Layer 3: PSP intent mandate verification
    if request.intent_mandate:
        ok, err = await _verify_intent_mandate(request.intent_mandate, request.amount)
        if not ok:
            raise HTTPException(status_code=403, detail=f"Intent mandate verification failed: {err}")

    return AuthorizeResponse(
        authorization_id=f"auth_{uuid.uuid4().hex}",
        status="approved",
        amount=request.amount,
        currency=request.currency,
    )
