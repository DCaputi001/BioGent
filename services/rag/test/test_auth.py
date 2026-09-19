"""Unit tests for app.auth — Cognito access token verification.

Tokens are minted here with a throwaway RSA key generated per test session,
and the JWKS lookup is stubbed to hand back its public half. Nothing reaches
AWS, so these stay in the fast, no-credentials CI tier with the rest.

The cases that matter most are the rejections. A verifier that accepts good
tokens but also accepts an ID token, a token from another app client, or an
unsigned one looks completely healthy in manual testing — every legitimate
sign-in works — while leaving the isolation boundary open.
"""

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth import CognitoTokenVerifier, require_user
from app.errors import ApiError

REGION = "us-east-1"
POOL_ID = "us-east-1_ExamplePool"
CLIENT_ID = "example-app-client-id"
ISSUER = f"https://cognito-idp.{REGION}.amazonaws.com/{POOL_ID}"
USER_SUB = "11111111-2222-3333-4444-555555555555"


@pytest.fixture(scope="module")
def private_key():
    """One keypair for the module: generating RSA keys is slow."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def other_private_key():
    """A key the verifier does not trust, for the bad-signature case."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def make_token(key, **overrides) -> str:
    """A Cognito-shaped access token, with any claim replaced for a test."""
    now = int(time.time())
    claims = {
        "sub": USER_SUB,
        "iss": ISSUER,
        "client_id": CLIENT_ID,
        "token_use": "access",
        "iat": now,
        "exp": now + 3600,
    }
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm="RS256")


@pytest.fixture
def verifier(private_key, monkeypatch) -> CognitoTokenVerifier:
    """A verifier whose JWKS lookup returns our test key instead of Cognito's."""

    class StubSigningKey:
        key = private_key.public_key()

    monkeypatch.setattr(
        "app.auth.PyJWKClient.get_signing_key_from_jwt",
        lambda self, token: StubSigningKey(),
    )
    return CognitoTokenVerifier(region=REGION, user_pool_id=POOL_ID, client_id=CLIENT_ID)


def test_a_valid_access_token_yields_the_user_id(verifier, private_key):
    assert verifier.verify(make_token(private_key)) == USER_SUB


def test_an_expired_token_is_rejected(verifier, private_key):
    expired = make_token(private_key, exp=int(time.time()) - 60)

    with pytest.raises(ApiError) as caught:
        verifier.verify(expired)

    assert caught.value.status_code == 401
    assert caught.value.code == "invalid_token"


def test_a_token_from_another_user_pool_is_rejected(verifier, private_key):
    """Right signature, wrong issuer — a token minted by a different pool."""
    foreign = make_token(
        private_key, iss="https://cognito-idp.us-east-1.amazonaws.com/us-east-1_OtherPool"
    )

    with pytest.raises(ApiError) as caught:
        verifier.verify(foreign)

    assert caught.value.code == "invalid_token"


def test_a_token_for_another_app_client_is_rejected(verifier, private_key):
    """One pool can host several clients, and they are not interchangeable.

    This is the check that has to be done by hand: Cognito access tokens carry
    no `aud` claim, so JWT audience verification cannot do it.
    """
    other_client = make_token(private_key, client_id="some-other-app-client")

    with pytest.raises(ApiError) as caught:
        verifier.verify(other_client)

    assert caught.value.code == "invalid_token"


def test_an_id_token_is_not_accepted_as_an_access_token(verifier, private_key):
    """An ID token from this pool is correctly signed and correctly issued.

    Only token_use tells them apart, which is why it is checked explicitly.
    """
    id_token = make_token(private_key, token_use="id")

    with pytest.raises(ApiError) as caught:
        verifier.verify(id_token)

    assert caught.value.code == "invalid_token"


def test_a_token_signed_by_the_wrong_key_is_rejected(verifier, other_private_key):
    forged = make_token(other_private_key)

    with pytest.raises(ApiError) as caught:
        verifier.verify(forged)

    assert caught.value.code == "invalid_token"


def test_an_unsigned_token_is_rejected(verifier):
    """The classic 'alg: none' downgrade, refused by pinning the algorithm."""
    now = int(time.time())
    unsigned = jwt.encode(
        {
            "sub": USER_SUB,
            "iss": ISSUER,
            "client_id": CLIENT_ID,
            "token_use": "access",
            "exp": now + 3600,
        },
        key="",
        algorithm="none",
    )

    with pytest.raises(ApiError) as caught:
        verifier.verify(unsigned)

    assert caught.value.code == "invalid_token"


def test_a_token_without_a_subject_is_rejected(verifier, private_key):
    """Without `sub` there is no owner id, so there is nothing to scope to."""
    no_subject = make_token(private_key)
    claims_without_sub = jwt.decode(no_subject, options={"verify_signature": False})
    del claims_without_sub["sub"]
    token = jwt.encode(claims_without_sub, private_key, algorithm="RS256")

    with pytest.raises(ApiError) as caught:
        verifier.verify(token)

    assert caught.value.code == "invalid_token"


def test_unreachable_signing_keys_are_not_reported_as_a_bad_token(monkeypatch, private_key):
    """A JWKS outage must not tell a signed-in researcher to sign in again.

    Signing in again cannot fix it, and following that advice would throw away
    a session that is still perfectly valid.
    """

    def unreachable(self, token):
        raise jwt.PyJWKClientError("could not fetch the JWKS")

    monkeypatch.setattr("app.auth.PyJWKClient.get_signing_key_from_jwt", unreachable)
    verifier = CognitoTokenVerifier(region=REGION, user_pool_id=POOL_ID, client_id=CLIENT_ID)

    with pytest.raises(ApiError) as caught:
        verifier.verify(make_token(private_key))

    assert caught.value.status_code == 503
    assert caught.value.code == "auth_unavailable"
    assert caught.value.retryable is True


# --- require_user: header handling, before any verification happens ----------


def test_no_authorization_header_reads_as_signed_out():
    with pytest.raises(ApiError) as caught:
        require_user(authorization=None)

    assert caught.value.code == "missing_auth"


def test_a_non_bearer_scheme_is_rejected():
    with pytest.raises(ApiError) as caught:
        require_user(authorization="Basic dXNlcjpwYXNz")

    assert caught.value.code == "invalid_token"


def test_a_bearer_header_with_no_token_reads_as_signed_out():
    with pytest.raises(ApiError) as caught:
        require_user(authorization="Bearer    ")

    assert caught.value.code == "missing_auth"


def test_the_bearer_scheme_is_matched_case_insensitively(monkeypatch):
    """RFC 7235 defines the scheme as case-insensitive, and clients vary."""
    monkeypatch.setattr("app.auth.get_verifier", lambda: _AcceptAnything())

    assert require_user(authorization="bearer some-token") == USER_SUB


class _AcceptAnything:
    def verify(self, token: str) -> str:
        return USER_SUB
