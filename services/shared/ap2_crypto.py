"""AP2 cryptographic utilities.

Implements ECDSA P-256 key management, JCS canonicalization (RFC 8785),
JWS Detached Content signing (RFC 7515 Appendix F), and SD-JWT+kb
creation/verification for AP2 mandates.
"""

import base64
import hashlib
import json
import os
import time
from typing import Any

from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.hazmat.primitives import hashes


# --- Base64url encoding (no padding, URL-safe) ---

def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


# --- Key Generation ---

def generate_ec_key(kid: str) -> tuple[ec.EllipticCurvePrivateKey, dict]:
    """Generate a P-256 EC key pair. Returns (private_key, public_jwk)."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_jwk = export_public_jwk(private_key, kid)
    return private_key, public_jwk


def export_public_jwk(private_key: ec.EllipticCurvePrivateKey, kid: str) -> dict:
    """Export the public key as a JWK dict."""
    public_numbers = private_key.public_key().public_numbers()
    x_bytes = public_numbers.x.to_bytes(32, byteorder="big")
    y_bytes = public_numbers.y.to_bytes(32, byteorder="big")
    return {
        "kid": kid,
        "kty": "EC",
        "crv": "P-256",
        "x": b64url_encode(x_bytes),
        "y": b64url_encode(y_bytes),
        "alg": "ES256",
        "use": "sig",
    }


def jwk_to_public_key(jwk: dict) -> ec.EllipticCurvePublicKey:
    """Reconstruct an EC public key from a JWK dict."""
    x = int.from_bytes(b64url_decode(jwk["x"]), byteorder="big")
    y = int.from_bytes(b64url_decode(jwk["y"]), byteorder="big")
    public_numbers = ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1())
    return public_numbers.public_key()


def jwk_thumbprint(jwk: dict) -> str:
    """Compute JWK Thumbprint (RFC 7638) for a public key."""
    required = {"crv": jwk["crv"], "kty": jwk["kty"], "x": jwk["x"], "y": jwk["y"]}
    canonical = json.dumps(required, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).digest()
    return b64url_encode(digest)


# --- JCS Canonicalization (RFC 8785) ---

def jcs_canonicalize(obj: Any) -> bytes:
    """JSON Canonicalization Scheme per RFC 8785.

    For our use case (no special floats, no lone surrogates), Python's
    json.dumps with sort_keys and compact separators is sufficient.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


# --- ECDSA Signing (raw r||s, not DER) ---

def _sign_raw(data: bytes, private_key: ec.EllipticCurvePrivateKey) -> bytes:
    """Sign data with ECDSA P-256, returning raw r||s (64 bytes)."""
    der_sig = private_key.sign(data, ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(der_sig)
    return r.to_bytes(32, byteorder="big") + s.to_bytes(32, byteorder="big")


def _verify_raw(signature: bytes, data: bytes, public_key: ec.EllipticCurvePublicKey) -> bool:
    """Verify raw r||s ECDSA signature."""
    r = int.from_bytes(signature[:32], byteorder="big")
    s = int.from_bytes(signature[32:], byteorder="big")
    der_sig = utils.encode_dss_signature(r, s)
    try:
        public_key.verify(der_sig, data, ec.ECDSA(hashes.SHA256()))
        return True
    except Exception:
        return False


# --- JWS Detached Content (RFC 7515 Appendix F) ---

def sign_detached(payload_bytes: bytes, private_key: ec.EllipticCurvePrivateKey, kid: str) -> str:
    """Create a JWS with detached content: header..signature (double dot)."""
    header = {"alg": "ES256", "kid": kid}
    encoded_header = b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    encoded_payload = b64url_encode(payload_bytes)
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    signature = _sign_raw(signing_input, private_key)
    return f"{encoded_header}..{b64url_encode(signature)}"


def verify_detached(jws: str, payload_bytes: bytes, public_jwk: dict) -> bool:
    """Verify a JWS Detached Content signature."""
    parts = jws.split(".")
    if len(parts) != 3 or parts[1] != "":
        return False
    encoded_header, _, encoded_signature = parts
    encoded_payload = b64url_encode(payload_bytes)
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    signature = b64url_decode(encoded_signature)
    public_key = jwk_to_public_key(public_jwk)
    return _verify_raw(signature, signing_input, public_key)


# --- JWT Creation / Verification ---

def create_jwt(header: dict, payload: dict, private_key: ec.EllipticCurvePrivateKey) -> str:
    """Create a compact JWT (header.payload.signature)."""
    encoded_header = b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    encoded_payload = b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    signature = _sign_raw(signing_input, private_key)
    return f"{encoded_header}.{encoded_payload}.{b64url_encode(signature)}"


def verify_jwt(token: str, public_jwk: dict) -> dict:
    """Verify a JWT and return the payload. Raises ValueError on failure."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format")
    encoded_header, encoded_payload, encoded_signature = parts
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    signature = b64url_decode(encoded_signature)
    public_key = jwk_to_public_key(public_jwk)
    if not _verify_raw(signature, signing_input, public_key):
        raise ValueError("Invalid JWT signature")
    return json.loads(b64url_decode(encoded_payload))


# --- SD-JWT+kb ---

def create_sd_jwt_kb(
    claims: dict,
    issuer_key: ec.EllipticCurvePrivateKey,
    issuer_kid: str,
    holder_jwk: dict,
    audience: str,
    typ: str = "vc+sd-jwt",
    ttl_seconds: int = 300,
) -> str:
    """Create an SD-JWT with Key Binding.

    Returns: issuer_jwt~kb_jwt (tilde-separated, no disclosures for demo).
    """
    now = int(time.time())

    # Issuer JWT
    issuer_header = {"alg": "ES256", "typ": typ, "kid": issuer_kid}
    issuer_payload = {
        **claims,
        "iat": now,
        "exp": now + ttl_seconds,
        "cnf": {"jwk": {k: holder_jwk[k] for k in ("kty", "crv", "x", "y")}},
    }
    issuer_jwt = create_jwt(issuer_header, issuer_payload, issuer_key)

    # SD hash (SHA-256 of the issuer JWT)
    sd_hash = b64url_encode(hashlib.sha256(issuer_jwt.encode("ascii")).digest())

    # Key Binding JWT (signed by holder)
    # For Trusted Platform Provider model, holder key = platform key
    # The caller must provide the holder private key separately
    # For simplicity, we pass issuer_key as holder_key in this demo
    kb_header = {"alg": "ES256", "typ": "kb+jwt"}
    kb_payload = {
        "aud": audience,
        "iat": now,
        "nonce": b64url_encode(os.urandom(16)),
        "sd_hash": sd_hash,
    }
    kb_jwt = create_jwt(kb_header, kb_payload, issuer_key)

    return f"{issuer_jwt}~{kb_jwt}"


def create_sd_jwt_kb_with_holder_key(
    claims: dict,
    issuer_key: ec.EllipticCurvePrivateKey,
    issuer_kid: str,
    holder_key: ec.EllipticCurvePrivateKey,
    holder_jwk: dict,
    audience: str,
    typ: str = "vc+sd-jwt",
    ttl_seconds: int = 300,
    extra_kb_claims: dict | None = None,
) -> str:
    """Create an SD-JWT with Key Binding using separate holder key."""
    now = int(time.time())

    issuer_header = {"alg": "ES256", "typ": typ, "kid": issuer_kid}
    issuer_payload = {
        **claims,
        "iat": now,
        "exp": now + ttl_seconds,
        "cnf": {"jwk": {k: holder_jwk[k] for k in ("kty", "crv", "x", "y")}},
    }
    issuer_jwt = create_jwt(issuer_header, issuer_payload, issuer_key)

    sd_hash = b64url_encode(hashlib.sha256(issuer_jwt.encode("ascii")).digest())

    kb_header = {"alg": "ES256", "typ": "kb+jwt"}
    kb_payload = {
        "aud": audience,
        "iat": now,
        "nonce": b64url_encode(os.urandom(16)),
        "sd_hash": sd_hash,
    }
    if extra_kb_claims:
        kb_payload.update(extra_kb_claims)
    kb_jwt = create_jwt(kb_header, kb_payload, holder_key)

    return f"{issuer_jwt}~{kb_jwt}"


def verify_sd_jwt_kb(token: str, issuer_public_jwk: dict, expected_aud: str | None) -> dict:
    """Verify an SD-JWT+kb and return the issuer JWT claims.

    Raises ValueError on any verification failure.
    """
    parts = token.split("~")
    if len(parts) != 2:
        raise ValueError("Invalid SD-JWT+kb format: expected issuer_jwt~kb_jwt")

    issuer_jwt, kb_jwt = parts

    # Verify issuer JWT
    issuer_claims = verify_jwt(issuer_jwt, issuer_public_jwk)

    # Check expiration
    now = int(time.time())
    if "exp" in issuer_claims and issuer_claims["exp"] < now:
        raise ValueError("SD-JWT expired")

    # Verify key binding JWT using the cnf key from issuer claims
    cnf_jwk = issuer_claims.get("cnf", {}).get("jwk")
    if cnf_jwk is None:
        raise ValueError("Missing cnf.jwk in issuer JWT")

    kb_claims = verify_jwt(kb_jwt, cnf_jwk)

    # Verify audience (skip if expected_aud is None, e.g. for PSP verification)
    if expected_aud is not None and kb_claims.get("aud") != expected_aud:
        raise ValueError(f"Key binding audience mismatch: expected {expected_aud}, got {kb_claims.get('aud')}")

    # Verify sd_hash
    expected_sd_hash = b64url_encode(hashlib.sha256(issuer_jwt.encode("ascii")).digest())
    if kb_claims.get("sd_hash") != expected_sd_hash:
        raise ValueError("Key binding sd_hash mismatch")

    return issuer_claims
