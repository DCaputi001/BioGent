"""Runs the eval cases in cases.py against the real RAG chain and reports results.

Needs a real ANTHROPIC_API_KEY and costs real API calls — this is
deliberately separate from the automated test suite (services/rag has none
yet, but per ARCHITECTURE.md, tests should require no API key and be safe
on every CI push). Run this manually, locally, when you want a real
before/after signal on a chunking/retrieval/prompt change — e.g. after
tuning chunk_size or swapping the embedding model.

Usage:
    uv run python -m evals.run_evals

Writes a timestamped JSON report to evals/reports/ and prints a summary.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make `app` importable when running this from services/rag/ as
# `python -m evals.run_evals` (evals/ is a sibling of app/, not inside it).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.query import ask_with_context
from evals.cases import CASES, EvalCase

REPORTS_DIR = Path(__file__).resolve().parent / "reports"

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
    """Cheap, no-LLM-call check: does the answer contain a refusal phrase?"""
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


def check_faithfulness(question: str, answer: str, context: str) -> tuple[bool, str]:
    """LLM-as-judge: does the answer's content actually appear supported by
    the retrieved context, rather than drifting into unsupported claims?

    Uses a separate, plain Claude call (not the RAG chain) purely as a
    judge — no retrieval involved in this step, just reading the three
    pieces already produced and giving a verdict.
    """
    from langchain_anthropic import ChatAnthropic

    judge_prompt = f"""You are checking whether an AI assistant's answer is \
faithful to the context it was given — i.e. every claim in the answer \
should be supported by the context, with no fabricated details.

Context:
{context}

Question:
{question}

Answer to evaluate:
{answer}

Respond with exactly one word on the first line — PASS or FAIL — followed \
by a one-sentence reason on the second line. FAIL only if the answer makes \
a claim that is NOT supported by the context. An honest "I don't know" \
when the context lacks the answer is always a PASS.
"""
    llm = ChatAnthropic(model="claude-sonnet-5")
    result = llm.invoke(judge_prompt).content.strip()

    lines = result.splitlines()
    verdict = lines[0].strip().upper() if lines else ""
    reason = lines[1].strip() if len(lines) > 1 else result

    return verdict.startswith("PASS"), reason


def run_case(case: EvalCase) -> dict:
    result = ask_with_context(case.question)
    answer, context = result["answer"], result["context"]

    if case.check == "refusal":
        passed, detail = check_refusal(answer)
    elif case.check == "answer_fragment":
        passed, detail = check_answer_fragment(answer, case.expected_fragment)
    elif case.check == "faithfulness":
        passed, detail = check_faithfulness(case.question, answer, context)
    else:
        passed, detail = False, f"Unknown check type: {case.check!r}"

    return {
        "id": case.id,
        "question": case.question,
        "check": case.check,
        "passed": passed,
        "detail": detail,
        "answer": answer,
    }


def main() -> int:
    results = [run_case(case) for case in CASES]

    print("\n--- Eval Results ---")
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"[{status}] {r['id']} ({r['check']}) — {r['detail']}")

    passed_count = sum(1 for r in results if r["passed"])
    total = len(results)
    print(f"\n{passed_count}/{total} passed\n")

    REPORTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = REPORTS_DIR / f"report_{timestamp}.json"
    report_path.write_text(
        json.dumps(
            {"timestamp": timestamp, "passed": passed_count, "total": total, "results": results},
            indent=2,
        )
    )
    print(f"Report written to {report_path.relative_to(Path.cwd())}")

    return 0 if passed_count == total else 1


if __name__ == "__main__":
    sys.exit(main())