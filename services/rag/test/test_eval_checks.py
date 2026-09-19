"""Unit tests for the eval checks and scoring, with no API key and no network.

The LLM judges ARE tested here, against a stub that returns canned verdicts.
What cannot be tested without spending money is whether Claude judges well;
what can be tested — and is what actually broke in practice — is whether a
judge's reply is parsed into the right verdict, and whether a judge failure
takes the whole run down with it.
"""

import pytest

from evals.cases import EvalCase
from evals.checks import (
    check_retrieval,
    judge_context_precision,
    judge_faithfulness,
    message_text,
)
from evals.run_evals import run_case, summarize


class StubMessage:
    """A reply shaped like a real AIMessage, whose content is a block list."""

    def __init__(self, content):
        self.content = content


class StubJudge:
    """Returns canned replies in order, recording the prompts it was given."""

    def __init__(self, replies: list[str]):
        self._replies = list(replies)
        self.prompts: list[str] = []

    def invoke(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._replies.pop(0) if self._replies else "IRRELEVANT"


class StubDoc:
    def __init__(self, text: str):
        self.page_content = text


# --- check_retrieval ---------------------------------------------------------


def test_retrieval_passes_when_expected_source_present():
    passed, _ = check_retrieval(
        ["PIEZO_provides_an_ancient_molecular_framework_for_.pdf", "other.pdf"],
        ("PIEZO_provides_an_ancient",),
    )
    assert passed is True


def test_retrieval_fails_when_expected_source_absent():
    passed, detail = check_retrieval(["unrelated.pdf"], ("PIEZO_provides_an_ancient",))

    assert passed is False
    # The detail has to name what was retrieved instead, or the failure gives
    # no clue whether retrieval is broken or the case is simply stale.
    assert "unrelated.pdf" in detail


def test_retrieval_matches_on_substring_so_renames_do_not_break_cases():
    passed, _ = check_retrieval(["2024_PIEZO_provides_an_ancient_v2.pdf"], ("PIEZO_provides_an_ancient",))
    assert passed is True


def test_retrieval_requires_every_expected_source():
    passed, _ = check_retrieval(["a_paper.pdf"], ("a_paper", "b_paper"))
    assert passed is False


# --- message_text ------------------------------------------------------------
# Regression guards for a bug that reached a real eval run: every stubbed test
# passed because stubs returned strings, while ChatAnthropic returns a list of
# content blocks and the parser called .strip() on it.


def test_message_text_accepts_a_plain_string():
    assert message_text("PASS\nreason") == "PASS\nreason"


def test_message_text_extracts_text_from_anthropic_block_lists():
    reply = StubMessage([{"type": "text", "text": "PASS\nEvery claim is supported."}])

    assert message_text(reply) == "PASS\nEvery claim is supported."


def test_message_text_joins_multiple_blocks():
    reply = StubMessage([{"type": "text", "text": "PASS\n"}, {"type": "text", "text": "Because."}])

    assert message_text(reply) == "PASS\nBecause."


def test_message_text_ignores_non_text_blocks_without_crashing():
    reply = StubMessage([{"type": "thinking", "thinking": "hmm"}, {"type": "text", "text": "FAIL"}])

    assert message_text(reply) == "FAIL"


def test_faithfulness_parses_a_real_shaped_block_list_reply():
    """The end-to-end version of the bug: block-list content must still score."""
    judge = StubJudge([StubMessage([{"type": "text", "text": "PASS\nGrounded."}])])

    result = judge_faithfulness("q", "a", "ctx", judge)

    assert result.passed is True
    assert result.detail == "Grounded."


def test_context_precision_parses_block_list_replies():
    judge = StubJudge(
        [
            StubMessage([{"type": "text", "text": "RELEVANT"}]),
            StubMessage([{"type": "text", "text": "IRRELEVANT"}]),
        ]
    )

    result = judge_context_precision("q", [StubDoc("a"), StubDoc("b")], judge)

    assert result.score == 0.5


# --- judge_faithfulness ------------------------------------------------------


def test_faithfulness_parses_pass_verdict():
    result = judge_faithfulness("q", "a", "ctx", StubJudge(["PASS\nEvery claim appears in context."]))

    assert result.passed is True
    assert result.score == 1.0
    assert result.detail == "Every claim appears in context."


def test_faithfulness_parses_fail_verdict():
    result = judge_faithfulness("q", "a", "ctx", StubJudge(["FAIL\nThe date is not in the context."]))

    assert result.passed is False
    assert result.score == 0.0


def test_faithfulness_survives_a_reply_with_no_reason_line():
    result = judge_faithfulness("q", "a", "ctx", StubJudge(["PASS"]))

    assert result.passed is True
    assert result.detail  # falls back to the raw reply rather than crashing


def test_faithfulness_prompt_includes_all_three_inputs():
    judge = StubJudge(["PASS\nfine"])

    judge_faithfulness("Why do comb plates beat?", "Because of cilia.", "CONTEXT_MARKER", judge)

    prompt = judge.prompts[0]
    assert "Why do comb plates beat?" in prompt
    assert "Because of cilia." in prompt
    assert "CONTEXT_MARKER" in prompt


# --- judge_context_precision -------------------------------------------------


def test_context_precision_scores_the_relevant_fraction():
    judge = StubJudge(["RELEVANT", "IRRELEVANT", "RELEVANT", "IRRELEVANT"])
    docs = [StubDoc("one"), StubDoc("two"), StubDoc("three"), StubDoc("four")]

    result = judge_context_precision("q", docs, judge)

    assert result.score == 0.5
    assert "2/4" in result.detail


def test_context_precision_fails_below_half_relevant():
    judge = StubJudge(["RELEVANT", "IRRELEVANT", "IRRELEVANT", "IRRELEVANT"])
    docs = [StubDoc(str(i)) for i in range(4)]

    result = judge_context_precision("q", docs, judge)

    assert result.passed is False
    assert result.score == 0.25


def test_context_precision_judges_each_chunk_separately():
    judge = StubJudge(["RELEVANT", "RELEVANT"])

    judge_context_precision("q", [StubDoc("first chunk"), StubDoc("second chunk")], judge)

    assert len(judge.prompts) == 2
    assert "first chunk" in judge.prompts[0]
    assert "second chunk" in judge.prompts[1]


def test_context_precision_handles_retrieving_nothing():
    """An empty retrieval is a failure, not a division by zero."""
    result = judge_context_precision("q", [], StubJudge([]))

    assert result.passed is False
    assert result.score == 0.0


# --- run_case error isolation ------------------------------------------------


class ExplodingJudge:
    def invoke(self, prompt: str):
        raise RuntimeError("judge API is down")


def test_a_judge_failure_becomes_a_failed_case_not_a_crashed_run(monkeypatch):
    """One rate-limited judge call should not discard every result before it."""
    monkeypatch.setattr(
        "evals.run_evals.ask_with_context",
        lambda q: {"answer": "a", "context": "c", "sources": [], "documents": []},
    )
    case = EvalCase(id="x", question="q", check="faithfulness", uses_judge=True)

    result = run_case(case, ExplodingJudge())

    assert result["passed"] is False
    assert "judge API is down" in result["detail"]


def test_an_unreachable_chain_becomes_a_failed_case(monkeypatch):
    def boom(_question):
        raise ConnectionError("database unreachable")

    monkeypatch.setattr("evals.run_evals.ask_with_context", boom)
    case = EvalCase(id="x", question="q", check="refusal")

    result = run_case(case, None)

    assert result["passed"] is False
    assert "database unreachable" in result["detail"]


def test_unknown_check_type_is_reported_rather_than_silently_passing(monkeypatch):
    monkeypatch.setattr(
        "evals.run_evals.ask_with_context",
        lambda q: {"answer": "a", "context": "c", "sources": [], "documents": []},
    )
    case = EvalCase(id="x", question="q", check="typo_check")

    result = run_case(case, None)

    assert result["passed"] is False
    assert "Unknown check type" in result["detail"]


# --- summarize ---------------------------------------------------------------


def test_summarize_reports_a_mean_per_check_type():
    results = [
        {"check": "retrieval", "score": 1.0, "passed": True},
        {"check": "retrieval", "score": 0.0, "passed": False},
        {"check": "context_precision", "score": 0.75, "passed": True},
    ]

    metrics = summarize(results)

    assert metrics["retrieval_mean_score"] == 0.5
    assert metrics["context_precision_mean_score"] == 0.75
    assert metrics["passed"] == 2
    assert metrics["total"] == 3


@pytest.mark.parametrize("check", ["faithfulness", "refusal", "answer_fragment"])
def test_summarize_keeps_check_types_separate(check):
    """Retrieval regressing and the model drifting must not average together."""
    metrics = summarize([{"check": check, "score": 1.0, "passed": True}])

    assert f"{check}_mean_score" in metrics
