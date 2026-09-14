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