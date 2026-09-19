"""Unit tests for app.api — HTTP contract only, against a stubbed chain.

No API key, no database, no model download: query.ask_with_context and
query.get_retriever are replaced, so these stay in the fast CI tier alongside
the other tests. Whether the chain produces a good answer is the eval
harness's job; this file checks status codes, the error shape, and that the
caller's key is what reaches the chain and never comes back out.

Sign-in is stubbed with a FastAPI dependency override rather than a real
token: whether a Cognito token is genuine is test_auth.py's subject, and
minting signed tokens here would test that twice while making every unrelated
case slower. One case below deliberately skips the override, to confirm the
endpoint is closed by default rather than open when nothing stubs it.
"""

import httpx
import pytest
from anthropic import AuthenticationError, RateLimitError
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app import api, query
from app.auth import require_user

API_KEY = "sk-ant-test-key"
USER_ID = "cognito-sub-of-the-signed-in-researcher"
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

    def fake_ask_with_context(question, retriever, anthropic_api_key=None):
        calls.append(
            {
                "question": question,
                "anthropic_api_key": anthropic_api_key,
                # Carries the identity: get_retriever is stubbed below to encode
                # whichever user it was asked for, which is how these tests see
                # that retrieval was scoped to the signed-in researcher.
                "retriever": retriever,
            }
        )
        return {
            "answer": "PIEZO channels transduce mechanical force.",
            "context": "...retrieved chunks...",
            "sources": [SOURCE],
        }

    monkeypatch.setattr(query, "ask_with_context", fake_ask_with_context)
    # Guards against a real embedding model load if the cached retriever is
    # ever built eagerly rather than inside the request.
    monkeypatch.setattr(query, "get_retriever", _fake_get_retriever)
    return calls


def _fake_get_retriever(user_id: str) -> str:
    """Stands in for the real retriever, naming the user it was scoped to."""
    return f"retriever-for:{user_id}"


@pytest.fixture
def failing_chain(monkeypatch):
    """Make the chain raise a given exception, as the real one would upstream."""

    def _fail_with(exc: Exception):
        def fake_ask_with_context(question, retriever, anthropic_api_key=None):
            raise exc

        monkeypatch.setattr(query, "ask_with_context", fake_ask_with_context)
        monkeypatch.setattr(query, "get_retriever", _fake_get_retriever)

    return _fail_with


@pytest.fixture
def client() -> TestClient:
    """A client standing in for a signed-in researcher."""
    api.app.dependency_overrides[require_user] = lambda: USER_ID
    yield TestClient(api.app)
    # Overrides live on the app object, which is shared across tests, so
    # leaving one in place would silently sign in every later test too.
    api.app.dependency_overrides.clear()


@pytest.fixture
def signed_out_client() -> TestClient:
    """A client with no session at all, and nothing stubbing one in."""
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
    # the BYO-key flow — and retrieval was scoped to the signed-in researcher.
    assert recorded_calls == [
        {
            "question": QUESTION,
            "anthropic_api_key": API_KEY,
            "retriever": f"retriever-for:{USER_ID}",
        }
    ]


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


def test_signed_out_request_is_rejected(signed_out_client, recorded_calls):
    """No session means no answer, even with a perfectly good Anthropic key.

    Nothing overrides the auth dependency here, so this also confirms the
    endpoint is closed by default: if require_user were ever dropped from the
    route, this is the test that notices.
    """
    response = _ask(signed_out_client)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_auth"
    assert recorded_calls == []


def test_a_malformed_authorization_header_is_rejected(signed_out_client, recorded_calls):
    response = signed_out_client.post(
        f"{api.API_PREFIX}/ask",
        json={"question": QUESTION},
        headers={api.API_KEY_HEADER: API_KEY, "Authorization": "Basic not-a-bearer-token"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"
    assert recorded_calls == []


def test_the_request_body_cannot_choose_whose_documents_to_search(client, recorded_calls):
    """Identity comes from the verified token, never from the request.

    A body field naming another user must not reach retrieval — that would be
    the whole isolation boundary undone by one unvalidated parameter.
    """
    response = client.post(
        f"{api.API_PREFIX}/ask",
        json={"question": QUESTION, "user_id": "someone-elses-cognito-sub"},
        headers={api.API_KEY_HEADER: API_KEY},
    )

    assert response.status_code == 200
    assert recorded_calls[0]["retriever"] == f"retriever-for:{USER_ID}"


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
