"""Eval test cases for the RAG service.

Hybrid approach per ARCHITECTURE.md — "Observability & evaluation": most
cases are a question plus a cheap faithfulness or refusal check (no
hand-written reference answer to maintain). A small number get a hardcoded
expected fragment, as a permanent regression guard for specific behavior.

NOTE: these cases assume specific documents are present in the vector store.
The corpus they are written against is two ctenophore papers:

  PIEZO_provides_an_ancient_molecular_framework_for_.pdf
  Molecular_and_electrophysiological_properties_unde.pdf

If you swap out the documents, the "answer_fragment" and "retrieval" cases
must be rewritten — they are tied to this source material, not to general
RAG correctness.
"""

from dataclasses import dataclass, field

CHECK_TYPES = ("faithfulness", "refusal", "answer_fragment", "retrieval", "context_precision")


@dataclass(frozen=True)
class EvalCase:
    id: str
    question: str
    check: str  # one of CHECK_TYPES
    expected_fragment: str | None = None  # required for "answer_fragment"
    expected_sources: tuple[str, ...] = ()  # required for "retrieval"
    notes: str = ""
    # True for checks that spend money on a judge call, so a run can be
    # restricted to the free tier with --no-judge.
    uses_judge: bool = field(default=False)


CASES: list[EvalCase] = [
    # --- Faithfulness: no reference answer, just "is this grounded" ---
    EvalCase(
        id="ctenophore-general",
        question="What do you know about ctenophores?",
        check="faithfulness",
        uses_judge=True,
        notes="Verified manually during Step 1/2/3/4 testing — should stay "
        "grounded in the ingested papers' actual content (phylogenetic "
        "position, comb plates, research gaps), not general knowledge "
        "about ctenophores from Claude's training data.",
    ),
    # --- Refusal: confirms the system declines rather than reaching into
    #     general knowledge for something out of scope ---
    EvalCase(
        id="out-of-scope-capital",
        question="What is the capital of Mongolia?",
        check="refusal",
        notes="No plausible connection to any ingested paper — should decline "
        "rather than answer from general knowledge.",
    ),
    EvalCase(
        id="out-of-scope-plausible",
        question="What is the resting membrane potential of a human cardiac myocyte?",
        check="refusal",
        notes="Harder refusal than the capital question: electrophysiology is "
        "the right FIELD, and the model certainly knows the answer, but these "
        "papers are about ctenophores. Catches a model that pattern-matches on "
        "topic familiarity instead of on what the context actually contains.",
    ),
    # --- Regression: grounding vs. parametric knowledge ---
    #     The strongest case in this file. In mammals Yoda1 is a well-known
    #     PIEZO1 *agonist*, which is what training data will say. The PIEZO
    #     paper reports it acting as an *inhibitor* of the ctenophore channel
    #     MleiPIEZO. An ungrounded answer confidently says the opposite of the
    #     source, and says it fluently.
    EvalCase(
        id="yoda1-inhibits-mleipiezo",
        question="What effect does Yoda1 have on MleiPIEZO?",
        check="answer_fragment",
        expected_fragment="inhibit",
        notes="Grounding guard: general knowledge says Yoda1 ACTIVATES PIEZO1. "
        "The ingested paper reports the opposite for MleiPIEZO. Failing this "
        "means the model answered from training data rather than the context.",
    ),
    # --- Regression: specific numeric recall ---
    EvalCase(
        id="balancer-oscillation-frequency",
        question="At what frequency do balancer cilia spontaneously oscillate?",
        check="answer_fragment",
        expected_fragment="15",
        notes="Numbers are where retrieval failures show up most visibly: a "
        "model with the wrong chunk still produces a confident number. "
        "Replaces the Formula 1 hyphenation regression case, whose source "
        "document is no longer in the corpus (removed with the user's "
        "explicit sign-off — see AGENTS.md on not editing eval cases quietly).",
    ),
    EvalCase(
        id="muscle-activity-modes",
        question="What two modes characterize the spontaneous activity of Mnemiopsis muscle cells?",
        check="answer_fragment",
        expected_fragment="bursting",
        notes="Drawn from the electrophysiology paper, so it fails if only the "
        "PIEZO paper is retrievable — a cheap check that both documents are "
        "actually reachable.",
    ),
    # --- Retrieval: did the right document come back at all ---
    EvalCase(
        id="retrieval-piezo-paper",
        question="How does MleiPIEZO contribute to gravity detection?",
        check="retrieval",
        expected_sources=("PIEZO_provides_an_ancient",),
        notes="Separates a retrieval failure from a generation failure. If "
        "this passes while the Yoda1 case fails, the chunks arrived and the "
        "model ignored them; if it fails too, the problem is upstream.",
    ),
    EvalCase(
        id="retrieval-electrophysiology-paper",
        question="How was calcium signaling measured in Mnemiopsis muscle cells?",
        check="retrieval",
        expected_sources=("Molecular_and_electrophysiological",),
        notes="Same check against the second document, so one paper dominating "
        "retrieval for every question is visible rather than silent.",
    ),
    # --- Context precision: how much of what we retrieved was worth retrieving ---
    EvalCase(
        id="precision-piezo-function",
        question="What role does PIEZO play in mechanosensation?",
        check="context_precision",
        uses_judge=True,
        notes="The Phase 6 baseline metric. Judges each retrieved chunk "
        "separately, so it costs RETRIEVER_K judge calls. A falling score "
        "means the context window is filling with noise, which costs tokens "
        "on every real query and gives the model room to drift.",
    ),
]
