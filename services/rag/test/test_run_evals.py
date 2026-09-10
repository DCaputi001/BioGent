"""Unit tests for evals.run_evals's non-LLM check functions.

check_faithfulness() is NOT tested here — it makes a real Claude API call
and belongs to the evals tier (needs a key, costs money, run manually), not
this fast/free unit test tier. check_refusal() and check_answer_fragment()
are pure string logic and belong here instead.
"""

from evals.run_evals import check_answer_fragment, check_refusal


def test_check_refusal_detects_dont_know():
    passed, detail = check_refusal("I don't know based on the given context.")
    assert passed is True


def test_check_refusal_detects_no_information():
    passed, detail = check_refusal("There is no information about that topic here.")
    assert passed is True


def test_check_refusal_fails_on_confident_answer():
    passed, detail = check_refusal("The capital of Mongolia is Ulaanbaatar.")
    assert passed is False


def test_check_refusal_case_insensitive():
    passed, detail = check_refusal("I DON'T KNOW the answer to that.")
    assert passed is True


def test_check_answer_fragment_found():
    passed, detail = check_answer_fragment(
        "This accounts for individual vehicle dynamics, including the PU model.",
        expected_fragment="individual vehicle dynamics",
    )
    assert passed is True


def test_check_answer_fragment_not_found():
    passed, detail = check_answer_fragment(
        "This is about something completely unrelated.",
        expected_fragment="individual vehicle dynamics",
    )
    assert passed is False


def test_check_answer_fragment_case_insensitive():
    passed, detail = check_answer_fragment(
        "INDIVIDUAL VEHICLE DYNAMICS is the key concept here.",
        expected_fragment="individual vehicle dynamics",
    )
    assert passed is True