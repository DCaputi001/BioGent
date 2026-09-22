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


def missing_auth() -> ApiError:
    """No bearer token at all: the caller is signed out, not broken.

    Deliberately a different code from missing_api_key. Both are 401, but the
    remedies are opposites -- one needs a sign-in, the other needs an Anthropic
    key -- and a UI branching on status alone could only guess between them.
    """
    return ApiError(
        401,
        "missing_auth",
        "Sign in to ask questions about your documents.",
    )


def invalid_token() -> ApiError:
    """A token that is present but expired, malformed, or not ours.

    The distinction between those cases is deliberately not exposed: it tells a
    caller probing the endpoint how close a forged token got, and the remedy is
    the same either way. The specific reason goes to the server log.
    """
    return ApiError(
        401,
        "invalid_token",
        "Your session has expired. Sign in again to continue.",
    )


def auth_unavailable() -> ApiError:
    """Cognito's signing keys could not be fetched, so no token can be checked.

    Retryable and deliberately not a 401: telling a correctly signed-in
    researcher to sign in again cannot fix an outage on our side, and would
    throw away a session that is still valid.
    """
    return ApiError(
        503,
        "auth_unavailable",
        "Could not verify your sign-in just now. Try again in a moment.",
        retryable=True,
    )


def document_not_found() -> ApiError:
    """Deliberately the same answer for "does not exist" and "is not yours".

    Distinguishing them would turn this endpoint into a way to test whether a
    given document id exists in someone else's library.
    """
    return ApiError(
        404,
        "document_not_found",
        "That document is not in your library. It may have been deleted.",
    )


def question_not_found() -> ApiError:
    """Same answer for "does not exist" and "is not yours", as for documents."""
    return ApiError(
        404,
        "question_not_found",
        "That question is not in your history. It may have been removed.",
    )


def unsupported_file_type(suffix: str, supported: tuple[str, ...]) -> ApiError:
    return ApiError(
        415,
        "unsupported_file_type",
        f"{suffix or 'That file type'} cannot be read. "
        f"Upload one of: {', '.join(supported)}.",
    )


def upload_not_configured() -> ApiError:
    """Uploads are on, but nothing is set up to process them.

    A 503 rather than a 500: it is an operator configuration gap, and a
    researcher retrying later may well find it fixed.
    """
    return ApiError(
        503,
        "upload_unavailable",
        "Uploading is temporarily unavailable. Try again shortly.",
        retryable=True,
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
