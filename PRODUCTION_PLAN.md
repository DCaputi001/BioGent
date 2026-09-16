# Production Build Plan — Phased Roadmap
 
Companion to `ARCHITECTURE.md` (the design decisions) — this is the *build order*. Same phase-by-phase approach as the small learning project, scoped up for a real, multi-service, deployed application. Each phase has a clear goal and a checkpoint before moving to the next. Nothing here starts until you're ready — this is the map, not a commitment to start immediately.
 
---
 
## Phase 0: Foundations & Accounts
 
Get every account and tool in place before writing application code.
 
- AWS account confirmed, credits applied
- GitHub organization or repo created (decide: one repo for everything (monorepo) vs. one repo per service — recommend starting monorepo, splitting later only if it becomes painful)
- Docker installed and working locally
- Anthropic Console access confirmed (for your own testing; researchers bring their own key per the BYO decision)
- LangSmith account created
**Checkpoint:** `docker run hello-world` succeeds locally. AWS console loads and credits are visible. Empty GitHub repo exists.
 
---
 
## Phase 1: Repo Scaffolding & Dev Workflow
 
Set up the process before the product — this is what Phase 6 of the small project (LangSmith, tuning discipline) and the corpus comparison both pointed at doing early.
 
- Initialize repo, `main` branch protected (require PRs, no direct pushes)
- `CONTRIBUTING.md` — even a short one: branching model, commit conventions
- `CHANGELOG.md` — started empty, updated from the first real change onward
- `AGENTS.md` v1 — thin orientation doc for AI coding agents (repo layout, how to run things, pointers to `ARCHITECTURE.md`/`PRODUCTION_PLAN.md`, a "don't" list). See `ARCHITECTURE.md` — Development & Deployment Workflow for the full plan. Expanded later once agent-driven implementation ramps up.
- `.gitignore` for Python, Docker, and any frontend framework chosen later
- Basic GitHub Actions workflow: lint + a placeholder test step, running on every PR (the "T0" tier from corpus)
- GitHub Project board created, with labels (`rag-service`, `data-agent`, `infra`, `frontend`) and a first milestone ("MVP: single-service RAG web app")
**Checkpoint:** opening a PR against `main` triggers the CI workflow and shows a pass/fail check.
 
---
 
## Phase 2: Core RAG Service — Containerized
 
Port the working logic from the small learning project into a real, containerized service. This is not new R&D — it's productionizing something already proven to work.
 
- New service directory (e.g., `services/rag/`) with its own `Dockerfile`
- Ingestion logic (loaders, chunking, embeddings) carried over, generalized beyond the hardcoded `data/` folder
- **`pypdf` + `RecursiveCharacterTextSplitter` swapped for Docling + `HybridChunker`** (structure-aware PDF parsing and chunking, tokenizer-matched to `bge-small-en-v1.5`) — see `ARCHITECTURE.md` — Document parsing & chunking. Adopted now rather than deferred.
- Query logic carried over as an internal function/module, not yet exposed over HTTP
- Local Chroma swapped for a **local Postgres + pgvector** container (via `docker-compose`, matching corpus's pattern of running Grobid as a companion service) — proving out the new data layer before touching RDS
- Existing test questions from the small project's debugging sessions become the first real test cases
- **In-repo eval harness** (`services/rag/evals/`) — a small set of test questions run against the real chain with a real API key, mixing faithfulness/refusal checks (no reference answer needed) with a few hardcoded regression cases tied to known past bugs (e.g. the small project's retrieval failure). Separate from the automated test suite (no API key, safe on every CI push) and separate from LangSmith (hosted, ongoing). See `ARCHITECTURE.md` — Observability & evaluation.
**Checkpoint:** `docker compose up` runs the service locally; ingesting a test PDF and querying it against pgvector returns a correct, grounded answer — reproducing what `query.py` already proved, just in the new stack. Running the eval harness produces a committed report showing all cases passing.
 
---
 
## Phase 3: Data Layer on AWS
 
Move from local Postgres to the real managed database.
 
- RDS Postgres instance provisioned, `pgvector` extension enabled
- Schema design: documents, chunks/embeddings, users, (later) taxonomy/bibliography tables
- S3 bucket for source PDFs, ingestion service reads from S3 instead of local disk
- Connection secrets handled via AWS Secrets Manager, not hardcoded or committed
**Checkpoint:** the containerized RAG service from Phase 2 runs against the RDS instance instead of local Postgres, with PDFs pulled from S3, and still returns correct answers.
 
---
 
## Phase 4: Minimal Web Frontend
 
The thinnest possible UI that proves the BYO-API-key flow end to end. Not the final design — a functional skeleton.
 
- React + TypeScript project scaffolded with Vite (per `ARCHITECTURE.md` — Frontend section)
- Simple UI with: a place to paste an Anthropic API key, a search box, an answer display
- API key handled client-side only per the architecture decision — never sent to persistent storage
- Backend endpoint that accepts a question + API key, runs the RAG chain using the *researcher's* key (not yours), returns the answer
- Clear error states for invalid/expired keys
- The "how to get an API key" onboarding page — this is the single biggest lever for the non-technical-researcher goal, worth real attention here, not an afterthought
- Deployed to S3 + CloudFront as a static build, decoupled from backend service deploys
**Checkpoint:** a question typed into the web UI, using a pasted-in API key, returns a real grounded answer — the full loop, researcher-facing, working.
 
---
 
## Phase 5: CI/CD to AWS
 
Automate what's been manual through Phases 2-4.
 
- Dockerfile(s) build successfully in GitHub Actions
- Images pushed to Amazon ECR on merge to `main`
- ECS Fargate service(s) set up, pulling from ECR
- Deploy step wired into Actions — gated behind manual approval initially, not full auto-deploy
- Basic health checks / logging confirmed working on the deployed service
**Checkpoint:** a merged PR results in an updated, running service on AWS, reachable at a real URL, without manual deployment steps.
 
---
 
## Phase 6: Observability & Evaluation
 
Bring LangSmith in properly now that there's a deployed service worth monitoring — this was flagged as "day one, not bolted on" in the architecture doc, and this is that day.
 
- Tracing enabled on the deployed service, not just local dev
- Evaluation dataset built from real test questions (carried over from the small project's debugging history, expanded with new ones)
- Context precision / faithfulness metrics tracked as a baseline
- Basic alerting or dashboard for error rates / failed queries
**Checkpoint:** a LangSmith dashboard shows real traces from the deployed app, and running the eval dataset produces a scored report.
 
---
 
## Phase 8: Auth & Multi-User
 
> **Runs before Phase 7.** Decided after the Phase 4 checkpoint passed: getting real researchers onto the RAG service teaches more than building a second service nobody is using yet, and it is what makes document upload possible. Phase numbers are deliberately NOT renumbered — they are referenced as identifiers from `ARCHITECTURE.md`, `KNOWN_ISSUES.md`, `AGENTS.md`, and commit history, so renumbering would silently repoint all of them. Read the order as 5 → 6 → 8 → 7 → 9 → 10.
 
Move from "anyone with the URL can use it" to real accounts.
 
- Amazon Cognito set up for user accounts/sessions
- Frontend gated behind login
- Per-user data isolation confirmed (one researcher's documents/queries aren't visible to another, unless explicitly shared)
- **Background ingestion pipeline** (SQS + workers on ECS Fargate, per `ARCHITECTURE.md` — Full component comparison). Called for in the architecture but never assigned a phase until now. It is load-bearing for upload: Docling parsing plus embedding takes minutes, far longer than a browser request can wait, so an upload has to hand off to a queue and report progress rather than block.
- **Researcher-facing document upload** — the product statement assumes it ("upload documents and ask grounded questions"), but no earlier phase owns it, so it is recorded here. It lands in this phase because it depends on this phase's work: uploads go to user-scoped S3 prefixes (`users/{user_id}/documents/`, per `ARCHITECTURE.md` — Per-user data and persistence), and without that every upload would join one shared corpus visible to everyone. It also needs the duplicate-chunk gap in `KNOWN_ISSUES.md` fixed, since re-uploading a corrected file is routine rather than rare. Until this phase ships, documents reach the corpus only via the operator-run `python -m app.ingest --from-s3`.
**Checkpoint:** two separate test accounts can use the app independently without seeing each other's data, each uploading their own documents.
 
---
 
## Phase 7: Data Analyst Agent — First Version
 
> **Runs after Phase 8**, per the note above. Nothing here depends on auth; it is sequenced second because researchers using the document-search service is worth more than a second service built ahead of demand.
 
Build the second service, following the LangGraph + MCP design already sketched in `ARCHITECTURE.md`.
 
- New service directory (`services/data-agent/`) with its own Dockerfile
- LangGraph graph implemented: profile → generate hypotheses → select test → execute (via sandboxed code execution tool) → interpret → loop/report
- Code execution sandbox tool wired in — this is the part that must never let the LLM fabricate a statistical result
- Multiple-comparisons correction (or at minimum, prominent disclosure of how many hypotheses were tested) built in from the start, per the integrity caveat already flagged
**Checkpoint:** given a real test dataset, the agent produces at least one correctly-computed, correctly-interpreted statistical result, with the sandbox tool visibly doing the actual computation (verifiable in LangSmith traces).
 
---
 
## Phase 9: Domain-Specific Layer (Taxonomy)
 
Bring in the Darwin Core taxonomy layer, following corpus's approach.
 
- Taxonomy source decided (WoRMS / DwC-A / GBIF, per the target research domain)
- Taxonomy ingestion into its own Postgres tables (or a dedicated schema)
- Synonymy resolution wired into the RAG retrieval path — a query using a historical name should surface papers using any synonym
**Checkpoint:** a test query using a deprecated/historical name for a species returns results from papers that only used the current name (or vice versa).
 
---
 
## Phase 10: Polish & Additional Services
 
Lower-priority, high-value additions, tackled once the core is solid.
 
- MCP server exposed as a secondary interface, alongside the web app, for power users
- Citation graph service
- Report generation service
- Figure/vision extraction service
- Translation service
**Checkpoint:** each additional service has its own working demo and its own entry in the GitHub Project board — not necessarily all shipped, but all tracked.
 
---
 
## Notes on using this plan
 
- This is not a strict waterfall — Phases 6 (observability) and parts of Phase 1 (process) are meant to be revisited continuously, not done once and forgotten.
- Phase order can shift, and has: **Phase 8 (auth, multi-user, upload) now runs before Phase 7 (data analyst agent)**, decided once the Phase 4 checkpoint passed. Phase numbers stay as they are — other documents cite them as identifiers — so the real sequence is 5 → 6 → 8 → 7 → 9 → 10.
- Note that users cannot reach any of this until Phase 5 deploys the backend to a public HTTPS URL and ships the frontend to S3 + CloudFront. Phase 5 is what makes the app usable at all; Phase 8 is what makes it safe for more than one person.
- Each phase should get its own milestone and set of GitHub Issues once started, same pattern as the small project.
 