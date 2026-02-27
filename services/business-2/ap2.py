"""AP2 merchant authorization for the Book Store service.

Generates a key pair on import, signs checkout responses with
JWS Detached Content, and verifies mandates on completion.
"""

import copy
import os

from shared.ap2_crypto import (
    generate_ec_key,
    jcs_canonicalize,
    sign_detached,
    verify_detached,
    verify_sd_jwt_kb,
)

import httpx

# Generate merchant key pair on startup
_merchant_private_key, _merchant_public_jwk = generate_ec_key("merchant_002")

# Platform JWKS URL for mandate verification
PLATFORM_JWKS_URL = os.environ.get("PLATFORM_JWKS_URL", "http://host.docker.internal:3000/api/ap2/jwks")

# Cache for platform public keys
_platform_jwks_cache: dict | None = None

# Usage ledger for intent mandates: mandate_hash -> {total_spent, use_count}
_intent_usage: dict[str, dict] = {}


def get_merchant_public_jwk() -> dict:
    """Return the merchant's public signing key as JWK."""
    return _merchant_public_jwk


def sign_checkout_response(checkout_dict: dict) -> dict:
    """Add ap2.merchant_authorization to a checkout response dict."""
    to_sign = copy.deepcopy(checkout_dict)
    to_sign.pop("ap2", None)

    canonical = jcs_canonicalize(to_sign)
    jws = sign_detached(canonical, _merchant_private_key, _merchant_public_jwk["kid"])

    checkout_dict.setdefault("ap2", {})
    checkout_dict["ap2"]["merchant_authorization"] = jws
    return checkout_dict


def verify_own_merchant_authorization(checkout_dict: dict) -> bool:
    """Verify that a checkout's merchant_authorization was signed by us."""
    jws = checkout_dict.get("ap2", {}).get("merchant_authorization")
    if not jws:
        return False

    to_verify = copy.deepcopy(checkout_dict)
    to_verify.pop("ap2", None)
    canonical = jcs_canonicalize(to_verify)
    return verify_detached(jws, canonical, _merchant_public_jwk)


async def _fetch_platform_jwks() -> dict:
    """Fetch and cache the platform's JWKS."""
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


async def verify_checkout_mandate(
    mandate_str: str,
    session_dict: dict,
) -> tuple[bool, str]:
    """Verify a cart checkout mandate (SD-JWT+kb).

    Returns (success, error_message).
    """
    jwks = await _fetch_platform_jwks()
    keys = jwks.get("keys", [])
    if not keys:
        return False, "Cannot fetch platform signing keys"

    platform_jwk = keys[0]
    session_id = session_dict.get("id", "")

    try:
        claims = verify_sd_jwt_kb(mandate_str, platform_jwk, session_id)
    except ValueError as e:
        return False, f"mandate_invalid_signature: {e}"

    embedded_checkout = claims.get("checkout")
    if not embedded_checkout:
        return False, "mandate_scope_mismatch: no checkout in mandate"

    if embedded_checkout.get("id") != session_id:
        return False, "mandate_scope_mismatch: session ID mismatch"

    embedded_total = embedded_checkout.get("totals", {}).get("total")
    session_total = session_dict.get("totals", {}).get("total")
    if embedded_total != session_total:
        return False, "mandate_scope_mismatch: total mismatch"

    embedded_ap2 = embedded_checkout.get("ap2", {})
    if not embedded_ap2.get("merchant_authorization"):
        return False, "merchant_authorization_missing in mandate"

    if not verify_own_merchant_authorization(embedded_checkout):
        return False, "merchant_authorization_invalid in mandate"

    return True, ""


async def verify_intent_mandate(
    mandate_str: str,
    session_dict: dict,
    store_id: str,
) -> tuple[bool, str]:
    """Verify an intent mandate (SD-JWT+kb with intent-mandate+sd-jwt type).

    Checks authorization limits and updates usage ledger.
    Returns (success, error_message).
    """
    jwks = await _fetch_platform_jwks()
    keys = jwks.get("keys", [])
    if not keys:
        return False, "Cannot fetch platform signing keys"

    platform_jwk = keys[0]
    session_id = session_dict.get("id", "")

    try:
        claims = verify_sd_jwt_kb(mandate_str, platform_jwk, session_id)
    except ValueError as e:
        return False, f"mandate_invalid_signature: {e}"

    auth = claims.get("authorization", {})
    max_amount = auth.get("max_amount")
    max_total = auth.get("max_total")
    max_uses = auth.get("max_uses")
    merchant_ids = auth.get("merchant_ids", [])

    if merchant_ids and store_id not in merchant_ids:
        return False, f"mandate_scope_mismatch: store {store_id} not in authorized merchants"

    session_total = session_dict.get("totals", {}).get("total", 0)
    amount_cents = int(round(session_total * 100))

    if max_amount is not None and amount_cents > max_amount:
        return False, f"mandate_scope_mismatch: amount {amount_cents} exceeds max_amount {max_amount}"

    parts = mandate_str.split("~")
    if len(parts) == 2:
        from shared.ap2_crypto import verify_jwt
        kb_jwt = parts[1]
        cnf_jwk = claims.get("cnf", {}).get("jwk")
        if cnf_jwk:
            kb_claims = verify_jwt(kb_jwt, cnf_jwk)
            kb_amount = kb_claims.get("amount")

            if kb_amount is not None and kb_amount != amount_cents:
                return False, f"mandate_scope_mismatch: kb amount {kb_amount} != session amount {amount_cents}"

            issuer_jwt = parts[0]
            import hashlib
            mandate_id = hashlib.sha256(issuer_jwt.encode()).hexdigest()[:16]

            usage = _intent_usage.get(mandate_id, {"total_spent": 0, "use_count": 0})

            if max_uses is not None and usage["use_count"] >= max_uses:
                return False, f"mandate_expired: use count {usage['use_count']} >= max_uses {max_uses}"

            if max_total is not None and (usage["total_spent"] + amount_cents) > max_total:
                return False, f"mandate_scope_mismatch: cumulative spend would exceed max_total {max_total}"

            usage["total_spent"] += amount_cents
            usage["use_count"] += 1
            _intent_usage[mandate_id] = usage

    return True, ""
