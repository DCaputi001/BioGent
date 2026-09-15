"""Unit tests for app.storage — S3 download logic against an in-memory fake client.

No network and no AWS credentials: a fake boto3 client returns canned
list_objects_v2 pages and writes placeholder bytes on download. This checks
which keys are downloaded and where they land. Talking to real S3 is left to
the manual `--from-s3` check.
"""

from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from app.storage import download_documents_from_s3

BUCKET = "test-bucket"


class FakePaginator:
    def __init__(self, pages: list[list[str]]):
        self._pages = pages

    # Capitalized parameter names mirror boto3's keyword arguments.
    def paginate(self, Bucket: str, Prefix: str):
        for keys in self._pages:
            yield {"Contents": [{"Key": key} for key in keys if key.startswith(Prefix)]}


class FakeS3Client:
    """Stands in for boto3's S3 client; records every key it was asked to download."""

    def __init__(self, pages: list[list[str]]):
        self._pages = pages
        self.downloaded_keys: list[str] = []

    def get_paginator(self, operation_name: str) -> FakePaginator:
        assert operation_name == "list_objects_v2"
        return FakePaginator(self._pages)

    def download_file(self, bucket: str, key: str, filename: str) -> None:
        self.downloaded_keys.append(key)
        Path(filename).write_bytes(b"placeholder")


class FailingS3Client:
    def get_paginator(self, operation_name: str):
        raise ClientError(
            {"Error": {"Code": "NoSuchBucket", "Message": "The bucket does not exist"}},
            "ListObjectsV2",
        )


def test_downloads_only_supported_document_types(tmp_path: Path):
    client = FakeS3Client([["paper.pdf", "notes.txt", "readme.md", "table.docx", "folder/"]])

    downloaded = download_documents_from_s3(tmp_path, bucket=BUCKET, prefix="", client=client)

    assert sorted(p.name for p in downloaded) == ["notes.txt", "paper.pdf", "readme.md"]
    assert sorted(client.downloaded_keys) == ["notes.txt", "paper.pdf", "readme.md"]


def test_preserves_nested_key_layout(tmp_path: Path):
    client = FakeS3Client([["a/b/paper.pdf"]])

    download_documents_from_s3(tmp_path, bucket=BUCKET, prefix="", client=client)

    assert (tmp_path / "a" / "b" / "paper.pdf").is_file()


def test_strips_prefix_from_local_path(tmp_path: Path):
    client = FakeS3Client([["papers/2026/paper.pdf", "other/skip.pdf"]])

    downloaded = download_documents_from_s3(
        tmp_path, bucket=BUCKET, prefix="papers/", client=client
    )

    assert downloaded == [(tmp_path / "2026" / "paper.pdf").resolve()]
    assert (tmp_path / "2026" / "paper.pdf").is_file()


def test_skips_keys_that_escape_destination(tmp_path: Path):
    """Regression guard: S3 keys are arbitrary strings, so "../" in a key must
    never let a download write outside the destination directory.
    """
    dest = tmp_path / "dest"
    dest.mkdir()
    client = FakeS3Client([["../escape.pdf", "safe.pdf"]])

    downloaded = download_documents_from_s3(dest, bucket=BUCKET, prefix="", client=client)

    assert [p.name for p in downloaded] == ["safe.pdf"]
    assert not (tmp_path / "escape.pdf").exists()
    assert client.downloaded_keys == ["safe.pdf"]


def test_handles_multiple_pages(tmp_path: Path):
    client = FakeS3Client([["one.pdf", "two.pdf"], ["three.txt"]])

    downloaded = download_documents_from_s3(tmp_path, bucket=BUCKET, prefix="", client=client)

    assert len(downloaded) == 3


def test_missing_bucket_raises_clear_error(tmp_path: Path):
    with pytest.raises(RuntimeError, match="RAG_S3_BUCKET is not set"):
        download_documents_from_s3(tmp_path, bucket=None, client=FakeS3Client([]))


def test_s3_failure_is_wrapped_with_bucket_name(tmp_path: Path):
    with pytest.raises(RuntimeError, match=f"s3://{BUCKET}"):
        download_documents_from_s3(tmp_path, bucket=BUCKET, prefix="", client=FailingS3Client())
