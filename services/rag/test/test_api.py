"""Unit tests for app.api — HTTP contract only, against a stubbed chain.

No API key, no database, no model download: query.ask_with_context and
query.get_retriever are replaced, so these stay in the fast CI tier alongside
the other tests. Whether the chain produces a good answer is the eval
harness's job; this file checks status codes, the error shape, and that the
caller's key is what reaches the chain and never comes back out.
"""

import httpx
import pytest
from anthropic import AuthenticationError, RateLimitError
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app import api, query

API_KEY = "sk-ant-test-key"
QUESTION = "What role does PIEZO play in mechanosensation?"
SOURCE = "PIEZO_provides_an_ancient_molecular_framework_for_.pdf"


def _anthropic_response(status_code: int) -> httpx.Response:
    """The httpx response the Anthropic SDK requires when building an error."""
    return httpx.Response(
        status_code, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    )


@pytest.fixture
def recorded_calls(monkeypatch) -> list[dict]:
    """Stub the chain with a successful answer and record what it was passed."""
    calls: list[dict] = []

    def fake_ask_with_context(question, anthropic_api_key=None, retriever=None):
        calls.append({"question": question, "anthropic_api_key": anthropic_api_key})
        return {
            "answer": "PIEZO channels transduce mechanical force.",
            "context": "...retrieved chunks...",
            "sources": [SOURCE],
        }

    monkeypatch.setattr(query, "ask_with_context", fake_ask_with_context)
    # Guards against a real embedding model load if the cached retriever is
    # ever built eagerly rather than inside the request.
    monkeypatch.setattr(query, "get_retriever", lambda: "fake-retriever")
    return calls


@pytest.fixture
def failing_chain(monkeypatch):
    """Make the chain raise a given exception, as the real one would upstream."""

    def _fail_with(exc: Exception):
        def fake_ask_with_context(question, anthropic_api_key=None, retriever=None):
            raise exc

        monkeypatch.setattr(query, "ask_with_context", fake_ask_with_context)
        monkeypatch.setattr(query, "get_retriever", lambda: "fake-retriever")

    return _fail_with


@pytest.fixture
def client() -> TestClient:
    return TestClient(api.app)


def _ask(client: TestClient, question: str = QUESTION, key: str | None = API_KEY):
    headers = {api.API_KEY_HEADER: key} if key is not None else {}
    return client.post(f"{api.API_PREFIX}/ask", json={"question": question}, headers=headers)


def test_health_needs_no_key_or_database(client):
    response = client.get(f"{api.API_PREFIX}/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_routes_are_served_under_the_api_prefix(client):
    """CloudFront routes /api/* to this service and passes the path through
    unchanged, so an unprefixed route would 404 in production while passing
    every local test that hit it directly.
    """
    assert client.get("/health").status_code == 404
    assert client.post("/ask", json={"question": "x"}).status_code == 404


def test_answers_question_on_callers_key(client, recorded_calls):
    response = _ask(client)

    assert response.status_code == 200
    assert response.json() == {
        "answer": "PIEZO channels transduce mechanical force.",
        "sources": [SOURCE],
    }
    # The key the caller sent is the key the chain ran on — the whole point of
    # the BYO-key flow.
    assert recorded_calls == [{"question": QUESTION, "anthropic_api_key": API_KEY}]


def test_missing_key_header_is_rejected(client, recorded_calls):
    response = _ask(client, key=None)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_api_key"
    assert recorded_calls == []


def test_blank_key_header_is_rejected(client, recorded_calls):
    response = _ask(client, key="   ")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_api_key"
    assert recorded_calls == []


def test_never_falls_back_to_server_environment_key(client, recorded_calls, monkeypatch):
    """Regression guard for the BYO-key decision: a key sitting in the server's
    environment must never answer a request that carried no key of its own,
    because the operator would silently pay for it.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-server-side-key")

    response = _ask(client, key=None)

    assert response.status_code == 401
    assert recorded_calls == []


@pytest.mark.parametrize("question", ["", "   "])
def test_empty_question_is_rejected_before_any_llm_call(client, recorded_calls, question):
    response = _ask(client, question=question)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert recorded_calls == []


def test_rejected_key_returns_actionable_401(client, failing_chain):
    failing_chain(
        AuthenticationError(
            "invalid x-api-key", response=_anthropic_response(401), body=None
        )
    )

    response = _ask(client)
    error = response.json()["error"]

    assert response.status_code == 401
    assert error["code"] == "invalid_api_key"
    assert "console.anthropic.com" in error["message"]
    assert error["retryable"] is False


def test_rate_limit_is_marked_retryable(client, failing_chain):
    failing_chain(
        RateLimitError("slow down", response=_anthropic_response(429), body=None)
    )

    response = _ask(client)
    error = response.json()["error"]

    assert response.status_code == 429
    assert error["code"] == "rate_limited"
    assert error["retryable"] is True


def test_database_failure_does_not_leak_the_connection_string(client, failing_chain):
    """The vector store being down is the operator's problem, not something to
    explain to a researcher with a connection URL in it.
    """
    failing_chain(
        OperationalError(
            "SELECT 1",
            {},
            Exception("could not connect to host db.example.rds.amazonaws.com"),
        )
    )

    response = _ask(client)
    error = response.json()["error"]

    assert response.status_code == 503
    assert error["code"] == "document_store_unavailable"
    assert "rds.amazonaws.com" not in response.text


def test_unexpected_failure_is_generic_not_a_stack_trace(client, failing_chain):
    failing_chain(ValueError("some internal detail the researcher should not see"))

    response = _ask(client)
    error = response.json()["error"]

    assert response.status_code == 500
    assert error["code"] == "internal_error"
    assert "some internal detail" not in response.text


def test_error_responses_never_echo_the_api_key(client, failing_chain):
    failing_chain(
        AuthenticationError(
            "invalid x-api-key", response=_anthropic_response(401), body=None
        )
    )

    response = _ask(client)

    assert API_KEY not in response.text
