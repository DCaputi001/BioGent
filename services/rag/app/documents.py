"""Reads and writes for the `documents` table.

Kept out of api.py so the HTTP layer owns HTTP concerns only, and so the worker
can use exactly the same queries without importing FastAPI.

Every function that reaches a specific document takes BOTH a document id and a
user_id, and filters on both. A document id is a UUID a caller could hold from
anywhere, so looking one up by id alone would let a researcher read or delete
another's document by guessing or by keeping an id after losing access. The
ownership check belongs in the query, not in a caller that might forget it.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_PROCESSING,
    STATUS_READY,
    Document,
)


def create_pending(session: Session, user_id: str, filename: str, s3_key: str) -> Document:
    """Reserve a row before the upload starts.

    Created up front so the researcher has an id to report progress against,
    and so a document that is uploaded but never ingested is still visible
    rather than being an orphaned object in S3 nobody can see.

    Re-uploading a filename this researcher already has reuses that row and
    resets it, which is what makes a corrected file supersede the original
    instead of creating a second document. The UNIQUE (user_id, filename)
    constraint is what guarantees there is only ever one to find.
    """
    existing = get_by_filename(session, user_id, filename)
    if existing is not None:
        existing.s3_key = s3_key
        existing.status = STATUS_PENDING
        existing.error_message = None
        # chunk_count and content_hash are deliberately left alone. They still
        # describe the chunks currently in the vector store, and the worker
        # needs the old count to know how much of the tail to trim if the new
        # version produces fewer chunks. Clearing them here would strand those
        # chunks with nothing recording that they exist.
        session.flush()
        return existing

    document = Document(user_id=user_id, filename=filename, s3_key=s3_key)
    session.add(document)
    session.flush()
    return document


def get(session: Session, user_id: str, document_id: uuid.UUID) -> Document | None:
    return session.scalars(
        select(Document).where(Document.id == document_id, Document.user_id == user_id)
    ).one_or_none()


def get_by_filename(session: Session, user_id: str, filename: str) -> Document | None:
    return session.scalars(
        select(Document).where(Document.user_id == user_id, Document.filename == filename)
    ).one_or_none()


def get_for_processing(session: Session, document_id: uuid.UUID) -> Document | None:
    """Look up by id alone -- the worker's one exception to the rule above.

    The worker acts on a queue message, not on a request, so there is no
    caller whose ownership could be checked. The message was written by the
    API from a row it had already scoped to its owner, and the row carries the
    user_id the chunks are then stamped with.
    """
    return session.get(Document, document_id)


def list_for_user(session: Session, user_id: str) -> list[Document]:
    """Newest first -- the order the ix_documents_user_created index serves."""
    return list(
        session.scalars(
            select(Document)
            .where(Document.user_id == user_id)
            .order_by(Document.created_at.desc())
        )
    )


def mark_processing(session: Session, document: Document) -> Document:
    document.status = STATUS_PROCESSING
    document.error_message = None
    session.flush()
    return document


def mark_ready(
    session: Session, document: Document, chunk_count: int, content_hash: str, needs_ocr: bool
) -> Document:
    document.status = STATUS_READY
    document.chunk_count = chunk_count
    document.content_hash = content_hash
    document.needs_ocr = needs_ocr
    document.error_message = None
    session.flush()
    return document


def mark_failed(session: Session, document: Document, message: str) -> Document:
    """Record why, in words a researcher can act on.

    KNOWN_ISSUES.md's complaint about scanned PDFs was that they ingest as zero
    chunks "with nothing telling the researcher why". This column is that
    somewhere, so the message must stay readable rather than becoming a
    stringified exception.
    """
    document.status = STATUS_FAILED
    document.error_message = message
    session.flush()
    return document


def delete(session: Session, document: Document) -> None:
    session.delete(document)
    session.flush()
