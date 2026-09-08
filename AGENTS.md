# AGENTS.md

Orientation for AI coding agents (Claude Code, or any future agent) working in this repository. This is a v1 — thin, orientation-only, per the plan in `ARCHITECTURE.md` (Development & Deployment Workflow → `AGENTS.md` — plan). Expect this file to grow once agent-driven implementation work ramps up.

---

## What this project is

BioGent is a production, multi-researcher, web-based platform for scientific/taxonomic literature research. It lets non-technical researchers upload documents and ask grounded questions about them (a RAG document-search service), and eventually hand off datasets to an AI data analyst agent that generates and statistically tests hypotheses (a second, separate service, built later).

**Before proposing any architectural change or new dependency, read `ARCHITECTURE.md` and `PRODUCTION_PLAN.md` first.** Many decisions that might look like open questions have already been made, with reasoning documented. Do not propose:
- OpenAI (or any other) embeddings — Anthropic doesn't provide an embeddings API; the decision on which embedding provider to use for the production system is documented in `ARCHITECTURE.md`.
- Storing the researcher's Anthropic API key server-side — the BYO-key flow is deliberately client-side only, never persisted server-side. See `ARCHITECTURE.md` → "Key decision: how the LLM gets paid for."
- SQLite for the production data layer — the decision is PostgreSQL + `pgvector` on RDS, specifically because SQLite handles concurrent multi-user writes poorly.
- Skipping Darwin Core taxonomy in favor of a simpler custom scheme — taxonomy/synonymy resolution is a locked decision, not an open question.

---

## Repo layout

```
BioGent/
├── services/
│   ├── rag/              # RAG document-search service (Python)
│   └── data-agent/       # data analyst agent — LangGraph + MCP (built later, Phase 7)
├── frontend/              # React + TypeScript + Vite web app
├── .github/
│   └── workflows/         # CI/CD (GitHub Actions)
├── ARCHITECTURE.md         # design decisions and reasoning — read this first
├── PRODUCTION_PLAN.md      # phased build order with checkpoints
├── CONTRIBUTING.md         # branching model, PR workflow
├── CHANGELOG.md            # running log of changes
└── README.md               # project summary
```

This is a **monorepo** — one repository for all services and the frontend, not split into separate repos per service.

---

## How to run things locally

Not yet applicable — repo is in early scaffolding (see `PRODUCTION_PLAN.md` for current phase). This section will be filled in once `services/rag/` has a working `Dockerfile` and `docker-compose.yml` (Phase 2).

---

## Branching / PR conventions

Full detail in `CONTRIBUTING.md`. Quick reference:
- Never commit directly to `main`. All work on a `feature/*` or `fix/*` branch, merged via PR.
- `main` should always be deployable.

---

## Explicit "don't" list

- Never commit `.env` files or any real secrets/API keys — `.gitignore` already excludes `.env` but allows `.env.example`.
- Never touch RDS credentials directly in code — use AWS Secrets Manager once that layer exists (Phase 3).
- Never hardcode an Anthropic API key anywhere in the app as a "convenience" bypass of the BYO-key flow — this breaks the core cost-model decision for this project.
- Never commit real research documents or datasets — `data/`, `uploads/`, and `chroma_db/`-style generated stores are git-ignored on purpose.

---

## Status

Early scaffolding. See `PRODUCTION_PLAN.md` for the current phase and what's next.