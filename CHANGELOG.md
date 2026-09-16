# Changelog

All notable changes to this project are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/); dates are when the change was merged to `main`.

---

## [Unreleased]

### Added
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

### Changed
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