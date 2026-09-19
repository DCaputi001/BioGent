"""Runs the eval cases in cases.py against the real RAG chain and reports results.

Needs a real ANTHROPIC_API_KEY and costs real API calls — deliberately
separate from the unit test suite, which needs no key and runs on every CI
push. Run this manually when you want a real before/after signal on a
chunking, retrieval, or prompt change.

Usage:
    uv run python -m evals.run_evals                  # everything
    uv run python -m evals.run_evals --no-judge       # free checks only
    uv run python -m evals.run_evals --case yoda1-inhibits-mleipiezo

Writes a timestamped JSON report to evals/reports/ and prints a summary.
Reports are committed: a report sitting in the same PR as a chunking change
is the evidence that the change helped, which is the whole argument for an
in-repo harness in ARCHITECTURE.md.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make `app` importable when running this from services/rag/ as
# `python -m evals.run_evals` (evals/ is a sibling of app/, not inside it).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config
from app.query import ask_with_context
from evals.cases import CASES, EvalCase
from evals.checks import (
    CheckResult,
    check_answer_fragment,
    check_refusal,
    check_retrieval,
    judge_context_precision,
    judge_faithfulness,
)

REPORTS_DIR = Path(__file__).resolve().parent / "reports"


def _use_eval_tracing_project() -> None:
    """Route this run's traces to their own LangSmith project.

    Every case goes through ask_with_context(), the same chain real queries
    use, so LangChain would trace eval runs into config.LANGSMITH_PROJECT
    right alongside real usage if left alone. Setting os.environ here, before
    any chain is invoked, is what keeps synthetic eval traffic out of the
    dashboard you'd actually watch for production traces -- LangChain reads
    this per-call, not once at import time, so it is not too late even though
    app.query was already imported above.
    """
    if config.LANGSMITH_TRACING:
        os.environ["LANGSMITH_PROJECT"] = f"{config.LANGSMITH_PROJECT}-evals"


def build_judge():
    """The judge model, built once per run.

    Imported lazily so --no-judge runs, and the unit tests, never construct a
    client or require a key.
    """
    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(model=config.EVAL_JUDGE_MODEL)


def run_case(case: EvalCase, judge=None) -> dict:
    """Run one case and score it. Never raises: a failure is a result.

    Retrieval uses the default corpus. See KNOWN_ISSUES.md — Phase 8's
    per-user filtering will hide these documents from an eval run, and the
    fix depends on how that isolation is implemented.
    """
    try:
        result = ask_with_context(case.question)
    except Exception as exc:  # noqa: BLE001 - see below
        # Deliberately broad: an eval run is a measurement, and one unreachable
        # database or rate-limited call should be recorded as a failed case
        # rather than discarding the results of every case that already ran.
        return {
            "id": case.id,
            "question": case.question,
            "check": case.check,
            "passed": False,
            "score": 0.0,
            "detail": f"Chain error: {type(exc).__name__}: {exc}",
            "answer": "",
            "sources": [],
        }

    answer, context = result["answer"], result["context"]
    sources, documents = result["sources"], result["documents"]

    try:
        if case.check == "refusal":
            passed, detail = check_refusal(answer)
            checked = CheckResult(passed, 1.0 if passed else 0.0, detail)
        elif case.check == "answer_fragment":
            passed, detail = check_answer_fragment(answer, case.expected_fragment)
            checked = CheckResult(passed, 1.0 if passed else 0.0, detail)
        elif case.check == "retrieval":
            passed, detail = check_retrieval(sources, case.expected_sources)
            checked = CheckResult(passed, 1.0 if passed else 0.0, detail)
        elif case.check == "faithfulness":
            checked = judge_faithfulness(case.question, answer, context, judge)
        elif case.check == "context_precision":
            checked = judge_context_precision(case.question, documents, judge)
        else:
            checked = CheckResult(False, 0.0, f"Unknown check type: {case.check!r}")
    except Exception as exc:  # noqa: BLE001 - same reason as above
        checked = CheckResult(False, 0.0, f"Check error: {type(exc).__name__}: {exc}")

    return {
        "id": case.id,
        "question": case.question,
        "check": case.check,
        "passed": checked.passed,
        "score": round(checked.score, 3),
        "detail": checked.detail,
        "answer": answer,
        "sources": sources,
    }


def summarize(results: list[dict]) -> dict:
    """Per-check-type averages, so a baseline has numbers that can move.

    A single pass/fail total hides which layer regressed: retrieval getting
    worse and the model drifting both read as "fewer passes".
    """
    by_check: dict[str, list[float]] = {}
    for r in results:
        by_check.setdefault(r["check"], []).append(r["score"])

    metrics = {
        f"{check}_mean_score": round(sum(scores) / len(scores), 3)
        for check, scores in sorted(by_check.items())
    }
    metrics["passed"] = sum(1 for r in results if r["passed"])
    metrics["total"] = len(results)
    return metrics


def _git_commit() -> str:
    """The commit a report was produced at, so a number ties to code.

    Without it a committed report is just a number with no way to reproduce it.
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def main() -> int:
    _use_eval_tracing_project()

    parser = argparse.ArgumentParser(description="Run RAG evaluation cases.")
    parser.add_argument("--case", help="Run only the case with this id.")
    parser.add_argument(
        "--no-judge",
        action="store_true",
        help="Skip cases that call the judge model. Free, and needs no key beyond the chain itself.",
    )
    args = parser.parse_args()

    selected = [c for c in CASES if args.case is None or c.id == args.case]
    if args.case and not selected:
        print(f"No case with id {args.case!r}. Known ids: {[c.id for c in CASES]}")
        return 2
    if args.no_judge:
        selected = [c for c in selected if not c.uses_judge]

    judge = build_judge() if any(c.uses_judge for c in selected) else None
    results = [run_case(case, judge) for case in selected]
    metrics = summarize(results)

    print("\n--- Eval Results ---")
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"[{status}] {r['id']} ({r['check']}, score {r['score']}) — {r['detail']}")

    print(f"\n{metrics['passed']}/{metrics['total']} passed")
    for name, value in metrics.items():
        if name.endswith("_mean_score"):
            print(f"  {name}: {value}")
    print()

    REPORTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = REPORTS_DIR / f"report_{timestamp}.json"
    report_path.write_text(
        json.dumps(
            {
                "timestamp": timestamp,
                # Everything needed to interpret the scores later: the same
                # cases against a different embedding model or judge are not
                # comparable, and a report that does not say so is misleading.
                "commit": _git_commit(),
                "answering_model": config.ANTHROPIC_MODEL,
                "judge_model": config.EVAL_JUDGE_MODEL,
                "embedding_model": config.EMBEDDING_MODEL,
                "retriever_k": config.RETRIEVER_K,
                "collection": config.COLLECTION_NAME,
                "metrics": metrics,
                "results": results,
            },
            indent=2,
        )
    )
    print(f"Report written to {report_path.relative_to(Path.cwd())}")

    return 0 if metrics["passed"] == metrics["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
