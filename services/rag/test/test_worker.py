"""Unit tests for app.worker, with the database, S3 and Docling all faked.

The behaviour worth pinning is what happens when things go wrong. A worker that
raises on one bad file stops every other researcher's uploads behind it, and a
document that fails silently is the exact complaint KNOWN_ISSUES.md makes about
scanned PDFs ingesting as zero chunks with nothing saying why.
"""

import contextlib
from pathlib import Path

import pytest

from app import worker
from app.models import STATUS_READY


class FakeDocument:
    def __init__(self, **overrides):
        self.id = "doc-1"
        self.user_id = "researcher-sub"
        self.filename = "paper.pdf"
        self.s3_key = "users/researcher-sub/documents/paper.pdf"
        self.content_hash = None
        self.chunk_count = None
        self.status = "pending"
        self.error_message = None
        self.needs_ocr = False
        self.__dict__.update(overrides)


class FakeChunk:
    def __init__(self, text: str):
        self.page_content = text


@pytest.fixture
def document() -> FakeDocument:
    return FakeDocument()


@pytest.fixture
def wired(monkeypatch, document, tmp_path):
    """Replace every boundary the worker touches, and record what it did."""
    calls = {"marked": [], "written": None, "downloads": []}

    monkeypatch.setattr(worker.db, "session_scope", lambda: contextlib.nullcontext(None))
    monkeypatch.setattr(worker.documents, "get_for_processing", lambda session, _id: document)

    def mark_processing(session, doc):
        calls["marked"].append("processing")
        return doc

    def mark_ready(session, doc, count, digest, ocr):
        calls["marked"].append("ready")
        doc.chunk_count, doc.content_hash, doc.needs_ocr = count, digest, ocr
        return doc

    def mark_failed(session, doc, message):
        calls["marked"].append("failed")
        doc.error_message = message
        return doc

    monkeypatch.setattr(worker.documents, "mark_processing", mark_processing)
    monkeypatch.setattr(worker.documents, "mark_ready", mark_ready)
    monkeypatch.setattr(worker.documents, "mark_failed", mark_failed)

    def download(key, dest, *args, **kwargs):
        calls["downloads"].append(key)
        Path(dest).write_bytes(b"pretend pdf bytes")
        return dest

    monkeypatch.setattr(worker.storage, "download_document", download)

    def replace(chunks, document_id, previous_count, store=None):
        calls["written"] = (len(chunks), document_id, previous_count)
        return len(chunks)

    monkeypatch.setattr(worker.ingest, "replace_document_chunks", replace)
    return calls


def _chunks_of(*texts):
    return lambda *args, **kwargs: [FakeChunk(t) for t in texts]


def test_a_readable_document_becomes_ready_with_its_chunk_count(monkeypatch, wired, document):
    monkeypatch.setattr(worker.ingest, "chunk_one_file", _chunks_of("a" * 500, "b" * 500))

    assert worker.process_document("doc-1") == STATUS_READY
    assert wired["marked"] == ["processing", "ready"]
    assert document.chunk_count == 2
    assert document.content_hash is not None


def test_a_file_yielding_no_text_fails_with_a_reason_a_researcher_can_act_on(
    monkeypatch, wired, document
):
    """The KNOWN_ISSUES.md complaint, answered.

    A scanned PDF previously ingested as zero chunks with nothing explaining
    why. Now it fails visibly and the message mentions the actual cause.
    """
    monkeypatch.setattr(worker.ingest, "chunk_one_file", _chunks_of())

    assert worker.process_document("doc-1") == "failed"
    assert wired["marked"] == ["processing", "failed"]
    assert "scan" in document.error_message.lower()


def test_a_sparse_parse_is_retried_with_ocr_before_giving_up(monkeypatch, wired, document):
    """OCR is decided per document, not from the global RAG_DO_OCR setting."""
    attempts = []

    def chunk_one_file(path, user_id, document_id, do_ocr=False, **kwargs):
        attempts.append(do_ocr)
        return [FakeChunk("x" * 500)] if do_ocr else [FakeChunk("tiny")]

    monkeypatch.setattr(worker.ingest, "chunk_one_file", chunk_one_file)

    assert worker.process_document("doc-1") == STATUS_READY
    assert attempts == [False, True]
    assert document.needs_ocr is True


def test_identical_bytes_skip_reprocessing_but_stay_ready(monkeypatch, wired, document):
    """Re-uploading an unchanged file must not re-embed it.

    The hash is what makes a redundant upload cheap; the parse and embed it
    skips are the expensive half.
    """
    monkeypatch.setattr(worker.ingest, "chunk_one_file", _chunks_of("a" * 500))
    worker.process_document("doc-1")
    first_hash, first_count = document.content_hash, document.chunk_count

    def fail_if_called(*args, **kwargs):
        raise AssertionError("an unchanged document must not be re-parsed")

    monkeypatch.setattr(worker.ingest, "chunk_one_file", fail_if_called)
    wired["written"] = None

    assert worker.process_document("doc-1") == STATUS_READY
    assert document.content_hash == first_hash
    assert document.chunk_count == first_count
    assert wired["written"] is None


def test_the_previous_chunk_count_is_passed_so_a_shrinking_document_is_trimmed(
    monkeypatch, wired, document
):
    """A corrected file with fewer chunks must not leave the old tail behind."""
    document.chunk_count = 9
    document.content_hash = "a-different-hash"
    monkeypatch.setattr(worker.ingest, "chunk_one_file", _chunks_of("a" * 500, "b" * 500))

    worker.process_document("doc-1")

    assert wired["written"] == (2, "doc-1", 9)


def test_an_unexpected_failure_fails_the_document_not_the_worker(monkeypatch, wired, document):
    def boom(*args, **kwargs):
        raise RuntimeError("Docling fell over")

    monkeypatch.setattr(worker.ingest, "chunk_one_file", boom)

    # No exception escapes: the loop must survive one bad file.
    assert worker.process_document("doc-1") == "failed"
    assert document.error_message is not None
    # The researcher sees a readable sentence, not a stack trace.
    assert "Docling fell over" not in document.error_message


def test_a_document_deleted_before_the_worker_reached_it_is_not_an_error(monkeypatch):
    monkeypatch.setattr(worker.db, "session_scope", lambda: contextlib.nullcontext(None))
    monkeypatch.setattr(worker.documents, "get_for_processing", lambda session, _id: None)

    assert worker.process_document("doc-gone") == "missing"


# --- message handling --------------------------------------------------------


def test_a_message_is_acknowledged_after_the_work_is_recorded(monkeypatch):
    acknowledged = []
    monkeypatch.setattr(worker.queue, "delete", lambda handle, **kw: acknowledged.append(handle))
    monkeypatch.setattr(worker, "process_document", lambda _id, store=None: STATUS_READY)

    worker.handle_message({"Body": '{"document_id": "doc-1"}', "ReceiptHandle": "r-1"})

    assert acknowledged == ["r-1"]


def test_an_unreadable_message_is_acknowledged_rather_than_retried_forever(monkeypatch):
    """Retrying a message that cannot be parsed reaches the same answer.

    Acknowledging it spends no redrive budget getting there.
    """
    acknowledged = []
    monkeypatch.setattr(worker.queue, "delete", lambda handle, **kw: acknowledged.append(handle))

    def fail_if_called(*args, **kwargs):
        raise AssertionError("nothing should be processed for a junk message")

    monkeypatch.setattr(worker, "process_document", fail_if_called)

    worker.handle_message({"Body": "not json", "ReceiptHandle": "r-2"})

    assert acknowledged == ["r-2"]


# --- text-layer detection ----------------------------------------------------


def test_a_born_digital_paper_does_not_trigger_ocr():
    assert worker.needs_ocr([FakeChunk("x" * 5000)]) is False


def test_an_empty_parse_triggers_ocr():
    assert worker.needs_ocr([]) is True


def test_the_hash_is_stable_for_the_same_bytes(tmp_path):
    first, second = tmp_path / "a.pdf", tmp_path / "b.pdf"
    first.write_bytes(b"identical")
    second.write_bytes(b"identical")

    assert worker.file_digest(first) == worker.file_digest(second)


def test_the_hash_changes_when_the_bytes_do(tmp_path):
    path = tmp_path / "a.pdf"
    path.write_bytes(b"original")
    before = worker.file_digest(path)
    path.write_bytes(b"corrected")

    assert worker.file_digest(path) != before
