"""Unit tests for app.errors — the exception-to-response mapping, without HTTP.

Complements test_api.py: that file checks the endpoint returns the mapped
result, this one checks the mapping itself, including the ordering trap where
AuthenticationError, RateLimitError and BadRequestError all subclass
APIStatusError and a general case placed first would swallow them.
"""

import httpx
import pytest
from anthropic import (
    APIConnectionError,
    APIStatusError,
    AuthenticationError,
    BadRequestError,
    PermissionDeniedError,
    RateLimitError,
)
from sqlalchemy.exc import OperationalError

from app.errors import to_api_error

REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(cls, status_code: int, message: str = "upstream said no"):
    return cls(message, response=httpx.Response(status_code, request=REQUEST), body=None)


@pytest.mark.parametrize(
    ("exc", "expected_status", "expected_code"),
    [
        (_status_error(AuthenticationError, 401), 401, "invalid_api_key"),
        (_status_error(PermissionDeniedError, 403), 403, "permission_denied"),
        (_status_error(RateLimitError, 429), 429, "rate_limited"),
        (_status_error(APIStatusError, 500), 502, "upstream_error"),
        (APIConnectionError(request=REQUEST), 502, "upstream_unreachable"),
        (OperationalError("SELECT 1", {}, Exception("boom")), 503, "document_store_unavailable"),
        (ValueError("anything else"), 500, "internal_error"),
    ],
)
def test_maps_exception_to_expected_error(exc, expected_status, expected_code):
    error = to_api_error(exc)

    assert error.status_code == expected_status
    assert error.code == expected_code


def test_exhausted_credit_is_distinguished_from_other_bad_requests():
    """Anthropic reports an empty balance as a plain 400, so the wording is the
    only signal. Getting this wrong would tell a researcher their key is broken
    when they actually just need to add credit.
    """
    out_of_credit = _status_error(
        BadRequestError, 400, "Your credit balance is too low to access the Anthropic API"
    )

    error = to_api_error(out_of_credit)

    assert error.status_code == 402
    assert error.code == "insufficient_credit"


def test_other_bad_requests_are_not_reported_as_a_billing_problem():
    error = to_api_error(_status_error(BadRequestError, 400, "max_tokens is too large"))

    assert error.code == "upstream_error"


def test_retryable_flags_match_whether_retrying_could_help():
    assert to_api_error(_status_error(RateLimitError, 429)).retryable is True
    assert to_api_error(APIConnectionError(request=REQUEST)).retryable is True
    # A rejected key will keep being rejected until the researcher changes it.
    assert to_api_error(_status_error(AuthenticationError, 401)).retryable is False


def test_messages_tell_the_researcher_what_to_do():
    assert "console.anthropic.com" in to_api_error(_status_error(AuthenticationError, 401)).message
    assert "credit" in to_api_error(
        _status_error(BadRequestError, 400, "Your credit balance is too low")
    ).message.lower()
