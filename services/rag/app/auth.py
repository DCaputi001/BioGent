"""Verifies Amazon Cognito access tokens and resolves them to a user id.

Owns exactly one question -- "who is making this request?" -- and answers it
with the Cognito `sub`, which the rest of the service treats as the opaque
owner id on a researcher's documents. Consumed by app/api.py as a FastAPI
dependency, beside the separate BYO-key dependency.

The two credentials on a request answer different questions and neither
substitutes for the other: the bearer token decides WHOSE documents are
searched, the Anthropic key decides WHO PAYS for the answer. A valid token with
no key, or a key with no token, is a 401 either way.

Verification is local. Cognito signs tokens with RS256 and publishes the public
half at a JWKS endpoint, so checking one costs a signature verification rather
than a call to AWS on every request.
"""

import logging
from functools import lru_cache

import jwt
from fastapi import Header
from jwt import PyJWKClient

from app import config
from app.errors import auth_unavailable, invalid_token, missing_auth

logger = logging.getLogger(__name__)

# Compared against a lowercased scheme, so it matches whatever casing the
# client sent -- RFC 7235 defines the scheme as case-insensitive.
BEARER_SCHEME = "bearer"

# Cognito signs with RS256 only. Pinning the list is what stops an attacker
# presenting a token whose own header asks for "none" or for a symmetric
# algorithm that would verify against the public key as if it were a secret.
SIGNING_ALGORITHMS = ["RS256"]

ACCESS_TOKEN_USE = "access"


class CognitoTokenVerifier:
    """Validates access tokens issued by one Cognito user pool."""

    def __init__(self, region: str, user_pool_id: str, client_id: str) -> None:
        self._client_id = client_id
        self._issuer = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
        # PyJWKClient caches the keys it fetches, so the JWKS endpoint is hit
        # once per process rather than once per request.
        self._jwks_client = PyJWKClient(f"{self._issuer}/.well-known/jwks.json")

    def verify(self, token: str) -> str:
        """Return the Cognito `sub` for a valid access token.

        Raises ApiError (401) for anything a caller could fix by signing in
        again, and ApiError (503) if the signing keys cannot be reached, which
        is an outage on our side rather than a bad token.
        """
        claims = self._decode(token)

        # An ID token from the same pool carries a valid signature and issuer,
        # so without this check it would be accepted here. ID tokens describe a
        # user to the client; access tokens are what authorize an API call.
        if claims.get("token_use") != ACCESS_TOKEN_USE:
            logger.warning("Rejected token: token_use was %r", claims.get("token_use"))
            raise invalid_token()

        # A pool can host several app clients. Without this, a token minted for
        # a different client in the same pool would authorize requests here.
        if claims.get("client_id") != self._client_id:
            logger.warning("Rejected token: client_id did not match this app client")
            raise invalid_token()

        return claims["sub"]

    def _decode(self, token: str) -> dict:
        """Signature, expiry and issuer checks, mapped onto our error shape."""
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=SIGNING_ALGORITHMS,
                issuer=self._issuer,
                options={
                    # Cognito access tokens carry no `aud` claim -- the app
                    # client is named by `client_id` instead -- so audience
                    # verification must be off here or every genuine token
                    # would be rejected. verify() checks client_id explicitly
                    # in its place; removing that check would leave the token
                    # unbound to any app client.
                    "verify_aud": False,
                    "require": ["exp", "iss", "sub"],
                },
            )
        except jwt.PyJWKClientError as exc:
            # Cognito's JWKS endpoint is unreachable or returned nothing usable.
            # Reporting this as a bad token would tell a signed-in researcher to
            # sign in again, which cannot help and loses their session.
            logger.exception("Could not reach Cognito's signing keys")
            raise auth_unavailable() from exc
        except jwt.PyJWTError as exc:
            # Expired, malformed, wrong issuer, bad signature. The specific
            # reason is logged but never returned: it tells someone probing the
            # endpoint how close a forged token came.
            logger.warning("Rejected token: %s", exc)
            raise invalid_token() from exc


@lru_cache(maxsize=1)
def get_verifier() -> CognitoTokenVerifier:
    """The verifier for the configured pool, built once per process.

    Cached so the JWKS key cache inside it is shared across requests rather
    than being rebuilt (and refetched) on every call.
    """
    missing = [
        name
        for name, value in (
            ("AWS_REGION", config.AWS_REGION),
            ("RAG_COGNITO_USER_POOL_ID", config.COGNITO_USER_POOL_ID),
            ("RAG_COGNITO_CLIENT_ID", config.COGNITO_CLIENT_ID),
        )
        if not value
    ]
    if missing:
        # A configuration fault, not a caller fault: fail loudly in the server
        # log rather than answering as though the request were unauthorized.
        raise RuntimeError(
            f"Authentication is not configured: {', '.join(missing)} must be set. "
            "See services/rag/.env.example."
        )

    return CognitoTokenVerifier(
        region=config.AWS_REGION,
        user_pool_id=config.COGNITO_USER_POOL_ID,
        client_id=config.COGNITO_CLIENT_ID,
    )


def require_user(authorization: str | None = Header(default=None)) -> str:
    """FastAPI dependency: the signed-in researcher's Cognito `sub`, or a 401.

    The returned id is what scopes retrieval, so every authenticated route gets
    its user from here rather than from anything the client could set directly.
    """
    header = (authorization or "").strip()
    if not header:
        raise missing_auth()

    # partition rather than a prefix match: "Bearer" with no token left behind
    # strips down to a scheme with no separator, which a prefix check including
    # the space would misread as an unknown scheme rather than an empty token.
    scheme, _, token = header.partition(" ")
    if scheme.lower() != BEARER_SCHEME:
        raise invalid_token()

    token = token.strip()
    if not token:
        raise missing_auth()

    return get_verifier().verify(token)
