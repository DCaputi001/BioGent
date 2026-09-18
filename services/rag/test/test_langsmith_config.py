"""Unit tests for the LangSmith tracing configuration added in Phase 6.

Covers the two things that are actually testable without a real LangSmith
account: the misconfiguration warning, and eval runs getting routed to their
own project rather than polluting production traces. Whether LangChain itself
picks these env vars up correctly is verified manually against a real
account -- see the Phase 6 plan's verification steps.
"""

import logging

from app.config import _warn_if_tracing_misconfigured
from evals.run_evals import _use_eval_tracing_project


def test_warns_when_tracing_enabled_without_a_key(caplog):
    with caplog.at_level(logging.WARNING):
        _warn_if_tracing_misconfigured(tracing=True, has_key=False)

    assert "LANGSMITH_API_KEY" in caplog.text


def test_no_warning_when_tracing_enabled_with_a_key(caplog):
    with caplog.at_level(logging.WARNING):
        _warn_if_tracing_misconfigured(tracing=True, has_key=True)

    assert caplog.text == ""


def test_no_warning_when_tracing_is_off(caplog):
    """A missing key only matters if tracing is actually on."""
    with caplog.at_level(logging.WARNING):
        _warn_if_tracing_misconfigured(tracing=False, has_key=False)

    assert caplog.text == ""


def test_eval_runs_get_their_own_langsmith_project(monkeypatch):
    """Regression guard: without this, every eval run traces into the same
    project as real researcher queries, making the production dashboard
    unreadable the first time someone runs the eval suite.
    """
    monkeypatch.setattr("evals.run_evals.config.LANGSMITH_TRACING", True)
    monkeypatch.setattr("evals.run_evals.config.LANGSMITH_PROJECT", "biogent-rag")
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)

    _use_eval_tracing_project()

    import os

    assert os.environ["LANGSMITH_PROJECT"] == "biogent-rag-evals"


def test_eval_project_override_is_skipped_when_tracing_is_off(monkeypatch):
    """No reason to touch the environment when tracing is disabled entirely."""
    monkeypatch.setattr("evals.run_evals.config.LANGSMITH_TRACING", False)
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)

    _use_eval_tracing_project()

    import os

    assert "LANGSMITH_PROJECT" not in os.environ
