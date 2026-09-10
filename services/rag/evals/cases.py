"""Eval test cases for the RAG service.

Hybrid approach per ARCHITECTURE.md — "Observability & evaluation": most
cases are a question plus a cheap faithfulness or refusal check (no
hand-written reference answer to maintain). A small number of cases tied to
real bugs already found get a hardcoded expected answer fragment, as a
permanent regression guard for that specific, previously-broken behavior.

NOTE: these cases assume specific documents are present in the vector store
(whatever's been ingested from data/). If you swap out your test documents,
update or remove the cases that depend on them — the "answer_fragment"
cases especially are tied to specific source material, not general RAG
correctness.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EvalCase:
    id: str
    question: str
    check: str  # "faithfulness" | "refusal" | "answer_fragment"
    expected_fragment: str | None = None  # required for "answer_fragment"
    notes: str = ""


CASES: list[EvalCase] = [
    # --- Faithfulness cases: no reference answer, just "is this grounded" ---
    EvalCase(
        id="ctenophore-general",
        question="What do you know about ctenophores?",
        check="faithfulness",
        notes="Verified manually during Step 1/2/3/4 testing — should stay "
        "grounded in the ingested paper's actual content (phylogenetic "
        "position, research gaps, cited authors), not general knowledge "
        "about ctenophores from Claude's training data.",
    ),
    # --- Refusal case: confirms the system says "I don't know" instead of
    #     reaching into general knowledge for something out of scope ---
    EvalCase(
        id="out-of-scope-capital",
        question="What is the capital of Mongolia?",
        check="refusal",
        notes="No plausible connection to any ingested research paper — "
        "should decline rather than answer from general knowledge.",
    ),
    # --- Regression case: tied to a specific, previously-found bug. See the
    #     small project's README Troubleshooting Log for the full story —
    #     this exact question originally failed due to a PDF line-wrap
    #     hyphenation issue in pypdf's text extraction, only fixed after
    #     several rounds of debugging (embedding model, chunk overlap, and
    #     finally identifying the "dynam-\nics" hyphenation break). ---
    EvalCase(
        id="single-agent-dynamic-models",
        question="What does single-agent dynamic models account for?",
        check="answer_fragment",
        expected_fragment="individual vehicle dynamics",
        notes="Regression guard for the hyphenation/chunking bug. Only "
        "meaningful if the F1 paper (Game_Theory_in_Formula_1...) is "
        "present in data/ — skip or remove if that document isn't loaded.",
    ),
]