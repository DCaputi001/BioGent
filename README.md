# BioGent

A production, multi-researcher, web-based platform for scientific/taxonomic literature research — built so a non-technical researcher can search their own document collection, ask grounded questions, and eventually hand off datasets to an AI data analyst agent, all without any local setup, command line, or MCP client installation.

This project is directly informed by comparing its design against [caseywdunn/corpus](https://github.com/caseywdunn/corpus), a mature RAG system built for taxonomic/biodiversity research — see `ARCHITECTURE.md` for the detailed comparison and the reasoning behind every major decision below.

---

## The goal, stated plainly

Give researchers who aren't computer-savvy a web app where they can:
- Upload their own papers/documents and ask grounded questions about them (RAG document-search service)
- Hand off a dataset and get back statistically tested hypotheses (data analyst agent — planned, later phase)
- Do all of this without installing anything, editing config files, or bringing their own infrastructure

---

## Key decisions already made

| Decision | Choice |
|---|---|
| LLM cost model | Researcher brings their own Anthropic API key (BYO), pasted into the web app |
| Auth & multi-user | Amazon Cognito; every document and query is scoped to the signed-in researcher |
| Vector + relational data | PostgreSQL + `pgvector`, on Amazon RDS |
| Document storage | S3, with a background SQS + Fargate worker parsing and embedding uploads |
| Frontend | React + TypeScript, built with Vite, hosted on S3 + CloudFront |
| Observability | LangSmith — tracing + evaluation, built in from day one |
| Taxonomy | Darwin Core (WoRMS/GBIF/ITIS), synonymy resolution |
| Deployment | Docker containers per service, GitHub Actions CI/CD, ECS Fargate on AWS |
| Repo structure | Monorepo, split into per-service directories under `services/` |

Full reasoning for each of these lives in `ARCHITECTURE.md`.

---

## Project structure

```
BioGent/
├── services/
│   ├── rag/              # RAG document-search service
│   └── data-agent/       # data analyst agent (LangGraph + MCP) — built later
├── frontend/              # React + TypeScript + Vite web app
├── .github/
│   └── workflows/         # CI/CD (GitHub Actions)
├── ARCHITECTURE.md         # design decisions and reasoning
├── PRODUCTION_PLAN.md      # phased build order
├── CONTRIBUTING.md         # branching model, conventions
├── CHANGELOG.md            # running log of changes
├── AGENTS.md               # orientation for AI coding agents working in this repo
└── README.md               # this file
```

---

## Where this came from

This project follows a smaller, local-only learning project (a single-user LangChain + Claude RAG CLI tool) that proved out the core retrieval concepts — chunking, embeddings, vector search — including a real debugging session that traced a retrieval failure down to PDF line-wrap hyphenation. That project is not part of this repo; this repo is the production version, designed from scratch with multi-user, web-based, and cost-model constraints in mind from day one.

---

## Documentation map

- **`ARCHITECTURE.md`** — every design decision and the reasoning behind it (data layer, LLM cost model, frontend stack, observability, the two-service split, dev/deploy workflow).
- **`PRODUCTION_PLAN.md`** — the phased build order, Phase 0 through Phase 10, each with a concrete checkpoint.
- **`CONTRIBUTING.md`** — branching model and commit conventions.
- **`AGENTS.md`** — orientation for AI coding agents (Claude Code, etc.) working in this repo.
- **`KNOWN_ISSUES.md`** — deliberately deferred gaps, with the reasoning and what unblocks each one.

---

## Status

The core RAG document-search service is live in production: researchers sign in with their own account, upload papers, and ask grounded questions against their own document library, with each researcher's documents and question history isolated from every other's. Concretely, per `PRODUCTION_PLAN.md`:

- **Phases 0–6 complete** — repo scaffolding, the containerized RAG service, RDS + S3 as the data layer, the web frontend with the BYO-key flow, CI/CD to ECS Fargate, and LangSmith tracing + an in-repo eval harness.
- **Phase 8 complete** — Cognito accounts, per-user document isolation, document upload with background parsing/embedding (SQS + a Fargate worker), and saved question history. This was the last phase gating Phase 7.
- **Not started** — Phase 7 (the data analyst agent, a second LangGraph + MCP service), Phase 9 (Darwin Core taxonomy layer), and Phase 10 (polish: MCP server, citation graph, report generation, and related services).

Known gaps and deliberately deferred work are tracked in `KNOWN_ISSUES.md`. See `PRODUCTION_PLAN.md` for the full phase-by-phase checkpoints.

## License

Not yet decided.