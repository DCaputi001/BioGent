"""HTTP API for the RAG service: one question-answering endpoint, plus health.

Thin on purpose. This module owns HTTP concerns only — request shape, the
BYO-key header, CORS — and delegates every retrieval and LLM decision to
app/query.py, which the CLI and the eval harness already exercise.

BYO-KEY: the researcher's Anthropic key arrives in the X-Anthropic-Api-Key
header on each request, is passed straight to that one chain invocation, and is
never written to disk, cached, or logged. The endpoint deliberately does NOT
fall back to a server-side ANTHROPIC_API_KEY: a server that answers without a
caller's key would silently bill the operator, which is the cost model this
project explicitly rejected (see ARCHITECTURE.md, "how the LLM gets paid for").

Run locally:
    uv run uvicorn app.api:app --reload --port 8000
"""

import logging

from fastapi import APIRouter, Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app import config, query
from app.errors import ApiError, ErrorResponse, missing_api_key, to_api_error

logger = logging.getLogger(__name__)

API_KEY_HEADER = "X-Anthropic-Api-Key"

# Every route lives under /api. In production one CloudFront distribution serves
# the frontend from S3 and routes /api/* here, so the app owns the prefix rather
# than relying on an edge function to rewrite paths. Same URLs locally, which
# keeps development and production honest about what the frontend calls.
API_PREFIX = "/api"

app = FastAPI(
    title="BioGent RAG API",
    description="Ask grounded questions about ingested research documents.",
    version="0.1.0",
)

router = APIRouter(prefix=API_PREFIX)

# The browser blocks the frontend's calls without this once the Vite dev server
# (default http://localhost:5173) starts calling the API. curl ignores CORS
# entirely, so a missing origin here only ever surfaces in the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", API_KEY_HEADER],
)


class AskRequest(BaseModel):
    # Strip first, then enforce min_length, so a whitespace-only box from the UI
    # is rejected here rather than becoming a paid LLM call that retrieves noise.
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=1, description="The researcher's question.")


class AskResponse(BaseModel):
    answer: str
    sources: list[str] = Field(
        default_factory=list,
        description="Filenames of the documents the answer was grounded in.",
    )


@app.exception_handler(ApiError)
def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
    """Render every deliberate failure in the one documented error shape."""
    return JSONResponse(status_code=exc.status_code, content=exc.to_response().model_dump())


@app.exception_handler(RequestValidationError)
def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Same shape for malformed requests as for everything else.

    FastAPI's default 422 body is a list of pydantic error dicts, which a UI
    would have to special-case; this collapses it to one readable sentence.
    """
    error = ApiError(
        422,
        "invalid_request",
        "That question could not be read. Enter a question and try again.",
    )
    return JSONResponse(status_code=error.status_code, content=error.to_response().model_dump())


def require_api_key(
    x_anthropic_api_key: str | None = Header(default=None, alias=API_KEY_HEADER),
) -> str:
    """The caller's Anthropic key, or a 401 explaining that one is required.

    Whitespace-only counts as missing: a UI sending an untrimmed empty field
    should get the same clear error as one sending no header at all.
    """
    key = (x_anthropic_api_key or "").strip()
    if not key:
        raise missing_api_key()
    return key


@router.get("/health")
def health() -> dict:
    """Liveness only: no database call and no API key, so it stays cheap.

    Phase 5's ECS health check polls this, which is why it must not depend on
    RDS or Secrets Manager being reachable.
    """
    return {"status": "ok"}


@router.post(
    "/ask",
    response_model=AskResponse,
    responses={
        401: {"model": ErrorResponse},
        402: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def ask(request: AskRequest, api_key: str = Depends(require_api_key)) -> AskResponse:
    """Answer one question from the ingested documents, on the caller's key.

    get_retriever() is cached process-wide, so the embedding model loads on the
    first request only.

    Every failure below becomes an ApiError, so a rejected key or an
    unreachable database reaches the researcher as one readable sentence rather
    than a 500 and a stack trace. The original exception is logged server-side,
    where the operator can see it and the researcher cannot.
    """
    try:
        result = query.ask_with_context(
            request.question,
            anthropic_api_key=api_key,
            retriever=query.get_retriever(),
        )
    except Exception as exc:
        error = to_api_error(exc)
        # exc_info, not str(exc), and never the key: the traceback is for the
        # operator's log. logger.exception keeps the full context.
        logger.exception("POST /ask failed: %s", error.code)
        raise error from exc

    return AskResponse(answer=result["answer"], sources=result["sources"])


# Registered after the routes above are defined, which is what actually puts
# them on the app under API_PREFIX.
app.include_router(router)
