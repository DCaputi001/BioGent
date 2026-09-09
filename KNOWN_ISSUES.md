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

<!--
Template for future entries:

## Short description of the gap

**Where:** file/module/service

**What's incomplete:** what's missing or simplified, and what breaks (or could break) because of it

**Why deferred:** the real reason — usually a dependency on something not built yet, or a deliberate scope cut to keep a step isolated

**Unblocked by:** which future phase/decision resolves this

**Workaround until then:** what to do in the meantime, if anything
-->