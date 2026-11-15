"""Unit tests for access-token verification (no network, keys generated locally)."""

import time
import uuid

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError

from app.core.exceptions import AuthServiceUnavailableError, TokenValidationError
from app.core.security import TokenVerifier

ISSUER = "https://test-project.supabase.co/auth/v1"


def test_valid_token_returns_user(make_token, token_verifier: TokenVerifier) -> None:
    user_id = uuid.uuid4()
    user = token_verifier.verify(make_token(sub=str(user_id), email="a@example.com"))
    assert user.id == user_id
    assert user.email == "a@example.com"


def test_expired_token_rejected(make_token, token_verifier: TokenVerifier) -> None:
    now = int(time.time())
    with pytest.raises(TokenValidationError, match="expired"):
        token_verifier.verify(make_token(iat=now - 7200, exp=now - 3600))


def test_wrong_issuer_rejected(make_token, token_verifier: TokenVerifier) -> None:
    with pytest.raises(TokenValidationError):
        token_verifier.verify(make_token(iss="https://evil.example.com/auth/v1"))


def test_wrong_audience_rejected(make_token, token_verifier: TokenVerifier) -> None:
    with pytest.raises(TokenValidationError):
        token_verifier.verify(make_token(aud="some-other-app"))


def test_token_signed_by_unknown_key_rejected(make_token, token_verifier: TokenVerifier) -> None:
    attacker_key = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(TokenValidationError):
        token_verifier.verify(make_token(key=attacker_key))


def test_missing_subject_rejected(make_token, token_verifier: TokenVerifier) -> None:
    with pytest.raises(TokenValidationError):
        token_verifier.verify(make_token(sub=None))


def test_non_uuid_subject_rejected(make_token, token_verifier: TokenVerifier) -> None:
    with pytest.raises(TokenValidationError, match="user id"):
        token_verifier.verify(make_token(sub="not-a-uuid"))


def test_non_authenticated_role_rejected(make_token, token_verifier: TokenVerifier) -> None:
    with pytest.raises(TokenValidationError, match="authenticated"):
        token_verifier.verify(make_token(role="anon"))


def test_hs256_algorithm_confusion_rejected(make_token, token_verifier: TokenVerifier) -> None:
    forged = make_token(key="x" * 64, algorithm="HS256")
    with pytest.raises(TokenValidationError):
        token_verifier.verify(forged)


def test_garbage_token_rejected(token_verifier: TokenVerifier) -> None:
    with pytest.raises(TokenValidationError):
        token_verifier.verify("this.is.not-a-jwt")


def test_jwks_outage_is_service_unavailable_not_invalid_token(make_token) -> None:
    def broken_resolver(_token: str):
        raise PyJWKClientConnectionError("network down")

    verifier = TokenVerifier(issuer=ISSUER, audience="authenticated", key_resolver=broken_resolver)
    with pytest.raises(AuthServiceUnavailableError):
        verifier.verify(make_token())


def test_unknown_key_id_rejected(make_token) -> None:
    def resolver(_token: str):
        raise PyJWKClientError("Unable to find a signing key that matches")

    verifier = TokenVerifier(issuer=ISSUER, audience="authenticated", key_resolver=resolver)
    with pytest.raises(TokenValidationError):
        verifier.verify(make_token())
