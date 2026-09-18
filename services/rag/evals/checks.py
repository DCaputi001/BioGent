"""The individual checks an eval case can be scored by.

Two tiers, deliberately separated:

  Programmatic - pure string and set logic. Free, instant, deterministic, and
  unit-tested in test/test_run_evals.py without an API key.

  LLM judge - a second Claude call reading what the chain produced. Costs
  money and is non-deterministic, so it is reserved for the questions string
  matching genuinely cannot answer: "is this claim supported by the context"
  and "was this retrieved chunk actually relevant".

Every check returns a CheckResult carrying a score as well as a verdict.
Binary pass/fail is enough to gate a change, but `PRODUCTION_PLAN.md` Phase 6
asks for context precision and faithfulness tracked *as a baseline*, and a
baseline needs a number that can move.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CheckResult:
    passed: bool
    # 0.0-1.0. Binary checks report 1.0 or 0.0; graded checks (context
    # precision) report the fraction, so a run that gets worse but not broken
    # is still visible.
    score: float
    detail: str


# --- Programmatic checks -----------------------------------------------------

REFUSAL_PHRASES = [
    "don't know",
    "do not know",
    "don't have",
    "do not have",
    "not in the context",
    "isn't in the context",
    "no information",
    "cannot answer",
    "can't answer",
]


def check_refusal(answer: str) -> tuple[bool, str]:
    """Cheap, no-LLM-call check: does the answer contain a refusal phrase?

    Returns the original (bool, detail) shape rather than a CheckResult, so
    the existing unit tests keep exercising it unchanged; run_case wraps it.
    """
    lowered = answer.lower()
    found = [p for p in REFUSAL_PHRASES if p in lowered]
    if found:
        return True, f"Refusal phrase found: {found[0]!r}"
    return False, "No refusal phrase found — answer may have hallucinated a response."


def check_answer_fragment(answer: str, expected_fragment: str) -> tuple[bool, str]:
    """Cheap, no-LLM-call check: does the answer contain a known fragment?"""
    if expected_fragment.lower() in answer.lower():
        return True, f"Found expected fragment: {expected_fragment!r}"
    return False, f"Expected fragment NOT found: {expected_fragment!r}"


def check_retrieval(sources: list[str], expected_sources: tuple[str, ...]) -> tuple[bool, str]:
    """Did retrieval surface the document(s) this question should be answered from?

    Retrieval failures and generation failures look identical from the answer
    alone -- a wrong answer could mean the chunks never arrived, or that the
    model ignored good chunks. This separates the two, which is what made the
    original hyphenation bug so slow to find.

    Matching is by filename substring, so a case survives a document being
    re-uploaded under a slightly longer name.
    """
    missing = [
        expected
        for expected in expected_sources
        if not any(expected.lower() in actual.lower() for actual in sources)
    ]
    if missing:
        return False, f"Expected source(s) not retrieved: {missing} (got {sources})"
    return True, f"All expected sources retrieved: {list(expected_sources)}"


# --- LLM judges --------------------------------------------------------------

FAITHFULNESS_PROMPT = """You are checking whether an AI assistant's answer is \
faithful to the context it was given — i.e. every claim in the answer should \
be supported by the context, with no fabricated details.

Context:
{context}

Question:
{question}

Answer to evaluate:
{answer}

Respond with exactly one word on the first line — PASS or FAIL — followed by \
a one-sentence reason on the second line. FAIL only if the answer makes a \
claim that is NOT supported by the context. An honest "I don't know" when the \
context lacks the answer is always a PASS.
"""

RELEVANCE_PROMPT = """You are judging whether a retrieved passage is relevant \
to a question, as part of measuring a search system's precision.

Question:
{question}

Passage:
{passage}

Answer with exactly one word: RELEVANT if the passage contains information \
that helps answer the question, or IRRELEVANT if it does not. Judge only this \
passage, not whether the question could be answered from elsewhere.
"""


def message_text(reply) -> str:
    """The plain text of a chat model reply, whatever shape it arrives in.

    ChatAnthropic returns AIMessage.content as a LIST of content blocks, not a
    string -- calling .strip() on it raises AttributeError, which is how the
    first real judge run failed while every stubbed test passed. Stubs returned
    strings; the live client did not. Normalizing here keeps that difference
    from reaching the parsing logic.
    """
    content = getattr(reply, "content", reply)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            block.get("text", "") if isinstance(block, dict) else str(block) for block in content
        ]
        return "".join(parts)
    return str(content)


def _verdict_and_reason(raw: str) -> tuple[str, str]:
    """Split a judge reply into its first-line verdict and its explanation."""
    lines = raw.strip().splitlines()
    verdict = lines[0].strip().upper() if lines else ""
    reason = lines[1].strip() if len(lines) > 1 else raw.strip()
    return verdict, reason


def judge_faithfulness(question: str, answer: str, context: str, llm) -> CheckResult:
    """LLM-as-judge: is every claim in the answer supported by the context?

    `llm` is injected rather than constructed here so tests can pass a stub
    and so the judge model stays a configuration decision (config.EVAL_JUDGE_MODEL).
    """
    raw = llm.invoke(FAITHFULNESS_PROMPT.format(context=context, question=question, answer=answer))
    verdict, reason = _verdict_and_reason(message_text(raw))

    passed = verdict.startswith("PASS")
    return CheckResult(passed=passed, score=1.0 if passed else 0.0, detail=reason)


def judge_context_precision(question: str, documents: list, llm) -> CheckResult:
    """Fraction of retrieved chunks that are actually relevant to the question.

    The metric named in the Phase 6 checkpoint. Low precision means the
    retriever is padding the context with noise, which costs tokens on every
    query and gives the model more opportunity to drift.

    Costs one judge call per retrieved chunk (RETRIEVER_K per case), which is
    why it is opt-in per case rather than applied to every case.
    """
    if not documents:
        return CheckResult(passed=False, score=0.0, detail="Nothing retrieved")

    verdicts = []
    for doc in documents:
        raw = llm.invoke(RELEVANCE_PROMPT.format(question=question, passage=doc.page_content))
        verdicts.append(message_text(raw).strip().upper().startswith("RELEVANT"))

    relevant = sum(verdicts)
    score = relevant / len(verdicts)
    # Half the retrieved chunks being noise is the point at which retrieval is
    # doing more harm than good, so that is where this reports a failure.
    return CheckResult(
        passed=score >= 0.5,
        score=score,
        detail=f"{relevant}/{len(verdicts)} retrieved chunks judged relevant",
    )
