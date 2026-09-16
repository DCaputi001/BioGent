# Known Issues & Deferred Work

Things we know are incomplete, imperfect, or need revisiting — deliberately deferred rather than fixed now, with the reasoning for *why* it's deferred and *when* it should get picked back up.

This is different from `ARCHITECTURE.md`'s "Open questions" section: open questions are design decisions not yet made. This file is for known gaps in something already built and working, where we made a conscious call to ship the simpler version now.

Format: what the gap is, where it lives, why it's deferred, what unblocks fixing it.

---

## Re-ingesting the same file creates duplicate chunks

**Where:** `services/rag/app/ingest.py` — `build_vector_store()` / `run_ingestion()`

**What's incomplete:** Ingestion is additive by default (`reset=False`) so a researcher can add new documents without wiping their existing ones — this was a deliberate fix (see `CHANGELOG.md`). But nothing currently tracks "have I already ingested this exact document." Re-ingesting the *same* file twice (e.g. to pick up a corrected version) will duplicate that file's chunks in the vector store rather than replacing them.

**Why deferred:** Properly fixing this means tracking "which document is this" per user, so a re-ingested file can be matched to its prior chunks and those specifically removed/replaced. That's tied to per-user document management, which doesn't fully exist until real accounts/multi-tenancy land.

**Unblocked by:** Phase 8 (Auth & Multi-User) in `PRODUCTION_PLAN.md` — once documents are tracked per-user with real identity (e.g. a `documents` table row per uploaded file, keyed by `user_id` + a content hash or filename), re-ingestion can look up "does this user already have this document" and replace just that document's chunks instead of duplicating or wiping everything.

**Workaround until then:** `reset=True` on `run_ingestion()` for a full clean rebuild when a duplicate is suspected — same manual "wipe and redo" habit as the small project's `chroma_db` deletion, just via a function argument instead of deleting a folder.

---

## OCR is off by default, so scanned PDFs ingest as empty

**Where:** `services/rag/app/config.py` (`DO_OCR`) / `app/ingest.py` (`_get_converter()`)

**What's incomplete:** Docling runs OCR over every PDF page by default. Research papers are born-digital and already carry a text layer, so OCR detected nothing while costing roughly 90 seconds per ingestion run (35 consecutive "text detection result is empty" warnings on a two-PDF corpus). OCR is now opt-in via `RAG_DO_OCR`, defaulting to off. The gap: a scanned or image-only PDF now ingests as zero chunks silently, with nothing telling the researcher why their document produced no answers.

**Why deferred:** Doing this properly means detecting per document whether a text layer exists and enabling OCR only for the ones that need it, rather than a single global flag. That detection belongs at upload time, alongside the per-document tracking that doesn't exist yet.

**Unblocked by:** Phase 8 (Auth & Multi-User) in `PRODUCTION_PLAN.md` — the same `documents` table that fixes re-ingestion duplicates is where a per-document "needs OCR" decision would live, set once at upload instead of guessed globally at ingest time.

**Workaround until then:** Set `RAG_DO_OCR=true` in `services/rag/.env` when ingesting scanned documents, and back to `false` afterward.

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

<!--
Template for future entries:

## Short description of the gap

**Where:** file/module/service

**What's incomplete:** what's missing or simplified, and what breaks (or could break) because of it

**Why deferred:** the real reason — usually a dependency on something not built yet, or a deliberate scope cut to keep a step isolated

**Unblocked by:** which future phase/decision resolves this

**Workaround until then:** what to do in the meantime, if anything
-->