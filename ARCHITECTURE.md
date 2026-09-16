# Architecture Roadmap — Production Vision
 
This is a living design doc, not a build plan for right now. It captures decisions made while comparing this project's long-term goals against [caseywdunn/corpus](https://github.com/caseywdunn/corpus), a much larger RAG system built for taxonomic/biodiversity research. Kept here so early decisions in the current small-scale project don't accidentally box out this path later.
 
**Current status:** the small-scale local CLI RAG app (separate learning project) is on pause, feature-complete through Phase 6. This document has shifted from "parked ideas" to active design work for the production, multi-researcher, web-based version described below.
 
---
 
## The goal, stated plainly
 
A web-based version of this RAG pipeline, tuned for scientific/taxonomic literature (using Darwin Core taxonomy, like corpus does), usable by researchers who are **not** computer-savvy — no local setup, no MCP client installation, no command line.
 
---
 
## Key decision: how the LLM gets paid for
 
Three options were considered:
 
1. **We pay for every query** (our own API key, server-side) — simplest for the researcher, but cost scales with usage and needs rate-limiting/abuse protection as the app grows.
2. **MCP-only, like corpus** — researcher brings their own MCP client (Claude Desktop/Code) and their own Claude subscription. Zero cost to us, but real setup friction for a non-technical audience — installing a client, editing a JSON config, understanding what MCP is.
3. **BYO API key in our web app (chosen)** — researcher pastes their own Anthropic API key into our frontend. No app install, no MCP client, no config files — just a webpage. Meaningfully easier than option 2, and removes our own cost/rate-limiting burden entirely.
**Decision: Option 3.** It's the best fit for the stated audience — far less friction than corpus's MCP-only approach, while keeping usage costs on the researcher's own account rather than ours.
 
### What Option 3 requires to do right
- **A clear onboarding page** walking a first-time user through getting an API key (console.anthropic.com → API Keys → Create Key → copy). This page is the single biggest lever for actually hitting the "easy for non-technical researchers" goal.
- **Safe key handling.** Simplest safe pattern for a BYO-only design: keep the key in the researcher's browser (session/local storage), send it with each request, **never persist it server-side**. Avoids needing encryption-at-rest or a credential store entirely.
- **Graceful failure states** — invalid/expired/out-of-credit keys should surface a plain, actionable message ("Your API key looks invalid — check console.anthropic.com"), not a raw API error.
### What this removes from the design (compared to earlier drafts)
Going BYO-only removes the need for:
- Server-side API cost monitoring or usage caps
- Free-tier abuse protection
- Any billing/metering system on our end
---
 
## Data layer: one unified database instead of many
 
**corpus's approach:** three separate SQLite files (taxonomy, bibliography, taxon-mentions) plus a separate LanceDB vector store. Reasonable for a single researcher running everything locally — not reasonable for concurrent multi-user web access (SQLite handles concurrent writes poorly).
 
**Chosen approach: PostgreSQL + `pgvector` extension, on Amazon RDS.**
 
Why this is a real improvement, not just a swap:
- Embeddings *and* relational data (taxonomy, bibliography, papers, users) live in **one database**. A single query can do "find similar chunks AND filter by taxonomy AND join bibliography" instead of querying multiple separate stores and stitching results together in application code.
- RDS is fully managed: automated backups, Multi-AZ failover, proper concurrent connection handling — directly serves the "researchers can use it without us stressing about infrastructure" goal.
- Fits comfortably within available AWS credits, scales up smoothly as usage grows.
---
 
## Full component comparison: corpus vs. this project's production target
 
| Concern | corpus's approach | Planned approach here | Why |
|---|---|---|---|
| PDF storage | Local `data/` folder | **S3 bucket** | Durable, scales indefinitely, every pipeline stage can read/write independently |
| Vector + relational data | LanceDB + 3 separate SQLite files | **PostgreSQL + pgvector (RDS)** | Multi-user concurrent access; one query surface instead of several |
| Pipeline execution | Local script (`corpus run`) | **Background job queue** (SQS + workers on ECS Fargate) | OCR/embedding are slow — shouldn't block a researcher's browser tab |
| Access interface | MCP only | **Web app (primary) + optional MCP server (secondary, for power users)** | Closes the non-technical-user gap; MCP still valuable for advanced users with their own Claude clients |
| Auth | None (single-tenant, local) | **Amazon Cognito** | Real user accounts, sessions, without building auth from scratch |
| GPU (embeddings) | Assumes local GPU hardware | **On-demand GPU compute** (spin up only during ingestion batches) or a hosted embeddings API | Avoid maintaining always-on GPU infrastructure |
| LLM cost | Researcher's own Claude subscription via MCP client | **Researcher's own Anthropic API key**, entered in our web UI | Same cost model as corpus, much lower setup friction |
| Taxonomy | Darwin Core (WoRMS/GBIF/ITIS), synonymy resolution | **Keep as-is** | Correct approach for taxonomic literature; no reason to change |
| Bibliography | Grobid extraction + reconciliation into a citation graph | **Keep as-is** | Same reasoning — deduplicating citations is a real, solved problem worth reusing |
| Figures | Vision-model extraction + caption-to-taxonomy linking | **Keep as-is, lower priority** | Valuable, but not core to the MVP query flow |
 
---
 
## Observability & evaluation
 
Two distinct layers, solving different problems — worth building both in from the start rather than bolting on later.
 
### LangSmith — hosted tracing + ongoing evaluation
 
LangSmith (LangChain's platform, separate from Anthropic) provides two things directly relevant at production scale:
 
- **Tracing** — every chain run (retrieval call, chunks returned, prompt sent, response) logged automatically. At multi-user scale, this is how we'd actually debug a specific researcher's bad answer without asking them to reproduce it.
- **Evaluation** — a permanent regression-test suite built from real test questions (many already generated during this project's own debugging sessions), scored automatically on:
  - **Context precision/relevance** — were the retrieved chunks actually relevant?
  - **Faithfulness** — does the answer match the retrieved context, or did the model drift/hallucinate?
**Where it fits:** part of the core pipeline from day one — set up tracing (a couple of environment variables, no code changes) as soon as the production chain exists, and grow the eval dataset alongside real usage and support tickets.
 
### In-repo eval harness — version-controlled, runs locally
 
A lightweight, code-owned evaluation harness, separate from LangSmith, modeled on a pattern seen in a real reference project's CI setup: automated **tests** (structural, no API key required, safe to run on every push) stay separate from **evals** (need a real API key, cost real money, run deliberately and locally, results committed as artifacts) — two different tools solving two different problems.
 
Why this matters alongside LangSmith, not instead of it:
- **Runs without needing LangSmith access** — useful for anyone (including an AI agent) working in the repo without your LangSmith account.
- **Version-controlled alongside the code that changes it** — when a PR tunes `chunk_size` or swaps the embedding model, the committed eval report *in that PR* is direct, reviewable evidence of whether it helped or hurt, sitting right in the diff instead of only in an external dashboard.
- **Reuses proven test cases directly** — the small project's F1 questions, MTB questions, and confirmed out-of-scope question become a permanent regression suite instead of living only in chat history.
**Not every eval case needs a hand-written "correct answer."** Evaluation has two separable ingredients — the input (a question) and the judgment method — and the judgment method doesn't always require a pre-written reference answer:
 
| Evaluator type | Needs a written reference answer? | What it checks |
|---|---|---|
| Exact/fuzzy match | Yes | Answer matches a reference string |
| LLM-as-judge | No (a loose rubric instead) | A second LLM call scores whether the answer is reasonable, grounded, on-topic |
| Faithfulness check | No | Do the answer's claims actually appear in the retrieved context? |
| Retrieval-only check | Needs a known relevant section/chunk ID, not a full answer | Did the retriever pull back the chunk that's actually about this topic? |
| Refusal check | No | For known out-of-scope questions, does the system correctly decline instead of hallucinating? |
 
**Chosen approach: hybrid, not all-or-nothing.** Most eval cases are just a question plus a faithfulness/refusal check — cheap to write, no answer-maintenance burden as source documents change. A small number of cases tied to real bugs already found (e.g. the small project's "single-agent dynamic models" retrieval failure) get a hardcoded expected chunk ID or answer fragment, as a permanent regression guard for that specific, previously-broken behavior.
 
Planned location: `services/rag/evals/` (`cases.py` for the test questions, `run_evals.py` to execute them against the real chain, `reports/` for committed output).
 
---
 
## Second service: data analyst agent (planned)
 
A separate agent, alongside the document-search RAG service, for researchers to hand a dataset to and get back hypotheses generated and statistically tested against it. Not built yet — captured here so the design direction is on record before work starts.
 
### Why this needs LangGraph, not a chain
The document-search RAG service is a fixed pipeline (retrieve → answer). This agent can't be fixed the same way, because the right next step depends on what was just found: profile the data → generate a hypothesis → decide if it's testable with the available columns → run the test → decide whether the result supports refining the hypothesis or reporting it. That decision-and-loop pattern is what LangGraph is for.
 
### Rough graph shape
```
[Profile the dataset] → [Generate hypotheses] → [Select statistical test]
                                                          ↓
                                              [Execute test via tool]
                                                          ↓
                                              [Interpret result]
                                                    ↙        ↘
                                    [Refine hypothesis]   [Report finding]
                                          ↑______________________|
```
- **Profile the dataset** — column types, ranges, missingness, summary stats. Grounds every later step in actual facts about the data.
- **Generate hypotheses** — LLM call, explicitly constrained to hypotheses the actual columns can support (real hallucination risk otherwise — proposing relationships between columns that don't exist).
- **Select statistical test** — match hypothesis type to test (t-test, chi-square, correlation, regression, etc.).
- **Execute test** — must be real code execution, not the LLM "computing" a p-value itself. Goes through a tool call into a sandbox.
- **Interpret** — LLM reads the actual numeric output and explains it in plain language.
- **Loop condition** — inconclusive or poorly-formed results go back for refinement rather than getting reported as a solid finding.
### Where MCP fits, specifically
Different role here than in the document-search service — MCP is the **execution layer**, not just a data-retrieval layer:
- **Code execution / sandbox tool** — runs Python (pandas, scipy, statsmodels) in isolation, returns real numeric results. Load-bearing: the LLM must never "do math in its head" and report a fabricated p-value.
- **Data access tool** — reads the researcher's uploaded dataset (CSV, Excel) into the sandboxed environment.
- **Visualization tool** — generates a chart from test results alongside the plain-language interpretation.
### Where deep-agents becomes relevant (unlike the RAG service)
The document-search agent didn't need deep-agents — a fixed retrieval task doesn't benefit from open-ended planning. This one does: deep-agents' built-in task planning ("write a to-do list, work through it") and sub-agent delegation map naturally onto "profile the data, generate several hypotheses, test each one, compile findings" — a genuinely open-ended multi-step task rather than a fixed pipeline.
 
### Statistical integrity caveat — important
Automatically generating and testing many hypotheses against the same dataset is a real statistical trap (the multiple comparisons problem / p-hacking). If the agent tests 20 hypotheses and only reports the ones with p < 0.05, some "significant" results are expected to be false positives by chance alone. Needs a correction method (Bonferroni, false discovery rate) built in, or at minimum the total number of hypotheses tested surfaced prominently alongside any result — otherwise the tool could quietly produce misleading science, a serious credibility risk for a research-facing product.
 
---
 
## Additional services worth separating out
 
Modeled after how corpus separates concerns internally — each of these is independently useful, not just a step in one big pipeline:
 
- **Citation graph service** — "find all papers citing X," reusable for a frontend visualization, not just chat answers.
- **Figure/vision service** — plate extraction + captioning as its own pipeline stage.
- **Report generation service** — compile everything known about a topic into a downloadable PDF/LaTeX report.
- **Translation service** — explicit support for non-English source literature (corpus handles this implicitly via multilingual embeddings; worth surfacing as a first-class feature for a research audience).
---
 
## Development & Deployment Workflow
 
Decided while comparing against how `corpus` runs its own development process — a genuinely mature example worth learning from directly, not just architecturally.
 
### Containerization: Docker
 
Docker solves "works on my machine" by packaging the app and everything it needs into a portable image that runs identically locally, in CI, and on AWS. Given the multi-service design above, each service gets its own `Dockerfile` and can be built/tested/deployed somewhat independently:
- Web app / API (researcher-facing frontend + backend)
- RAG document-search service
- Data analyst agent service
- Ingestion pipeline workers (background job queue workers — OCR, embedding, etc.)
**The machine → GitHub → AWS flow:**
1. Build/test a Docker image locally
2. Push code to GitHub
3. GitHub Actions builds the image in CI, runs tests against it
4. On success, the image is pushed to **Amazon ECR** (AWS's container registry, pairs naturally with ECS Fargate)
5. ECS pulls the new image and deploys it
### CI/CD: GitHub Actions, tiered
 
corpus doesn't run one big test suite — it runs **tiered CI**, visible directly in their README badges: a fast **T0 (lint + unit tests)** tier that runs on every push, and heavier **T1/T2 (integration tests)** tiers layered on top (their docs reference further T3/T4 tiers for full platform validation). Worth adopting the same shape here: cheap fast checks run constantly, expensive slow checks run less often.
 
Three tiers of CI value, roughly in build-first order:
1. **On every push/PR** — lint, run tests, confirm the Docker image builds. Catches broken code before it's anywhere near AWS.
2. **On merge to `main`** — build the image, push to ECR.
3. **Deploy step** — trigger ECS to roll out the new image. Worth gating behind a manual approval or staging environment rather than auto-deploying to production on every merge.
### Branching model
 
`main` stays always-deployable. Work happens on feature branches (`feature/rag-service`, `fix/chunk-overlap-bug`), merged back via pull request — even solo, since this is what makes CI meaningful: checks run *on the PR*, before anything touches `main`, not after.
 
**Multi-machine workflow (PC + laptop):** push before switching machines, pull before starting work. Uncommitted work shouldn't sit stranded on one machine — commit (even as a rough WIP commit on a feature branch) or stash before switching.
 
### Process artifacts, modeled on corpus
 
corpus documents its own process explicitly rather than leaving it as tribal knowledge — worth replicating:
- **`CONTRIBUTING.md`** — branching model, release ritual, version bumps, written down even for an audience of one.
- **`CHANGELOG.md`** — a running, human-readable log of what changed per release, separate from raw git history. Paired with a single source of truth for the version number (avoids version drift across `pip show`-equivalents, CLI `--version` output, bundle manifests, etc.).
- **`AGENTS.md`** — orientation instructions specifically for AI coding agents working in the repo (Claude Code, etc.). Start it early even though most implementation is done by hand at first — a thin version from day one, expanded as agent-assisted work ramps up. See the dedicated subsection below for what it should contain and how it grows.
- **API stability doc** (their `dev_docs/API_STABILITY.md`) — documents what's frozen at a given version and what counts as a breaking change. A later-stage maturity marker, not needed on day one.
- **Idempotent pipeline runs** — corpus's pipeline is designed so re-running it only reprocesses what changed. Worth carrying over as a design principle for this project's own ingestion pipeline stages, not just a process convention.
### `AGENTS.md` — plan
 
Purpose: a written orientation doc *for AI coding agents* (Claude Code, or any future agent working in the repo), separate from the human-facing `README.md`. Most implementation is done by hand at first, but agents are expected to take on more of the implementation work as the project matures — so this should exist early, even in thin form, rather than being written retroactively once agent-driven work is already underway and conventions have drifted unrecorded.
 
**v1 (write at Phase 1, alongside `CONTRIBUTING.md`) — thin, orientation only:**
- One-paragraph project summary + pointer to `ARCHITECTURE.md` and `PRODUCTION_PLAN.md` as the source of truth for design decisions and build order — agents should read those before proposing anything that contradicts a decision already made there (e.g. don't suggest OpenAI embeddings, don't suggest storing the API key server-side).
- Repo layout: where each service lives (`services/rag/`, `services/data-agent/`, frontend), monorepo structure.
- How to run things locally: `docker compose up`, how to run tests, how to run lint.
- Branching/PR conventions (mirrors `CONTRIBUTING.md`, kept short here as a quick reference).
- Explicit "don't" list: never commit `.env` / secrets, never touch RDS credentials directly, never bypass the BYO-key flow with a hardcoded key for convenience.
**v2 (expand once agents start doing real implementation work, roughly Phase 2+):**
- Per-service conventions as they solidify (naming, testing patterns, where config lives).
- Known gotchas worth surfacing proactively (the kind of thing in the small project's Troubleshooting Log — Windows encoding, PDF hyphenation, deprecated params — but for the production codebase as they're discovered).
- Pointers to which parts of the codebase are stable vs. actively being redesigned, so an agent doesn't confidently "fix" something mid-refactor.
Treat it the same way as `CHANGELOG.md` — cheap to update incrementally as you go, expensive to reconstruct accurately after the fact once conventions exist only in your head.
 
---
 
- **GitHub Projects (kanban board)** — worth using here, unlike the small learning project, since multiple services and workstreams (frontend, RAG service, data analyst agent, infra) benefit from a visual board rather than a flat issue list.
- **Milestones** — group issues into meaningful chunks (e.g., "MVP: single-service RAG web app," "Add data analyst agent," "Add auth") so progress is trackable above the level of individual issues.
- **Labels by service** (`rag-service`, `data-agent`, `infra`, `frontend`) to keep the board navigable as it grows.
### What to set up now vs. later
 
**Now:** `main` + feature branches with PRs, basic CI (lint + smoke test), a `CHANGELOG.md` kept incrementally from the start, a short `CONTRIBUTING.md`, a thin `AGENTS.md` v1 (orientation only).
**Later, once there's a real codebase and possibly contributors:** tiered integration tests, `AGENTS.md` v2 (per-service conventions, gotchas), formal API stability docs, full auto-deploy CD.
 
---
 
## Frontend
 
**Stack decided: React + TypeScript, built with Vite, hosted on S3 + CloudFront.**
 
- **React** — large ecosystem, well-worn AWS deployment patterns.
- **TypeScript over plain JavaScript** — this project has multiple backend services (RAG service, data analyst agent) with real, evolving data shapes crossing the frontend/backend boundary (documents, chunks, hypothesis results, taxonomy data). TypeScript catches a backend field rename or shape change at compile time instead of at runtime in front of a researcher. Chosen specifically because this is heading to production, not because it's the default choice for every project — the small learning project stayed plain Python/JS-free for a reason (lower ceremony while learning fundamentals).
- **Vite** — modern standard build tool; Create React App is deprecated.
- **S3 + CloudFront** — static SPA build, decouples frontend deploys from backend service deploys entirely (frontend can ship without touching ECS).
### Per-user data and persistence
 
Every researcher brings their own documents/datasets and needs to be able to save and return to their work — this is a real requirement, not an edge case to defer indefinitely, and it's already implied by the data layer decided above:
 
- **S3** — user-scoped prefixes for uploads, e.g. `s3://bucket/users/{user_id}/documents/`.
- **Postgres/pgvector** — every row (documents, chunks, embeddings) needs a `user_id` column, and every query needs to filter by it. This is the concrete mechanism behind the Phase 8 (Auth & Multi-User) checkpoint: one researcher's documents/queries must not be visible to another.
- **"Save what they're working on" implies actual projects/sessions as a first-class concept**, not just "upload and query once." A researcher likely has multiple named collections (e.g., "My siphonophore papers" vs. "a side project"), each with its own document set and its own conversation history — worth modeling as its own entity (a `projects` table owning documents and chat history) rather than bolting on later.
---
 
## Document parsing & chunking: Docling + HybridChunker
 
**Decision: adopt Docling for PDF parsing, paired with its `HybridChunker` for structure-aware chunking — replacing `pypdf` + `RecursiveCharacterTextSplitter`.** Adopted now rather than deferred, per the reasoning below.
 
**Why not just swap the chunker in isolation:** `HybridChunker` operates on Docling's own structured document representation (headings, sections, tables — detected via Docling's layout model and TableFormer), not on raw extracted text. Feeding it `pypdf`'s flat text output would defeat most of its value, since the sentence/paragraph/heading boundaries it relies on wouldn't exist yet. Adopting `HybridChunker` therefore means replacing the whole extraction front end, not swapping one class.
 
**What this fixes, concretely:** the small project's real debugging session traced a retrieval failure to `pypdf` preserving PDF line-wrap hyphenation literally (`"dynam-\nics"`), and `RecursiveCharacterTextSplitter`'s character-count-only splitting had no awareness of sentence boundaries. Docling's layout-aware parsing and `HybridChunker`'s structure-aware splitting directly target both of these — not by accident, but because they're built around a real document's actual structure rather than counting characters.
 
**Tokenizer-matching requirement:** `HybridChunker` sizes chunks using the tokenizer of whichever embedding model it's paired with. This is a hard dependency, not a detail — the chunker must be re-paired (and the vector store rebuilt) any time the embedding model changes, same as any other embedding model swap already established as normal practice in this project.
 
**Resolves the embedding model open question below:** `BAAI/bge-small-en-v1.5` now (CPU-only, no GPU required, already proven working), `BGE-M3` later once deployed on AWS with GPU compute available for processing (matching corpus's own choice, and giving multilingual/cross-lingual retrieval — relevant once non-English taxonomic literature enters the corpus). The `HybridChunker` tokenizer pairing gets updated at that same cutover point.
 
---
 
## Open questions / revisit later
 
- Exact query-cost estimate a researcher should expect on their own API key, to set expectations in onboarding docs.
- Whether BYO-key should remain the *only* option long-term, or whether a limited free tier (our key, capped) gets added back once there's real usage data to size it against.
- Exact trigger point for the `bge-small-en-v1.5` → `BGE-M3` cutover (tied to AWS GPU compute becoming available for ingestion processing, per the Docling/HybridChunker decision above) — not yet scheduled to a specific phase.
 