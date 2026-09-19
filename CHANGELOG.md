# Changelog

All notable changes to this project are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/); dates are when the change was merged to `main`.

---

## [Unreleased]

### Added
- **Accounts and per-user document isolation (Phase 8, first stage).** Amazon Cognito user pool, public SPA client and hosted sign-in page in `infra/cognito.tf`; the frontend is gated behind sign-in; `POST /api/ask` now requires a Cognito access token alongside the Anthropic key. The two credentials answer different questions and neither substitutes for the other: the token decides *whose documents are searched*, the key decides *whose Anthropic account pays*. The user id comes from the verified token and never from the request body, covered by a regression test — a body field naming another user would otherwise undo the whole isolation boundary.
- Isolation is a `user_id` key in chunk metadata, filtered on every retrieval, per `ARCHITECTURE.md` ("Per-user data and persistence") — not a collection per user. `KNOWN_ISSUES.md` had left that mechanism open; it is now settled. `langchain_pg_embedding.cmetadata` is already JSONB with a GIN index, so this needed no schema migration. `app/ingest.py` takes a required `--user-id`, and `query.build_retriever`/`get_retriever` take a required `user_id`: a default would mean "search everything", making a forgotten argument a silent cross-user leak rather than an error.
- `app/auth.py` verifies Cognito access tokens locally against the pool's JWKS (RS256 pinned, so an `alg: none` token is refused). Two checks are easy to miss and are tested explicitly: Cognito access tokens carry no `aud` claim, so audience verification is off and `client_id` is checked by hand instead; and an ID token from the same pool is correctly signed and issued, so only `token_use` distinguishes it from an access token. A JWKS outage returns a retryable 503 rather than a 401 — telling a correctly signed-in researcher to sign in again cannot help and discards a valid session. Adds `pyjwt[crypto]`.
- `missing_auth` / `invalid_token` (401) and `auth_unavailable` (503) error codes, kept distinct from the Anthropic-key 401s so the UI branches on the code rather than the status: a rejected key and an expired session are both 401, and offering "use a different key" to someone whose session merely expired sends them to fix the wrong credential.
- The eval harness runs as its own identity (`RAG_EVAL_USER_ID`, default `eval-fixture`), which owns a seeded copy of the corpus — the fix `KNOWN_ISSUES.md` prescribed for the scoping gap that per-user filtering would otherwise have opened. Seed with `uv run python -m app.ingest --reset --user-id eval-fixture`.
- Expanded the eval harness (Phase 6): `evals/checks.py` adds `check_retrieval` (did the right source document come back, separate from whether the answer used it) and `judge_context_precision` (fraction of retrieved chunks an LLM judge scores as relevant to the question — the Phase 6 baseline metric). `EvalCase` gains a `score` alongside pass/fail, and `run_evals.py` reports per-check-type mean scores rather than one pass count, so a retrieval regression and a faithfulness regression stay distinguishable. Cases rewritten against the corpus actually loaded (two ctenophore papers); the orphaned Formula 1 regression case was removed with explicit sign-off and replaced with `yoda1-inhibits-mleipiezo`, which fails if the model answers from training data (Yoda1 activates PIEZO1 in general knowledge) instead of the ingested paper (it inhibits the ctenophore channel MleiPIEZO).
- `--case` and `--no-judge` flags on `run_evals.py`; reports now record the commit, answering/judge/embedding models and `RETRIEVER_K`, so a committed score is reproducible.
- LangSmith tracing (Phase 6): `LANGSMITH_TRACING` / `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT` are read directly by LangChain's SDK, so no code change is needed to trace `query.py`/`api.py` calls — `config.py` documents them and warns once if tracing is enabled with no key. `run_evals.py` routes its own traces to a separate `-evals` project so eval runs don't pollute the dashboard used for real traffic. Production wiring lives in `infra/` (`langsmith_secret_arn`, default `""` — a no-op until a secret is created and set); ECS resolves the key natively via the execution role rather than application code, since it needs no parsing the way the database password does.
- Initial repo scaffolding: `services/rag/`, `services/data-agent/`, `frontend/`, `.github/workflows/` directory structure.
- `.gitignore` covering Python, Node/React, Docker, and local data/secrets.
- Project `README.md` with goal statement, key decisions summary, and structure overview.
- `CONTRIBUTING.md` documenting branching model and PR workflow.
- `AGENTS.md` v1 — orientation doc for AI coding agents working in this repo.
- `.gitkeep` placeholders in empty service/frontend/workflow directories so they survive `git clone` on a new machine.
- Fail-fast database reachability check in `run_ingestion()` — an unreachable vector store now fails in about a second instead of after a multi-minute parse and embed.
- `RAG_DO_OCR` setting (default off) making Docling's PDF OCR opt-in; it found nothing on born-digital papers while costing roughly 90 seconds per run.
- `.env.example` now documents `RAG_DATABASE_URL` and `RAG_DO_OCR`, not just `ANTHROPIC_API_KEY`.
- `python -m app.ingest --from-s3`: ingests documents from `RAG_S3_BUCKET` (optionally scoped by `RAG_S3_PREFIX`) via a new, separate `app/storage.py`. Files download to a temporary directory that is deleted after the run; parsing and chunking are unchanged. Adds `boto3`. `AWS_REGION` is honored explicitly, since botocore on its own only reads `AWS_DEFAULT_REGION`.
- RDS credentials via AWS Secrets Manager: a new `app/db_credentials.py` builds the connection URL at runtime from the secret named by `RAG_DB_SECRET_ID` (host/port/database from `RAG_DB_HOST`/`RAG_DB_PORT`/`RAG_DB_NAME` when the secret lacks them, `sslmode=require` by default). The RDS password no longer belongs in `.env`. `RAG_DATABASE_URL` stays as the local docker-compose fallback when no secret ID is set.
- `secret-scan` CI job (gitleaks, full history) on every push and PR.
- HTTP API (`app/api.py`, FastAPI): `POST /ask` answers a question from the ingested documents and returns `{answer, sources}`; `GET /health` for liveness. Run with `uv run uvicorn app.api:app --reload --port 8000`. Adds `fastapi` and `uvicorn[standard]`.
- BYO-key over HTTP: `/ask` requires the researcher's Anthropic key in an `X-Anthropic-Api-Key` header, uses it for that one call, and never stores or logs it. It deliberately does not fall back to a server-side `ANTHROPIC_API_KEY` (a missing or blank header is a 401), so the operator can never silently pay for a query. Covered by a regression test.
- `RAG_CORS_ORIGINS` (default `http://localhost:5173`) for the Vite dev server.
- Build order changed in `PRODUCTION_PLAN.md`: Phase 8 (auth, multi-user, document upload) now runs before Phase 7 (data analyst agent), so real researchers can use the document-search service while the second service is built. Phase numbers were kept as-is rather than renumbered, since `ARCHITECTURE.md`, `KNOWN_ISSUES.md`, `AGENTS.md`, and commit history all cite them as identifiers. Phase 8 also gained the background ingestion pipeline (SQS + Fargate workers), which the architecture called for but no phase owned.
- Web frontend (`frontend/`, React + TypeScript + Vite): paste an Anthropic API key, ask a question, read the answer with the source documents listed. This completes the Phase 4 checkpoint — the BYO-key loop working end to end for a researcher. The key is held in `sessionStorage` (survives a reload, gone when the tab closes), sent as a header with each question, and never persisted server-side. `VITE_API_BASE_URL` points at the backend; note that every `VITE_`-prefixed variable is embedded in the built JavaScript in plain text, so none may hold a secret.
- Actionable error states in the UI: failures are grouped by remedy rather than by status code (`src/api/errorActions.ts`), so a rejected key offers "use a different key", an empty balance links to Anthropic billing with no pointless retry, and rate limits or an unreachable service offer "try again". An unreachable service also names the uvicorn command, since locally that nearly always means the API is not running.
- Onboarding page explaining how to get an Anthropic API key, including the trap that a new key with no credit behind it fails on the first question. `ARCHITECTURE.md` flags this page as the single biggest lever for the non-technical-researcher goal.
- Frontend test suite (vitest + Testing Library, 32 tests) and a `frontend-tests` CI job (`npm ci`, lint, test, build) replacing the placeholder block.
- Researcher-facing error responses (`app/errors.py`): every API failure returns one shape, `{"error": {"code", "message", "retryable"}}`, with a plain-English message naming the action to take. Covers a rejected key (401), exhausted credit (402, detected from Anthropic's 400 wording since there is no billing-specific status), blocked model access (403), rate limiting (429), Anthropic unreachable or erroring (502), vector store down (503), and anything else (500). Stack traces, connection strings, and the API key stay in the server log and never reach the response body.

### Changed
- **Container image cut from 10.7GB to 3.8GB** by resolving `torch` and `torchvision` from PyTorch's CPU-only index (`[tool.uv.index]` in `pyproject.toml`). The default Linux wheels bundle CUDA runtimes that cannot execute on Fargate, where each task pulls the image on every start. Both packages must come from the same index: a CPU `torch` beside a default-index `torchvision` imports cleanly and then fails with `operator torchvision::nms does not exist` the first time a model loads.
- The embedding model (`BAAI/bge-small-en-v1.5`) is baked into the image at build time under `HF_HOME=/opt/hf-cache`, so a task serves requests without downloading it first. Verified by embedding successfully with `--network none`. Not `~/.cache`, which docker-compose mounts a volume over.
- The image serves the HTTP API by default (`CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", ...]`). The previous `CMD ["-m", "app.query"]` relied on an `ENTRYPOINT` the Dockerfile never declared, so a fresh build could not start without an explicit command; every existing caller passed one, so it went unnoticed. `docker run <image> python -m app.ingest` still overrides it.
- Added `services/rag/.dockerignore`, keeping `.venv`, `data/` (real research PDFs), caches and tests out of the build context.
- **API routes moved under `/api`** (`/api/ask`, `/api/health`). In production one CloudFront distribution serves the frontend from S3 and routes `/api/*` to the backend, so the service owns the prefix rather than depending on an edge function to rewrite paths. A useful side effect: frontend and API share an origin in production, so CORS no longer applies there. Local callers must add the prefix, and `VITE_API_BASE_URL` now includes it.
- `ARCHITECTURE.md` and `PRODUCTION_PLAN.md` are now tracked in git. They were excluded by a `#planning` block in `.gitignore`, which left `AGENTS.md` and `KNOWN_ISSUES.md` pointing at files absent from a fresh clone.
- `query.py` entry points (`build_chain`, `ask`, `ask_with_context`) take an optional `anthropic_api_key`; left unset they use `ANTHROPIC_API_KEY` from the environment exactly as before, so the CLI and evals are unchanged. `ask_with_context` also returns a `sources` list and accepts a prebuilt retriever. New `get_retriever()` caches the retriever per process, so the HTTP API loads the embedding model once instead of on every request.
- `database_url` parameters in `ingest.py` and `query.py` now default to `None` and resolve at call time through `db_credentials.get_database_url()`, rather than binding `config.DATABASE_URL` at import. `build_chain()` now reuses `build_retriever()`.
- `config.S3_REGION` renamed to `config.AWS_REGION`, since S3 and Secrets Manager share it. Same env vars (`AWS_REGION`, then `AWS_DEFAULT_REGION`).
- Local AWS access now uses one AWS CLI profile (`AWS_PROFILE`) for both S3 and Secrets Manager, replacing raw `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` in `.env`. Remove those keys from existing `.env` files: boto3 checks them before `AWS_PROFILE`, so leftovers silently win. `docker-compose.yml` mounts `~/.aws` read-only into the `rag` container so the profile resolves there too.

### Fixed
- `.env` was ignored entirely: `ingest.py` and `query.py` called `load_dotenv()` *after* importing `app.config`, which resolves every `os.getenv()` at import time. Every setting silently fell back to its default, so a `RAG_DATABASE_URL` pointing at RDS still connected to `localhost`. `config.py` now loads `.env` itself, before reading any variable. Note this changes which database a default run targets on any machine with a populated `.env`.

---

<!--
Template for future entries:

## [x.y.z] - YYYY-MM-DD

### Added
- New features

### Changed
- Changes to existing functionality

### Fixed
- Bug fixes

### Removed
- Removed features
-->