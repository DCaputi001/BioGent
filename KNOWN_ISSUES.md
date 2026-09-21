# Known Issues & Deferred Work

Things we know are incomplete, imperfect, or need revisiting — deliberately deferred rather than fixed now, with the reasoning for *why* it's deferred and *when* it should get picked back up.

This is different from `ARCHITECTURE.md`'s "Open questions" section: open questions are design decisions not yet made. This file is for known gaps in something already built and working, where we made a conscious call to ship the simpler version now.

Format: what the gap is, where it lives, why it's deferred, what unblocks fixing it.

---

## Re-ingesting the same file creates duplicate chunks

**Where:** `services/rag/app/ingest.py` — `build_vector_store()` / `run_ingestion()`

**Fixed for uploaded documents; still open for the operator CLI path.**

**What's incomplete:** A document uploaded through the web app no longer duplicates. Its chunks are written under deterministic ids (`{document_id}:{index}`), and PGVector writes with `ON CONFLICT (id) DO UPDATE`, so re-uploading a corrected file overwrites its chunks in place — and `replace_document_chunks()` trims the tail when the new version produces fewer. The remaining gap is the bulk path: `python -m app.ingest` and `--from-s3` still glob a directory with no `documents` row behind each file, so no id is available to write under, and re-running one duplicates exactly as before.

**Why deferred:** The operator path ingests whole directories that may not correspond to per-user documents at all, so giving it document identity means deciding what a "document" is for a bulk load nobody uploaded. That is a real design question, and the researcher-facing path — the one that actually gets re-run routinely — is fixed.

**Unblocked by:** Nothing external. It needs a decision about whether bulk ingestion should create `documents` rows, which would also give those files per-document OCR and deletion.

**Workaround until then:** `reset=True` on `run_ingestion()` for a full clean rebuild when a duplicate is suspected from a CLI run. Note this wipes the whole collection, including uploaded documents — re-seed the eval corpus afterwards.

---

## OCR is off by default, so scanned PDFs ingest as empty

**Where:** `services/rag/app/config.py` (`DO_OCR`) / `app/ingest.py` (`_get_converter()`)

**Fixed for uploaded documents; still open for the operator CLI path.**

**What's incomplete:** The worker now decides per document. It parses without OCR first, and if the result is almost empty (`worker.needs_ocr`, under 200 characters across all chunks) it re-parses with OCR on and records the decision in `documents.needs_ocr`. A file that still yields nothing is marked `failed` with a message naming the likely cause, so the silent-zero-chunks case is gone from the upload path. The bulk CLI path still reads the global `RAG_DO_OCR` flag, because it has no `documents` row to record a per-file decision in.

**Why deferred:** Same reason as the entry above — bulk ingestion has no per-document identity to hang the decision on.

**Unblocked by:** Nothing external; it follows whatever is decided about `documents` rows for bulk ingestion.

**Workaround until then:** Set `RAG_DO_OCR=true` in `services/rag/.env` when bulk-ingesting scanned documents, and back to `false` afterward. Uploads need no flag.

---

## Some chunks exceed the embedding model's 512-token limit and are silently truncated

**Where:** `services/rag/app/ingest.py` — `load_and_chunk_pdfs()` / `_build_chunker()`

**What's incomplete:** `HybridChunker` sizes chunks to `bge-small-en-v1.5`'s 512-token budget, but `chunker.contextualize()` prepends the heading trail *after* chunking, which pushes some chunks past the limit. Measured on the current two-PDF corpus: 10 of 154 chunks exceed 512 tokens (largest 531), and the model truncates those tails at embed time. The chunk text stored in Postgres is complete; only its vector under-represents the end of the chunk. Surfaces as the `transformers` warning "Token indices sequence length is longer than the specified maximum sequence length".

**Why deferred:** The overflow is small (about 4 percent on the worst chunk) and affects retrieval ranking subtly rather than breaking anything, so it was separated from the connection fix it was discovered alongside rather than bundled into it.

**Unblocked by:** Nothing external — this is fixable now by giving the chunker headroom for the heading prefix (e.g. `HuggingFaceTokenizer(..., max_tokens=480)`) or by measuring the contextualized length and re-splitting. It needs a re-ingest afterward, since existing vectors were built the old way.

**Workaround until then:** None needed for correctness; retrieval works, just marginally less precisely on the 10 affected chunks.

---

## Database credentials are cached for the life of the process, so an RDS password rotation isn't picked up

**Where:** `services/rag/app/db_credentials.py` — `get_database_url()`

**What's incomplete:** The URL built from the Secrets Manager secret is cached with `lru_cache`, so each process calls Secrets Manager once. RDS-managed master secrets rotate automatically. A process that is still running when a rotation happens keeps the old password, and its new connections then fail authentication until it restarts.

**Why deferred:** Today the service runs only as short-lived CLI commands (`app.ingest`, `app.query`, evals), which finish well within a rotation window and pick up the new password on the next run. Refresh logic (re-fetch the secret when authentication fails, then retry once) only earns its complexity once something runs for a long time.

**Unblocked by:** Phase 4 in `PRODUCTION_PLAN.md`, the long-running HTTP API. At that point, catch the authentication failure, call `get_database_url.cache_clear()`, rebuild the engine, and retry. The alternative is AWS's Secrets Manager caching client with a TTL.

**Workaround until then:** Restart any long-running `app.query` session after a rotation.

---

## Nothing tests the `documents` table against real SQL

**Where:** `services/rag/test/test_api_documents.py`, `test_worker.py` — and the absence of a test for `app/documents.py`

**What's incomplete:** The unit suite is deliberately database-free (`AGENTS.md` — fast, no credentials, runs on every push), and `app/models.py` uses `postgresql.UUID`, which will not run on SQLite. So the repository is exercised only through fakes: the tests prove the API calls it with the right owner and the worker updates the right statuses, but nothing executes the SQL. Specifically untested: that `UNIQUE (user_id, filename)` actually rejects a duplicate, that a re-upload reuses the existing row rather than raising `IntegrityError`, and that the CHECK constraint refuses an invalid status.

These are the parts most likely to be wrong in a way the fakes cannot show, because a fake repository agrees with whatever the caller believes.

**Why deferred:** Testing them means a real Postgres in CI — a service container, a migration step, and a slower pipeline — which is a tier of testing this project has not set up yet. `ARCHITECTURE.md` anticipates it ("tiered integration tests" under what to set up later).

**Unblocked by:** Nothing external. A `postgres` service container in `.github/workflows/ci.yml` plus `alembic upgrade head` would cover it, at the cost of a slower `rag-service-tests` job.

**Workaround until then:** The end-to-end verification in the PR covers it manually — upload, re-upload a corrected file, confirm the chunk count does not double.

---

## The eval corpus has to be re-seeded by hand after a reset

**Where:** `services/rag/evals/run_evals.py` — `build_eval_retriever()` / `app/ingest.py --user-id`

**What's incomplete:** Retrieval is now filtered by owner, and the eval harness runs as `RAG_EVAL_USER_ID` (default `eval-fixture`), which owns its own copy of the two ctenophore papers. That resolved the scoping problem, but the seeding is still a manual step: nothing in the repo recreates that corpus automatically, and `run_ingestion(reset=True)` wipes the whole collection rather than one owner's documents. So a clean rebuild silently takes the eval corpus with it, and the next eval run fails wholesale until someone re-runs the seed command.

**Why deferred:** Per-owner deletion needs the `documents` table, which lands with upload in Phase 8's second stage. Until then `reset` is a blunt operator tool and re-seeding is one command.

**Unblocked by:** Phase 8's upload stage, which brings per-document tracking and therefore scoped deletion — the same table the two entries above wait on.

**Workaround until then:** After any `--reset`, re-seed with `uv run python -m app.ingest --reset --user-id eval-fixture`, then re-ingest your own documents additively. If the whole suite fails at once, check the corpus exists before suspecting a retrieval regression.

---

<!--
Template for future entries:

## Short description of the gap

**Where:** file/module/service

**What's incomplete:** what's missing or simplified, and what breaks (or could break) because of it

**Why deferred:** the real reason — usually a dependency on something not built yet, or a deliberate scope cut to keep a step isolated

**Unblocked by:** which future phase/decision resolves this

**Workaround until then:** what to do in the meantime, if anything
-->