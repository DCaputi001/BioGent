"""Document storage: fetch source documents from S3 onto local disk for ingestion.

Kept separate from ingest.py on purpose. This module only moves bytes. It
never parses, chunks, or embeds anything, so the Docling/HybridChunker pipeline
stays unaware of where its input came from and keeps reading a plain local
directory, same as with the data/ folder.

The caller owns the destination directory and its cleanup (ingest.py uses a
TemporaryDirectory), so downloaded research documents never outlive the run.
"""

from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app import config

# Must match the file types ingest.py globs for. Downloading anything else
# would cost transfer time for files ingestion silently ignores.
SUPPORTED_SUFFIXES = (".pdf", ".txt", ".md")


def _safe_local_path(dest_dir: Path, key: str, prefix: str) -> Path | None:
    """Map an S3 key to a path under dest_dir, or None if it should be skipped.

    Skips "folder" placeholder keys (trailing slash) and any key that would
    resolve outside dest_dir. S3 keys are arbitrary strings, so a key like
    "../../evil.pdf" is legal in a bucket and must not be allowed to write
    outside the download directory.
    """
    if key.endswith("/"):
        return None

    relative_key = key.removeprefix(prefix).lstrip("/")
    if not relative_key:
        return None

    root = dest_dir.resolve()
    local_path = (root / relative_key).resolve()
    if not local_path.is_relative_to(root):
        return None
    return local_path


def download_documents_from_s3(
    dest_dir: Path,
    bucket: str | None = config.S3_BUCKET,
    prefix: str = config.S3_PREFIX,
    client=None,
) -> list[Path]:
    """Download every supported document under s3://bucket/prefix into dest_dir.

    The key's folder layout below the prefix is kept, since ingest.py globs
    recursively. Returns the local paths written, for logging and tests.

    client is injectable so unit tests can pass a fake instead of hitting AWS.
    Raises RuntimeError with the bucket name and what to check on any
    configuration, credential, or S3 failure.
    """
    if not bucket:
        raise RuntimeError(
            "RAG_S3_BUCKET is not set. Set it in services/rag/.env to ingest with --from-s3."
        )

    client = client or boto3.client("s3", region_name=config.S3_REGION)
    downloaded: list[Path] = []

    # The try covers the loop, not just the paginate() call: boto3 paginators
    # are lazy, so a missing bucket or bad credentials only fail on iteration.
    try:
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for s3_object in page.get("Contents", []):
                key = s3_object["Key"]
                if not key.lower().endswith(SUPPORTED_SUFFIXES):
                    continue

                local_path = _safe_local_path(dest_dir, key, prefix)
                if local_path is None:
                    continue

                local_path.parent.mkdir(parents=True, exist_ok=True)
                client.download_file(bucket, key, str(local_path))
                downloaded.append(local_path)
    except (ClientError, BotoCoreError) as exc:
        raise RuntimeError(
            f"Failed to download documents from s3://{bucket}/{prefix}. "
            "Check RAG_S3_BUCKET, AWS credentials, and region in services/rag/.env."
        ) from exc

    return downloaded
