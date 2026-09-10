"""Unit tests for app.ingest — the plaintext path only.

Deliberately does NOT test load_and_chunk_pdfs() or anything involving
Docling/the embedding model here: those need real model downloads and are
slow, which is exactly what the tests-vs-evals split (ARCHITECTURE.md —
Observability & evaluation) says NOT to put in this fast, no-API-key tier.
Structural correctness of the plaintext path — which needs neither — is
fully testable here.
"""

from pathlib import Path

from app.ingest import load_and_chunk_plaintext


def test_load_and_chunk_plaintext_splits_long_file(tmp_path: Path):
    """A file longer than chunk_size should be split into multiple chunks."""
    long_text = "word " * 1000  # well over any reasonable chunk_size
    (tmp_path / "notes.txt").write_text(long_text, encoding="utf-8")

    chunks = load_and_chunk_plaintext(data_dir=tmp_path, chunk_size=200, chunk_overlap=50)

    assert len(chunks) > 1
    assert all(chunk.metadata["source"] == "notes.txt" for chunk in chunks)


def test_load_and_chunk_plaintext_short_file_is_one_chunk(tmp_path: Path):
    """A file shorter than chunk_size shouldn't be split at all."""
    short_text = "This is a short note."
    (tmp_path / "short.md").write_text(short_text, encoding="utf-8")

    chunks = load_and_chunk_plaintext(data_dir=tmp_path, chunk_size=1000, chunk_overlap=200)

    assert len(chunks) == 1
    assert chunks[0].page_content == short_text


def test_load_and_chunk_plaintext_handles_utf8(tmp_path: Path):
    """Regression guard: the small project hit a real UnicodeDecodeError on
    Windows (cp1252 default) with smart quotes / em dashes in .txt files.
    This confirms non-ASCII characters survive intact.
    """
    text_with_special_chars = "The bike had a \u201csmart\u201d quote and an em dash \u2014 here."
    (tmp_path / "special.txt").write_text(text_with_special_chars, encoding="utf-8")

    chunks = load_and_chunk_plaintext(data_dir=tmp_path)

    assert len(chunks) == 1
    assert "\u201csmart\u201d" in chunks[0].page_content
    assert "\u2014" in chunks[0].page_content


def test_load_and_chunk_plaintext_empty_dir_returns_empty_list(tmp_path: Path):
    """No .txt/.md files present should return an empty list, not raise."""
    chunks = load_and_chunk_plaintext(data_dir=tmp_path)
    assert chunks == []


def test_load_and_chunk_plaintext_ignores_non_text_files(tmp_path: Path):
    """A .pdf sitting in the same directory should be ignored by this
    function — it's load_and_chunk_pdfs()'s job, not this one's.
    """
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "paper.pdf").write_bytes(b"%PDF-1.4 fake content")

    chunks = load_and_chunk_plaintext(data_dir=tmp_path)

    assert len(chunks) == 1
    assert chunks[0].metadata["source"] == "note.txt"