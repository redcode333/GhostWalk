"""Clerk session-token verification (JWKS) and workspace API tokens.

ClerkVerifier.verify(token): RS256 signature against the JWKS (keys cached by PyJWKClient), `exp` and `nbf` enforced (10 s leeway), `iat` and `sub` required, the issuer checked when known, and the
authorised party (`azp`, the origin that asked Clerk for the session) checked against the allow-list when one is configured.
Workspace API tokens are `gw_live_<workspace id>_<secret>`: only a SHA-256 of the secret is stored, and the full token is shown exactly once, when it is issued."""
from __future__ import annotations
import hashlib, hmac, os, secrets
import jwt


class AuthError(Exception):
    pass


class ClerkVerifier:
    def __init__(self, jwks_url: str | None = None, issuer: str | None = None, authorized_parties=(), jwk_client=None, leeway: int = 10):
        if jwk_client is None:
            if not jwks_url:
                raise ValueError("CLERK_JWKS_URL is required for AUTH_MODE=clerk")
            jwk_client = jwt.PyJWKClient(jwks_url, cache_keys=True, max_cached_keys=16, lifespan=3600)       # keys are cached, not fetched per request
        self.client, self.leeway = jwk_client, leeway
        self.issuer = issuer or (jwks_url.split("/.well-known")[0] if jwks_url else None)
        self.parties = {p.rstrip("/") for p in authorized_parties if p}

    @classmethod
    def from_env(cls):
        parties = [p.strip() for p in os.environ.get("CLERK_AUTHORIZED_PARTIES", os.environ.get("GW_CORS_ORIGINS", "")).split(",") if p.strip()]
        return cls(os.environ.get("CLERK_JWKS_URL"), os.environ.get("CLERK_ISSUER"), parties)

    def verify(self, token: str) -> dict:
        try:
            key = self.client.get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=["RS256"], issuer=self.issuer, leeway=self.leeway, options={"require": ["exp", "iat", "sub"], "verify_aud": False})
        except jwt.PyJWTError as e:
            raise AuthError(f"invalid session: {type(e).__name__}") from e
        except Exception as e:                                                        # JWKS unreachable, malformed header
            raise AuthError(f"invalid session: {type(e).__name__}") from e
        if self.parties:
            azp = claims.get("azp")
            if azp and azp.rstrip("/") not in self.parties:           # as Clerk's own SDK does: checked when present (a browser session always carries it; a token minted server-side with the secret key does not)
                raise AuthError("invalid session: unauthorised party")
        return claims


def new_token(wsid: str) -> tuple[str, str]:
    """-> (the full token, to show once; the SHA-256 of its secret, to store)."""
    secret = secrets.token_hex(16)
    return f"gw_live_{wsid}_{secret}", hashlib.sha256(secret.encode()).hexdigest()


def split_token(tok: str) -> tuple[str | None, str | None]:
    """gw_live_<wsid>_<secret> -> (wsid, secret); the older gw_live_<secret> -> (None, secret)."""
    if not tok or not tok.startswith("gw_live_"):
        return None, None
    rest = tok[len("gw_live_"):]
    if "_" in rest:
        wsid, secret = rest.rsplit("_", 1)
        return wsid, secret
    return None, rest


def secret_matches(secret: str | None, stored_hash: str | None) -> bool:
    return bool(secret and stored_hash) and hmac.compare_digest(hashlib.sha256(secret.encode()).hexdigest(), stored_hash)
