"""Error taxonomy for the HTTP API: one JSON shape, researcher-readable messages.

Every failure the API returns looks like:

    {"error": {"code": "invalid_api_key", "message": "...", "retryable": false}}

so the frontend parses one thing and can branch on a stable `code` rather than
on prose. Messages are written for a non-technical researcher and name the
action to take, per ARCHITECTURE.md's "graceful failure states" requirement.

Kept separate from api.py so the exception-to-response mapping can be unit
tested directly, without HTTP. Nothing here echoes an API key, a connection
string, or a raw upstream payload — those go to the server log only.
"""

from anthropic import (
    APIConnectionError,
    APIStatusError,
    AuthenticationError,
    BadRequestError,
    PermissionDeniedError,
    RateLimitError,
)
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

CONSOLE_URL = "console.anthropic.com"


class ErrorDetail(BaseModel):
    code: str
    message: str
    # Lets the UI decide between "try again" and "fix something first" without
    # hardcoding a list of codes.
    retryable: bool = False


class ErrorResponse(BaseModel):
    error: ErrorDetail


class ApiError(Exception):
    """An error already shaped for the researcher; api.py renders it as JSON."""

    def __init__(self, status_code: int, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable

    def to_response(self) -> ErrorResponse:
        return ErrorResponse(
            error=ErrorDetail(code=self.code, message=self.message, retryable=self.retryable)
        )


def missing_api_key() -> ApiError:
    """A fresh instance per call: raising one shared exception object would let
    each raise overwrite the previous traceback.
    """
    return ApiError(
        401,
        "missing_api_key",
        "Add your Anthropic API key to ask a question. It is sent with each "
        "request and never stored.",
    )


def _is_out_of_credit(exc: BadRequestError) -> bool:
    """Anthropic reports exhausted credit as a 400, not a payment-specific status.

    The wording is the only signal available, so this stays a substring check
    rather than a status code check.
    """
    return "credit balance" in str(exc).lower()


def to_api_error(exc: Exception) -> ApiError:
    """Map an exception raised while answering into a researcher-facing error.

    Ordered most specific first: AuthenticationError, PermissionDeniedError and
    RateLimitError all subclass APIStatusError, so the general case must come
    last or it would swallow them.
    """
    if isinstance(exc, AuthenticationError):
        return ApiError(
            401,
            "invalid_api_key",
            f"Anthropic rejected this API key. Check it at {CONSOLE_URL}, or create a new one.",
        )
    if isinstance(exc, BadRequestError) and _is_out_of_credit(exc):
        return ApiError(
            402,
            "insufficient_credit",
            f"This Anthropic account is out of credit. Add credit at {CONSOLE_URL} "
            "under Settings, then try again.",
        )
    if isinstance(exc, PermissionDeniedError):
        return ApiError(
            403,
            "permission_denied",
            "This API key is not allowed to use the model this service runs on. "
            f"Check the key's permissions at {CONSOLE_URL}.",
        )
    if isinstance(exc, RateLimitError):
        return ApiError(
            429,
            "rate_limited",
            "Anthropic is temporarily limiting how fast this key can ask questions. "
            "Wait a few seconds and try again.",
            retryable=True,
        )
    if isinstance(exc, APIConnectionError):
        return ApiError(
            502,
            "upstream_unreachable",
            "Could not reach Anthropic. Check your internet connection and try again.",
            retryable=True,
        )
    if isinstance(exc, APIStatusError):
        return ApiError(
            502,
            "upstream_error",
            "Anthropic returned an unexpected error. Try again in a moment.",
            retryable=True,
        )
    if isinstance(exc, SQLAlchemyError):
        # Deliberately vague: the underlying message can carry the database host
        # and connection details, which belong in the log, not in a response.
        return ApiError(
            503,
            "document_store_unavailable",
            "The document library is temporarily unavailable. Try again shortly.",
            retryable=True,
        )
    return ApiError(
        500,
        "internal_error",
        "Something went wrong on our end. Try again in a moment.",
        retryable=True,
    )
