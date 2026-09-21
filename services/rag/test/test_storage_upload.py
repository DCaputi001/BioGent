"""Unit tests for the upload half of app.storage.

Filename handling is the security-sensitive part: the name comes from a
browser, is chosen by the person uploading, and ends up inside an S3 key that
decides which researcher's prefix the object lands in. These tests treat it as
hostile input rather than as a name.

No AWS: the presign tests pass a fake client and assert on what would be sent.
"""

import pytest

from app import config, storage

USER = "cognito-sub-of-a-researcher"


class FakeS3:
    """Records the presign call instead of talking to S3."""

    def __init__(self, result=None):
        self.presign_calls = []
        self.deleted = []
        self.result = result or {"url": "https://bucket.s3.amazonaws.com/", "fields": {}}

    def generate_presigned_post(self, **kwargs):
        self.presign_calls.append(kwargs)
        return self.result

    def delete_object(self, **kwargs):
        self.deleted.append(kwargs)


# --- filename sanitization ---------------------------------------------------


@pytest.mark.parametrize(
    "hostile",
    [
        "../../../etc/passwd.pdf",
        "..\\..\\windows\\system32\\evil.pdf",
        "/absolute/path/paper.pdf",
        "subdir/paper.pdf",
    ],
)
def test_directory_components_are_stripped(hostile):
    """A filename must never be able to climb out of its owner's prefix."""
    assert "/" not in storage.sanitize_filename(hostile)
    assert "\\" not in storage.sanitize_filename(hostile)
    assert ".." not in storage.sanitize_filename(hostile)


def test_a_traversal_attempt_still_lands_in_the_uploaders_own_prefix():
    key = storage.build_user_key(USER, "../../other-researcher/secret.pdf")

    assert key == f"users/{USER}/documents/secret.pdf"


def test_spaces_and_punctuation_become_safe_characters():
    assert storage.sanitize_filename("My Paper (final) v2.pdf") == "My_Paper_final_v2.pdf"


def test_the_extension_survives_a_very_long_name():
    """Truncation must not eat the suffix: it decides how the file is parsed."""
    long_name = "a" * 500 + ".pdf"

    cleaned = storage.sanitize_filename(long_name)

    assert cleaned.endswith(".pdf")
    assert len(cleaned) <= storage.MAX_FILENAME_LENGTH


def test_a_filename_with_nothing_usable_is_rejected():
    """Better a clear error than a presigned URL pointing at the prefix itself."""
    with pytest.raises(ValueError):
        storage.sanitize_filename("///")


def test_unicode_is_replaced_rather_than_passed_through():
    """S3 accepts these, but an allowlist avoids arguing about which are safe."""
    assert storage.sanitize_filename("papier-Ã©tude.pdf") == "papier-_tude.pdf"


# --- presigned upload --------------------------------------------------------


def test_the_presign_pins_the_key_so_it_cannot_be_redirected():
    client = FakeS3()

    storage.presigned_upload_post("users/abc/documents/p.pdf", bucket="b", client=client)

    assert client.presign_calls[0]["Key"] == "users/abc/documents/p.pdf"
    assert client.presign_calls[0]["Bucket"] == "b"


def test_the_presign_carries_a_size_limit_s3_will_enforce():
    """The whole reason for POST over PUT.

    A presigned PUT has no policy, so a size limit on one would be advisory and
    the client could ignore it. This condition is applied by S3 itself.
    """
    client = FakeS3()

    storage.presigned_upload_post("k", max_bytes=1234, bucket="b", client=client)

    conditions = client.presign_calls[0]["Conditions"]
    assert ["content-length-range", 1, 1234] in conditions


def test_the_presign_expires():
    client = FakeS3()

    storage.presigned_upload_post("k", expires_in=60, bucket="b", client=client)

    assert client.presign_calls[0]["ExpiresIn"] == 60


def test_presigning_without_a_bucket_configured_says_so():
    with pytest.raises(RuntimeError, match="RAG_S3_BUCKET is not set"):
        storage.presigned_upload_post("k", bucket=None, client=FakeS3())


def test_deleting_an_object_names_the_key():
    client = FakeS3()

    storage.delete_document_object("users/abc/documents/p.pdf", bucket="b", client=client)

    assert client.deleted == [{"Bucket": "b", "Key": "users/abc/documents/p.pdf"}]


def test_the_upload_prefix_matches_the_documented_layout():
    """ARCHITECTURE.md specifies users/{user_id}/documents/."""
    assert storage.build_user_key("u", "p.pdf").startswith(f"{config.USER_UPLOAD_PREFIX}/u/")
