"""SQLAlchemy models for this project's own tables.

Today that is one table: `documents`, a row per file a researcher uploaded.
Chunks and embeddings are NOT here — `langchain_pg_collection` and
`langchain_pg_embedding` are created and owned by langchain-postgres, and
Alembic deliberately leaves them alone (see alembic/env.py).

The link between the two halves is `documents.id`, written into each chunk's
metadata at ingestion, which is what lets a re-upload delete exactly one
document's chunks instead of wiping a whole collection.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Postgres will invent names for constraints that do not have one, and those
# names are not reproducible across databases. A later migration that needs to
# ALTER or DROP a constraint has to name it, so without this every such
# migration is a guess. Set once, before any constraint exists, because
# renaming them afterwards is its own migration.
#
# Note the "ck" pattern interpolates the name that was passed: a CheckConstraint
# declared name="status" becomes "ck_documents_status", while passing the full
# "ck_documents_status" would render "ck_documents_ck_documents_status".
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for our tables. Alembic autogenerates against this."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# Tables created and owned by langchain-postgres, not by us. Alembic must never
# manage them: autogenerate compares the database against the models above, so
# without this filter it sees two tables no model declares and emits DROP TABLE
# for both -- which would take the entire vector store with it.
#
# Lives here rather than in alembic/env.py so it can be imported and tested;
# env.py runs migrations at import time and cannot be imported from a test.
EXTERNAL_TABLES = frozenset({"langchain_pg_collection", "langchain_pg_embedding"})


def include_object(object_, name, type_, reflected, compare_to) -> bool:
    """Alembic autogenerate filter: keep it to the tables this project owns."""
    return not (type_ == "table" and name in EXTERNAL_TABLES)


# A document's lifecycle. Kept as a CHECK constraint over plain text rather than
# a Postgres ENUM type: adding a value to an ENUM needs its own migration and
# cannot run inside a transaction on older servers, which is a lot of ceremony
# for a list that will grow.
STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_READY = "ready"
STATUS_FAILED = "failed"

DOCUMENT_STATUSES = (STATUS_PENDING, STATUS_PROCESSING, STATUS_READY, STATUS_FAILED)

# Statuses where the researcher is still waiting, so the UI keeps polling.
IN_PROGRESS_STATUSES = (STATUS_PENDING, STATUS_PROCESSING)

# Derived from the tuple above so the two cannot drift. Migrations deliberately
# do NOT import this: a migration is a frozen snapshot of one past schema, and
# a status added later arrives with its own migration rather than silently
# changing what an old one means.
_STATUS_LIST_SQL = ", ".join(f"'{status}'" for status in DOCUMENT_STATUSES)
STATUS_CHECK_CONDITION = f"status IN ({_STATUS_LIST_SQL})"


def _utcnow() -> datetime:
    """Timezone-aware UTC. datetime.utcnow() is naive and deprecated in 3.12."""
    return datetime.now(timezone.utc)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # The Cognito sub of the owner. Every query filters on it, exactly as
    # retrieval does on chunk metadata -- see ARCHITECTURE.md, "Per-user data
    # and persistence".
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)

    filename: Mapped[str] = mapped_column(String(255), nullable=False)

    # Where the bytes live: users/{user_id}/documents/{filename}. Stored rather
    # than recomputed so a later change to the key layout cannot strand the
    # objects already uploaded under the old one.
    s3_key: Mapped[str] = mapped_column(Text, nullable=False)

    # SHA-256 of the uploaded bytes. Null until the upload completes. Lets a
    # re-upload of identical content skip parsing entirely, which is the
    # idempotency principle in ARCHITECTURE.md ("re-running only reprocesses
    # what changed"). Distinct from the unique constraint below: the constraint
    # decides WHICH document this is, the hash decides whether it CHANGED.
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Both defaults on purpose, here and below: the Python default keeps an ORM
    # insert from needing a round trip, while the server default is what saves
    # an INSERT that bypasses the ORM -- a psql fix, a backfill, another
    # service -- from failing on NOT NULL.
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=STATUS_PENDING, server_default=STATUS_PENDING
    )

    # Why processing failed, in words a researcher can act on. The counterpart
    # to KNOWN_ISSUES.md's complaint that a scanned PDF ingests as zero chunks
    # "with nothing telling the researcher why".
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Decided per document at upload by checking for a text layer, instead of
    # the global RAG_DO_OCR guess. OCR costs roughly 90 seconds per run and
    # finds nothing on born-digital papers, so it must stay opt-in per file.
    needs_ocr: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Unused in Phase 8. Present because ARCHITECTURE.md calls projects "worth
    # modeling rather than bolting on later", and a nullable column now costs
    # nothing while saving a table rewrite when projects land.
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    # onupdate stays Python-side and has no server equivalent here: a server
    # default only fires on INSERT, so without it an UPDATE would leave
    # updated_at showing the creation time forever.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
        onupdate=_utcnow,
    )

    __table_args__ = (
        # One row per filename per researcher. This is what makes re-uploading
        # a corrected file REPLACE its chunks rather than duplicate them --
        # the bug recorded in KNOWN_ISSUES.md. Two researchers may each hold a
        # file of the same name; they are different documents.
        # Named in full rather than left to the convention: the "uq" pattern
        # interpolates only the first column, so an unnamed composite would
        # render uq_documents_user_id, which reads as one row per user and
        # hides that the filename is half the key.
        UniqueConstraint("user_id", "filename", name="uq_documents_user_id_filename"),
        # name="status", not the full name -- the "ck" convention interpolates
        # whatever is passed here into ck_%(table_name)s_%(constraint_name)s.
        CheckConstraint(STATUS_CHECK_CONDITION, name="status"),
        # Every listing is "this researcher's documents, newest first".
        Index("ix_documents_user_created", "user_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Document {self.filename!r} status={self.status!r}>"
