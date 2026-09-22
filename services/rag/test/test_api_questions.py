"""HTTP contract for question history, against a stubbed chain and database.

Two properties matter most. History is owner-scoped like documents: one
researcher can never list or delete another's questions. And history is
secondary to the answer: if saving it fails, the answer the researcher already
paid Anthropic for must still come back.
"""

import contextlib
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import api, db, query, questions
from app.auth import require_user

USER = "cognito-sub-of-the-signed-in-researcher"
OTHER_USER = "cognito-sub-of-someone-else"
API_KEY = "sk-ant-test-key"
QUESTION_ID = uuid.uuid4()
ANSWER = "PIEZO channels transduce mechanical force."


class FakeEntry:
    def __init__(self, user_id=USER, **overrides):
        self.id = QUESTION_ID
        self.user_id = user_id
        self.question = "What does PIEZO do?"
        self.answer = ANSWER
        self.sources = ["piezo.pdf"]
        self.created_at = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
        self.__dict__.update(overrides)


@pytest.fixture
def client(monkeypatch) -> TestClient:
    api.app.dependency_overrides[require_user] = lambda: USER
    monkeypatch.setattr(db, "session_scope", lambda: contextlib.nullcontext(None))
    monkeypatch.setattr(
        query,
        "ask_with_context",
        lambda question, retriever, anthropic_api_key=None: {
            "answer": ANSWER,
            "context": "...",
            "sources": ["piezo.pdf"],
        },
    )
    monkeypatch.setattr(query, "get_retriever", lambda user_id: f"retriever-for:{user_id}")
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


def _ask(client):
    return client.post(
        f"{api.API_PREFIX}/ask",
        json={"question": "What does PIEZO do?"},
        headers={api.API_KEY_HEADER: API_KEY},
    )


def _stub_owned_entry(monkeypatch, entry):
    """questions.get returns the entry only when the owner matches, as the real one does."""

    def get(session, user_id, question_id):
        return entry if (entry.user_id == user_id and entry.id == question_id) else None

    monkeypatch.setattr(questions, "get", get)


# --- recording on /ask -------------------------------------------------------


def test_an_answered_question_is_saved_under_the_askers_account(client, monkeypatch):
    saved = []

    def record(session, user_id, question, answer, sources):
        saved.append((user_id, question, answer, sources))
        return FakeEntry()

    monkeypatch.setattr(questions, "record", record)

    response = _ask(client)

    assert response.status_code == 200
    assert response.json()["id"] == str(QUESTION_ID)
    # The owner comes from the verified token, like everything else.
    assert saved == [(USER, "What does PIEZO do?", ANSWER, ["piezo.pdf"])]


def test_the_answer_survives_a_failed_history_write(client, monkeypatch):
    """The researcher already paid Anthropic for this answer.

    Failing the whole request because a secondary feature could not save would
    throw that answer away. It comes back; it just has no history id.
    """

    def broken_record(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(questions, "record", broken_record)

    response = _ask(client)

    assert response.status_code == 200
    assert response.json()["answer"] == ANSWER
    assert response.json()["id"] is None


def test_a_failed_answer_is_not_saved(client, monkeypatch):
    """Only answers go into history -- not errors dressed up as entries."""

    def fail(*args, **kwargs):
        raise RuntimeError("chain failed")

    monkeypatch.setattr(query, "ask_with_context", fail)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("a failed question must not be recorded")

    monkeypatch.setattr(questions, "record", fail_if_called)

    response = _ask(client)

    assert response.status_code == 500


# --- listing -----------------------------------------------------------------


def test_listing_returns_only_this_researchers_history(client, monkeypatch):
    asked_for = []
    monkeypatch.setattr(
        questions,
        "list_for_user",
        lambda session, user_id, limit: asked_for.append(user_id) or [FakeEntry()],
    )

    response = client.get(f"{api.API_PREFIX}/questions")
    body = response.json()

    assert response.status_code == 200
    assert asked_for == [USER]
    assert body[0]["question"] == "What does PIEZO do?"
    assert body[0]["answer"] == ANSWER
    assert body[0]["sources"] == ["piezo.pdf"]
    assert body[0]["created_at"].startswith("2026-09-21")


def test_the_limit_is_capped(client):
    """A caller cannot ask for an unbounded history in one response."""
    response = client.get(f"{api.API_PREFIX}/questions", params={"limit": 10_000})

    assert response.status_code == 422


def test_history_needs_a_signed_in_researcher():
    response = TestClient(api.app).get(f"{api.API_PREFIX}/questions")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_auth"


# --- deleting ----------------------------------------------------------------


def test_deleting_an_entry_removes_it(client, monkeypatch):
    removed = []
    _stub_owned_entry(monkeypatch, FakeEntry())
    monkeypatch.setattr(questions, "delete", lambda session, entry: removed.append(entry.id))

    response = client.delete(f"{api.API_PREFIX}/questions/{QUESTION_ID}")

    assert response.status_code == 204
    assert removed == [QUESTION_ID]


def test_deleting_another_researchers_entry_is_a_404_and_touches_nothing(client, monkeypatch):
    """Not a 403: distinguishing them would confirm the entry exists."""
    _stub_owned_entry(monkeypatch, FakeEntry(user_id=OTHER_USER))

    def fail_if_called(*args, **kwargs):
        raise AssertionError("another researcher's history must not be touched")

    monkeypatch.setattr(questions, "delete", fail_if_called)

    response = client.delete(f"{api.API_PREFIX}/questions/{QUESTION_ID}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "question_not_found"
