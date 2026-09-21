"""HTTP contract for the document routes, against stubbed storage and database.

The isolation cases matter most here. A document id is a UUID a caller could
hold from anywhere -- kept after losing access, or simply guessed -- so every
route has to prove it refuses one belonging to someone else rather than
trusting that the id came from a legitimate place.
"""

import contextlib
import uuid

import pytest
from fastapi.testclient import TestClient

from app import api, db, documents, ingest, queue, storage
from app.auth import require_user

USER = "cognito-sub-of-the-signed-in-researcher"
OTHER_USER = "cognito-sub-of-someone-else"
DOCUMENT_ID = uuid.uuid4()


class FakeDocument:
    def __init__(self, user_id=USER, **overrides):
        self.id = DOCUMENT_ID
        self.user_id = user_id
        self.filename = "paper.pdf"
        self.s3_key = f"users/{user_id}/documents/paper.pdf"
        self.status = "ready"
        self.chunk_count = 12
        self.error_message = None
        self.__dict__.update(overrides)


@pytest.fixture
def client(monkeypatch) -> TestClient:
    """A signed-in researcher, with every external boundary stubbed out."""
    api.app.dependency_overrides[require_user] = lambda: USER
    monkeypatch.setattr(db, "session_scope", lambda: contextlib.nullcontext(None))
    monkeypatch.setattr(api.config, "INGESTION_QUEUE_URL", "https://sqs.example/queue")
    monkeypatch.setattr(
        storage,
        "presigned_upload_post",
        lambda key, **kw: {"url": "https://bucket.s3.amazonaws.com/", "fields": {"key": key}},
    )
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


def _stub_owned_document(monkeypatch, document=None):
    """documents.get returns a row only when the owner matches, as the real one does."""
    row = document if document is not None else FakeDocument()

    def get(session, user_id, document_id):
        return row if (row.user_id == user_id and row.id == document_id) else None

    monkeypatch.setattr(documents, "get", get)
    return row


# --- creating an upload ------------------------------------------------------


def test_requesting_an_upload_returns_a_presigned_post(client, monkeypatch):
    created = FakeDocument(status="pending")
    monkeypatch.setattr(documents, "create_pending", lambda s, u, f, k: created)

    response = client.post(f"{api.API_PREFIX}/documents", json={"filename": "paper.pdf"})
    body = response.json()

    assert response.status_code == 200
    assert body["upload_url"].startswith("https://")
    assert body["document_id"] == str(DOCUMENT_ID)
    assert body["max_bytes"] > 0


def test_the_upload_key_is_built_from_the_token_not_the_request(client, monkeypatch):
    """The whole isolation boundary, in one assertion.

    A filename containing a traversal must not be able to steer the upload at
    another researcher's prefix.
    """
    keys = []
    monkeypatch.setattr(
        documents,
        "create_pending",
        lambda s, u, f, k: keys.append(k) or FakeDocument(status="pending"),
    )

    client.post(
        f"{api.API_PREFIX}/documents",
        json={"filename": f"../../../{OTHER_USER}/stolen.pdf"},
    )

    assert keys[0] == f"users/{USER}/documents/stolen.pdf"
    assert OTHER_USER not in keys[0]


def test_an_unsupported_file_type_is_refused_before_anything_is_reserved(client, monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("no row should be created for a file we cannot read")

    monkeypatch.setattr(documents, "create_pending", fail_if_called)

    response = client.post(f"{api.API_PREFIX}/documents", json={"filename": "virus.exe"})

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_file_type"


def test_uploads_are_refused_when_nothing_can_process_them(client, monkeypatch):
    """Accepting a file with no queue behind it would strand it at 'pending'."""
    monkeypatch.setattr(api.config, "INGESTION_QUEUE_URL", None)

    response = client.post(f"{api.API_PREFIX}/documents", json={"filename": "paper.pdf"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "upload_unavailable"


def test_an_upload_request_needs_a_signed_in_researcher(monkeypatch):
    monkeypatch.setattr(db, "session_scope", lambda: contextlib.nullcontext(None))

    response = TestClient(api.app).post(
        f"{api.API_PREFIX}/documents", json={"filename": "paper.pdf"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_auth"


# --- completing an upload ----------------------------------------------------


def test_completing_an_upload_queues_it(client, monkeypatch):
    _stub_owned_document(monkeypatch, FakeDocument(status="pending"))
    monkeypatch.setattr(documents, "mark_processing", lambda s, d: d)
    queued = []
    monkeypatch.setattr(queue, "enqueue", lambda document_id, **kw: queued.append(document_id))

    response = client.post(f"{api.API_PREFIX}/documents/{DOCUMENT_ID}/complete")

    assert response.status_code == 200
    assert queued == [DOCUMENT_ID]


def test_completing_another_researchers_document_is_a_404(client, monkeypatch):
    """Not a 403: distinguishing them would confirm the document exists."""
    _stub_owned_document(monkeypatch, FakeDocument(user_id=OTHER_USER))

    def fail_if_called(*args, **kwargs):
        raise AssertionError("another researcher's document must not be queued")

    monkeypatch.setattr(queue, "enqueue", fail_if_called)

    response = client.post(f"{api.API_PREFIX}/documents/{DOCUMENT_ID}/complete")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "document_not_found"


# --- listing -----------------------------------------------------------------


def test_listing_returns_only_this_researchers_documents(client, monkeypatch):
    asked_for = []
    monkeypatch.setattr(
        documents,
        "list_for_user",
        lambda session, user_id: asked_for.append(user_id) or [FakeDocument()],
    )

    response = client.get(f"{api.API_PREFIX}/documents")

    assert response.status_code == 200
    assert asked_for == [USER]
    assert response.json()[0]["filename"] == "paper.pdf"


def test_a_failed_document_reports_why(client, monkeypatch):
    """The status the UI polls for, and the reason it shows."""
    monkeypatch.setattr(
        documents,
        "list_for_user",
        lambda s, u: [FakeDocument(status="failed", error_message="No readable text.")],
    )

    body = client.get(f"{api.API_PREFIX}/documents").json()

    assert body[0]["status"] == "failed"
    assert body[0]["error_message"] == "No readable text."


# --- deleting ----------------------------------------------------------------


def test_deleting_removes_chunks_then_the_row_then_the_object(client, monkeypatch):
    """Order matters: chunks first.

    If the row went first and chunk deletion then failed, the chunks would stay
    retrievable with nothing left recording that they exist.
    """
    order = []
    _stub_owned_document(monkeypatch)
    monkeypatch.setattr(
        ingest, "delete_document_chunks", lambda *a, **kw: order.append("chunks")
    )
    monkeypatch.setattr(documents, "delete", lambda s, d: order.append("row"))
    monkeypatch.setattr(storage, "delete_document_object", lambda key, **kw: order.append("object"))

    response = client.delete(f"{api.API_PREFIX}/documents/{DOCUMENT_ID}")

    assert response.status_code == 204
    assert order == ["chunks", "row", "object"]


def test_deleting_another_researchers_document_touches_nothing(client, monkeypatch):
    _stub_owned_document(monkeypatch, FakeDocument(user_id=OTHER_USER))

    def fail_if_called(*args, **kwargs):
        raise AssertionError("another researcher's data must not be touched")

    monkeypatch.setattr(ingest, "delete_document_chunks", fail_if_called)
    monkeypatch.setattr(documents, "delete", fail_if_called)
    monkeypatch.setattr(storage, "delete_document_object", fail_if_called)

    response = client.delete(f"{api.API_PREFIX}/documents/{DOCUMENT_ID}")

    assert response.status_code == 404


def test_deleting_a_document_that_does_not_exist_is_a_404(client, monkeypatch):
    monkeypatch.setattr(documents, "get", lambda s, u, d: None)

    response = client.delete(f"{api.API_PREFIX}/documents/{uuid.uuid4()}")

    assert response.status_code == 404


def test_a_malformed_document_id_is_rejected_readably(client):
    """FastAPI's default 422 body is a list of pydantic dicts; ours is a sentence."""
    response = client.delete(f"{api.API_PREFIX}/documents/not-a-uuid")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
