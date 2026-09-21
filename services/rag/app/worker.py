"""The background ingestion worker: drains the queue, parses, embeds.

Runs as a second ECS service on the same image as the API, started with
`python -m app.worker` instead of uvicorn. Parsing a PDF with Docling and
embedding the result takes minutes -- far longer than a browser request can
wait -- which is why an upload hands off to a queue rather than blocking
(ARCHITECTURE.md, "Pipeline execution").

Two properties the loop is built around:

- **A failure is recorded, not raised.** Anything that goes wrong with one
  document writes `failed` and a readable reason to its row and moves on. A
  worker that dies on a malformed PDF would stop every other researcher's
  uploads behind it.
- **The message is acknowledged only after the database is updated.** Deleting
  it earlier would lose a document on a crash; deleting it later at worst
  reprocesses one, which deterministic chunk ids make harmless.
"""

import hashlib
import logging
import signal
import sys
import tempfile
from pathlib import Path

from app import config, db, documents, ingest, queue, storage
from app.models import STATUS_READY

logger = logging.getLogger(__name__)

# Read in chunks rather than whole: an uploaded file can be tens of megabytes
# and the worker has other things to hold in memory.
_HASH_CHUNK_BYTES = 1024 * 1024

# How much text a PDF must yield before OCR is considered unnecessary. A
# born-digital paper produces thousands of characters; a scan produces almost
# none, which is the signal KNOWN_ISSUES.md wanted detected per document
# instead of guessed globally.
MIN_TEXT_LAYER_CHARS = 200


class GracefulShutdown:
    """Tracks SIGTERM so the loop can stop between documents, not during one.

    ECS sends SIGTERM and follows with SIGKILL 30 seconds later. Abandoning a
    half-written document is safe -- its chunks are deterministic ids that the
    retry overwrites -- but finishing the current one avoids the retry entirely.
    """

    def __init__(self) -> None:
        self.requested = False
        signal.signal(signal.SIGTERM, self._request)
        signal.signal(signal.SIGINT, self._request)

    def _request(self, signum, frame) -> None:
        logger.info("Shutdown requested (signal %s); finishing the current document", signum)
        self.requested = True


def file_digest(path: Path) -> str:
    """SHA-256 of a file's bytes, for detecting an unchanged re-upload."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(_HASH_CHUNK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def needs_ocr(chunks: list) -> bool:
    """Whether a parse produced so little text that OCR is the likely fix.

    Judged from the parse output rather than the file, because that is the
    thing that actually matters: a PDF whose text layer is missing or unusable
    yields nothing here regardless of what its headers claim.
    """
    return sum(len(chunk.page_content) for chunk in chunks) < MIN_TEXT_LAYER_CHARS


def process_document(document_id: str, store=None) -> str:
    """Ingest one document. Returns its final status.

    Never raises for a document-specific failure -- the reason is written to
    the row instead, which is where the researcher will read it.
    """
    with db.session_scope() as session:
        document = documents.get_for_processing(session, document_id)
        if document is None:
            # The document was deleted between the enqueue and now. Nothing to
            # do, and nothing wrong: acknowledging the message is correct.
            logger.info("Document %s no longer exists; discarding its message", document_id)
            return "missing"

        documents.mark_processing(session, document)
        user_id = document.user_id
        s3_key = document.s3_key
        filename = document.filename
        previous_hash = document.content_hash
        previous_count = document.chunk_count

    try:
        # Temporary so an uploaded research document never outlives the run,
        # the same contract app.ingest --from-s3 already follows.
        with tempfile.TemporaryDirectory(prefix="biogent-ingest-") as workdir:
            local_path = Path(workdir) / filename
            storage.download_document(s3_key, local_path)

            digest = file_digest(local_path)
            if previous_hash == digest and previous_count:
                # Identical bytes to what is already indexed. The expensive
                # half -- parse and embed -- is exactly what this skips.
                logger.info("Document %s is unchanged; keeping existing chunks", document_id)
                with db.session_scope() as session:
                    document = documents.get_for_processing(session, document_id)
                    documents.mark_ready(session, document, previous_count, digest, False)
                return STATUS_READY

            chunks = ingest.chunk_one_file(local_path, user_id, document_id)

            if needs_ocr(chunks):
                logger.info("Document %s yielded almost no text; retrying with OCR", document_id)
                chunks = ingest.chunk_one_file(local_path, user_id, document_id, do_ocr=True)
                ocr_used = True
            else:
                ocr_used = False

        if not chunks:
            with db.session_scope() as session:
                document = documents.get_for_processing(session, document_id)
                documents.mark_failed(
                    session,
                    document,
                    "No readable text was found in this file. If it is a scan, "
                    "it may need a version with selectable text.",
                )
            return "failed"

        count = ingest.replace_document_chunks(chunks, document_id, previous_count, store=store)

        with db.session_scope() as session:
            document = documents.get_for_processing(session, document_id)
            documents.mark_ready(session, document, count, digest, ocr_used)

    except Exception as exc:
        # Deliberately broad. One unreadable file, one S3 hiccup, or one
        # unexpected parser error must fail that document, not the worker
        # every other researcher is waiting on.
        logger.exception("Ingesting document %s failed", document_id)
        with db.session_scope() as session:
            document = documents.get_for_processing(session, document_id)
            if document is not None:
                documents.mark_failed(
                    session,
                    document,
                    f"This file could not be processed ({type(exc).__name__}). "
                    "Check that it opens normally, then try uploading it again.",
                )
        return "failed"

    return STATUS_READY


def handle_message(message: dict, sqs_client=None, store=None) -> None:
    """Process one queue message and acknowledge it."""
    document_id = queue.parse_document_id(message)

    if document_id is not None:
        process_document(document_id, store=store)

    # Acknowledged even when the body was unreadable: retrying a message that
    # cannot be parsed just burns the redrive budget to reach the same answer.
    queue.delete(message["ReceiptHandle"], client=sqs_client)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )

    if not config.INGESTION_QUEUE_URL:
        logger.error(
            "RAG_INGESTION_QUEUE_URL is not set, so there is no queue to consume. "
            "See services/rag/.env.example."
        )
        return 1

    shutdown = GracefulShutdown()
    # Built once: it loads the embedding model, which must not be paid for per
    # document.
    store = ingest.open_vector_store()
    logger.info("Worker ready; polling %s", config.INGESTION_QUEUE_URL)

    while not shutdown.requested:
        try:
            messages = queue.receive()
        except Exception:
            # Long polling means this already waited, so a failure here retries
            # on the next pass rather than spinning.
            logger.exception("Could not read from the queue; retrying")
            continue

        for message in messages:
            handle_message(message, store=store)

    logger.info("Worker stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
