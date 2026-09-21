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

AUTH: /ask also requires a Cognito access token (app/auth.py), which is a
separate credential answering a separate question — the token decides whose
documents are searched, the key decides whose Anthropic account pays. Both are
required, and the user id comes from the verified token rather than from the
request body, so a caller cannot ask for someone else's documents.

Run locally:
    uv run uvicorn app.api:app --reload --port 8000
"""

import logging
import uuid
from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, FastAPI, Header, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app import config, db, documents, ingest, query, queue, storage
from app.auth import require_user
from app.errors import (
    ApiError,
    ErrorResponse,
    document_not_found,
    missing_api_key,
    to_api_error,
    unsupported_file_type,
    upload_not_configured,
)

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
    # DELETE is here for removing a document. Production is same-origin through
    # CloudFront, so this only ever matters to the Vite dev server.
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "Authorization", API_KEY_HEADER],
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


class UploadRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    filename: str = Field(min_length=1, description="The file the researcher chose.")


class UploadResponse(BaseModel):
    """Everything the browser needs to post the file straight to S3."""

    document_id: uuid.UUID
    filename: str = Field(description="The sanitized name the document is stored under.")
    upload_url: str
    fields: dict[str, str] = Field(description="Form fields that must accompany the file.")
    max_bytes: int


class DocumentResponse(BaseModel):
    id: uuid.UUID
    filename: str
    status: str
    chunk_count: int | None = None
    error_message: str | None = None

    @classmethod
    def of(cls, document) -> "DocumentResponse":
        return cls(
            id=document.id,
            filename=document.filename,
            status=document.status,
            chunk_count=document.chunk_count,
            error_message=document.error_message,
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
def ask(
    request: AskRequest,
    user_id: str = Depends(require_user),
    api_key: str = Depends(require_api_key),
) -> AskResponse:
    """Answer one question from the caller's own documents, on the caller's key.

    The retriever is scoped to user_id, which comes from the verified token and
    never from the request, so one researcher cannot reach another's documents.
    The embedding model behind it is shared and loads on the first request only.

    Every failure below becomes an ApiError, so a rejected key or an
    unreachable database reaches the researcher as one readable sentence rather
    than a 500 and a stack trace. The original exception is logged server-side,
    where the operator can see it and the researcher cannot.
    """
    try:
        result = query.ask_with_context(
            request.question,
            retriever=query.get_retriever(user_id),
            anthropic_api_key=api_key,
        )
    except Exception as exc:
        error = to_api_error(exc)
        # exc_info, not str(exc), and never the key: the traceback is for the
        # operator's log. logger.exception keeps the full context.
        logger.exception("POST /ask failed: %s", error.code)
        raise error from exc

    return AskResponse(answer=result["answer"], sources=result["sources"])


def _load_owned_document(session, user_id: str, document_id: uuid.UUID):
    """Fetch a document or raise 404, never revealing another owner's rows."""
    document = documents.get(session, user_id, document_id)
    if document is None:
        raise document_not_found()
    return document


@router.post("/documents", response_model=UploadResponse)
def create_upload(request: UploadRequest, user_id: str = Depends(require_user)) -> UploadResponse:
    """Reserve a document and hand back a presigned POST for the file itself.

    The bytes never pass through this service: the browser posts them straight
    to S3. That is not only cheaper, it is required -- CloudFront caps a
    request body at 1MB, well under any real paper.

    The S3 key is built here from the verified user id, so a caller cannot
    steer the upload at another researcher's prefix, and the presigned policy
    pins both the key and a maximum size.
    """
    if not config.INGESTION_QUEUE_URL:
        # Refused up front rather than after the upload: accepting a file that
        # nothing can process would leave it stuck at "pending" forever.
        raise upload_not_configured()

    try:
        filename = storage.sanitize_filename(request.filename)
    except ValueError as exc:
        raise ApiError(422, "invalid_request", str(exc)) from exc

    if not filename.lower().endswith(storage.SUPPORTED_SUFFIXES):
        raise unsupported_file_type(PurePosixPath(filename).suffix, storage.SUPPORTED_SUFFIXES)

    key = storage.build_user_key(user_id, filename)

    try:
        presigned = storage.presigned_upload_post(key)
        with db.session_scope() as session:
            document = documents.create_pending(session, user_id, filename, key)
            document_id = document.id
    except ApiError:
        raise
    except Exception as exc:
        error = to_api_error(exc)
        logger.exception("POST /documents failed: %s", error.code)
        raise error from exc

    return UploadResponse(
        document_id=document_id,
        filename=filename,
        upload_url=presigned["url"],
        fields=presigned["fields"],
        max_bytes=config.MAX_UPLOAD_BYTES,
    )


@router.post("/documents/{document_id}/complete", response_model=DocumentResponse)
def complete_upload(
    document_id: uuid.UUID, user_id: str = Depends(require_user)
) -> DocumentResponse:
    """Told by the browser that the upload finished; queues the work.

    Separate from the upload itself because the upload goes to S3, which has no
    way to call back into this service. If the browser dies between the two,
    the document stays "pending" and the object is orphaned -- visible to the
    researcher rather than silently missing, and re-uploading the same filename
    reuses the row.
    """
    try:
        with db.session_scope() as session:
            document = _load_owned_document(session, user_id, document_id)
            response = DocumentResponse.of(documents.mark_processing(session, document))

        # After the commit: a queued message pointing at a row that was rolled
        # back would be picked up by a worker that cannot find it.
        queue.enqueue(document_id)
    except ApiError:
        raise
    except Exception as exc:
        error = to_api_error(exc)
        logger.exception("POST /documents/{id}/complete failed: %s", error.code)
        raise error from exc

    return response


@router.get("/documents", response_model=list[DocumentResponse])
def list_documents(user_id: str = Depends(require_user)) -> list[DocumentResponse]:
    """This researcher's documents and where each one has got to.

    Polled by the UI while anything is still processing, which is why it stays
    a plain read with no side effects.
    """
    try:
        with db.session_scope() as session:
            return [DocumentResponse.of(d) for d in documents.list_for_user(session, user_id)]
    except Exception as exc:
        error = to_api_error(exc)
        logger.exception("GET /documents failed: %s", error.code)
        raise error from exc


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: uuid.UUID, user_id: str = Depends(require_user)) -> None:
    """Remove a document: its chunks, its row, and its bytes.

    Chunks first. If the row went first and chunk deletion then failed, the
    chunks would be unreachable and unowned -- still retrievable by the
    researcher's queries, with nothing left recording where they came from.
    """
    try:
        with db.session_scope() as session:
            document = _load_owned_document(session, user_id, document_id)
            chunk_count, s3_key = document.chunk_count, document.s3_key

            ingest.delete_document_chunks(document_id, chunk_count)
            documents.delete(session, document)

        storage.delete_document_object(s3_key)
    except ApiError:
        raise
    except Exception as exc:
        error = to_api_error(exc)
        logger.exception("DELETE /documents/{id} failed: %s", error.code)
        raise error from exc


# Registered after the routes above are defined, which is what actually puts
# them on the app under API_PREFIX.
app.include_router(router)
