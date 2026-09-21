"""Document storage: fetch source documents from S3 onto local disk for ingestion.

Kept separate from ingest.py on purpose. This module only moves bytes. It
never parses, chunks, or embeds anything, so the Docling/HybridChunker pipeline
stays unaware of where its input came from and keeps reading a plain local
directory, same as with the data/ folder.

The caller owns the destination directory and its cleanup (ingest.py uses a
TemporaryDirectory), so downloaded research documents never outlive the run.

Phase 8 adds the upload direction: presigned POSTs that let a researcher's
browser send bytes straight to S3. They never pass through this service, which
is not only cheaper but necessary -- CloudFront caps a request body at 1MB, so
a real paper could not be routed through /api at all.
"""

import re
from pathlib import Path, PurePosixPath

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app import config

# Must match the file types ingest.py globs for. Downloading anything else
# would cost transfer time for files ingestion silently ignores.
SUPPORTED_SUFFIXES = (".pdf", ".txt", ".md")

# Everything outside this set is replaced in an uploaded filename. Deliberately
# an allowlist: a denylist of "bad" characters has to anticipate every one that
# matters to S3, to a shell, and to a filesystem, and it only takes one miss.
_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")

# S3 object keys can be 1024 bytes. The filename is only part of the key, and
# the documents table caps the column at 255, so keep well inside both.
MAX_FILENAME_LENGTH = 200


def sanitize_filename(filename: str) -> str:
    """Reduce a researcher-supplied filename to something safe as an S3 key.

    The filename arrives from a browser and is attacker-controlled, so it is
    treated the same way _safe_local_path treats an S3 key: assume it is
    hostile and constrain it, rather than assume it is a name.

    Strips any directory component, so "../../other-user/secret.pdf" becomes
    "secret.pdf" and cannot climb out of the caller's own prefix. Raises
    ValueError when nothing usable is left, since an empty key would otherwise
    become a presigned URL pointing at the prefix itself.
    """
    # PurePosixPath, not Path: the input uses browser/S3 separators, and on
    # Windows a Path would not treat a backslash the same way S3 will.
    bare = PurePosixPath(filename.replace("\\", "/")).name

    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", bare).strip("._")
    if not cleaned:
        raise ValueError("That filename has no usable characters.")

    if len(cleaned) > MAX_FILENAME_LENGTH:
        # Truncate the stem, never the suffix: the extension is what decides
        # how ingestion parses the file.
        suffix = PurePosixPath(cleaned).suffix[:20]
        cleaned = cleaned[: MAX_FILENAME_LENGTH - len(suffix)] + suffix

    return cleaned


def build_user_key(user_id: str, filename: str) -> str:
    """The S3 key a researcher's document lives at.

    users/{user_id}/documents/{filename}, per ARCHITECTURE.md. The user_id
    comes from a verified token, never from the request, so the prefix cannot
    be steered at another researcher's documents.
    """
    return f"{config.USER_UPLOAD_PREFIX}/{user_id}/documents/{sanitize_filename(filename)}"


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


def _require_bucket(bucket: str | None) -> str:
    if not bucket:
        raise RuntimeError(
            "RAG_S3_BUCKET is not set. Set it in services/rag/.env to work with documents."
        )
    return bucket


def _s3_client(client=None):
    return client or boto3.client("s3", region_name=config.AWS_REGION)


def presigned_upload_post(
    key: str,
    max_bytes: int = config.MAX_UPLOAD_BYTES,
    expires_in: int = config.UPLOAD_URL_TTL_SECONDS,
    bucket: str | None = config.S3_BUCKET,
    client=None,
) -> dict:
    """A presigned POST the browser submits the file to directly.

    Returns {"url", "fields"} for a multipart form post.

    POST rather than PUT because only POST carries a policy: the
    content-length-range condition below is enforced by S3 itself, which
    rejects an oversized upload before storing it. A presigned PUT has no such
    condition, so a size limit on one could only ever be a suggestion the
    client is free to ignore.

    The key is fixed by the policy, so a caller cannot redirect the upload to
    another researcher's prefix.
    """
    bucket = _require_bucket(bucket)

    try:
        return _s3_client(client).generate_presigned_post(
            Bucket=bucket,
            Key=key,
            Fields={"Content-Type": "application/octet-stream"},
            Conditions=[
                {"Content-Type": "application/octet-stream"},
                ["content-length-range", 1, max_bytes],
            ],
            ExpiresIn=expires_in,
        )
    except (ClientError, BotoCoreError) as exc:
        raise RuntimeError(
            f"Could not create an upload URL for s3://{bucket}/{key}. "
            f"{config.AWS_CREDENTIALS_HINT}"
        ) from exc


def download_document(key: str, dest: Path, bucket: str | None = config.S3_BUCKET, client=None):
    """Fetch one uploaded document to a local path, for the worker to parse."""
    bucket = _require_bucket(bucket)
    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        _s3_client(client).download_file(bucket, key, str(dest))
    except (ClientError, BotoCoreError) as exc:
        raise RuntimeError(
            f"Could not download s3://{bucket}/{key}. {config.AWS_CREDENTIALS_HINT}"
        ) from exc

    return dest


def delete_document_object(key: str, bucket: str | None = config.S3_BUCKET, client=None) -> None:
    """Remove an uploaded document's bytes.

    S3 treats deleting a key that is not there as success, so this is safe to
    call for a document whose upload never completed.
    """
    bucket = _require_bucket(bucket)

    try:
        _s3_client(client).delete_object(Bucket=bucket, Key=key)
    except (ClientError, BotoCoreError) as exc:
        raise RuntimeError(
            f"Could not delete s3://{bucket}/{key}. {config.AWS_CREDENTIALS_HINT}"
        ) from exc


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
    bucket = _require_bucket(bucket)
    client = _s3_client(client)
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
            f"Check RAG_S3_BUCKET. {config.AWS_CREDENTIALS_HINT}"
        ) from exc

    return downloaded
