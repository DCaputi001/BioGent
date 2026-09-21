"""Unit tests for app.models — the schema contract, without a database.

These guard the parts of the table definition that other code depends on by
name. A renamed constraint or a status value that exists in Python but not in
the CHECK constraint would both pass a type checker and fail only at INSERT
time against real Postgres, which is the slowest possible place to find out.
"""

from datetime import timezone

from sqlalchemy import CheckConstraint, UniqueConstraint

from app.models import (
    DOCUMENT_STATUSES,
    IN_PROGRESS_STATUSES,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_READY,
    Document,
    _utcnow,
    include_object,
)


def _constraint(kind) -> object:
    return next(c for c in Document.__table__.constraints if isinstance(c, kind))


def test_every_status_constant_is_permitted_by_the_check_constraint():
    """The Python tuple and the SQL CHECK must not drift apart.

    Adding a status to DOCUMENT_STATUSES without adding it to the constraint
    produces code that looks correct and raises IntegrityError on write.
    """
    check = _constraint(CheckConstraint)
    condition = str(check.sqltext)

    for status in DOCUMENT_STATUSES:
        assert f"'{status}'" in condition


def test_in_progress_statuses_are_real_statuses():
    """The UI polls while a document is in one of these; a typo would hang it."""
    assert set(IN_PROGRESS_STATUSES).issubset(set(DOCUMENT_STATUSES))
    # A finished document must never keep the UI polling.
    assert STATUS_READY not in IN_PROGRESS_STATUSES
    assert STATUS_FAILED not in IN_PROGRESS_STATUSES


def test_one_document_per_filename_per_user():
    """The constraint behind replace-on-reupload.

    Without it, uploading a corrected paper adds a second row and a second set
    of chunks rather than superseding the first — the duplicate-chunk bug in
    KNOWN_ISSUES.md.
    """
    unique = _constraint(UniqueConstraint)

    assert [c.name for c in unique.columns] == ["user_id", "filename"]
    assert unique.name == "uq_documents_user_id_filename"


def test_ownership_and_location_are_required():
    """A row with no owner is unreachable; one with no key has no bytes."""
    assert Document.__table__.c.user_id.nullable is False
    assert Document.__table__.c.s3_key.nullable is False


def test_fields_unknown_until_processing_finishes_are_nullable():
    """These are filled in by the worker, so a pending row must not need them."""
    for column in ("content_hash", "chunk_count", "error_message"):
        assert Document.__table__.c[column].nullable is True


def test_timestamps_are_timezone_aware():
    """Naive timestamps compare wrongly against anything stored with an offset."""
    assert _utcnow().tzinfo is timezone.utc
    assert Document.__table__.c.created_at.type.timezone is True


def test_every_non_nullable_column_the_orm_fills_also_has_a_server_default():
    """An INSERT that bypasses the ORM must still work.

    A psql fix, a backfill, or another service writing this table would
    otherwise hit NOT NULL on columns the ORM was quietly populating.
    """
    for column in ("status", "needs_ocr", "created_at", "updated_at"):
        assert Document.__table__.c[column].server_default is not None, column


def test_status_defaults_to_pending_in_the_database_too():
    rendered = str(Document.__table__.c.status.server_default.arg)

    assert STATUS_PENDING in rendered


def test_updated_at_refreshes_on_update():
    """A server default fires only on INSERT.

    Without the Python-side onupdate, updated_at would show the creation time
    forever and a status change would look like it never happened.
    """
    assert Document.__table__.c.updated_at.onupdate is not None


# --- the autogenerate filter -------------------------------------------------
#
# The highest-stakes code in this file. Without it, `alembic revision
# --autogenerate` sees two tables that no model declares and emits DROP TABLE
# for both -- destroying every embedding in the vector store.


def test_langchain_tables_are_hidden_from_autogenerate():
    for table in ("langchain_pg_collection", "langchain_pg_embedding"):
        assert include_object(None, table, "table", True, None) is False, table


def test_our_own_tables_are_still_managed():
    assert include_object(None, "documents", "table", True, None) is True


def test_the_filter_only_suppresses_tables():
    """A column or index named like one of those tables must not be dropped.

    The check is deliberately scoped to type_ == "table"; without that scoping
    an unrelated object sharing the name would be silently skipped.
    """
    assert include_object(None, "langchain_pg_embedding", "column", True, None) is True
