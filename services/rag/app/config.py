"""Centralized configuration for the RAG service.

Every value here was a hardcoded constant in the original small-project
scripts (DATA_DIR, embedding model name, chunk size, k, etc.). Pulling them
into one place, sourced from environment variables with sensible defaults,
is what "generalized beyond the hardcoded data/ folder" means in practice —
nothing below should need to be edited in code to change behavior.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Must run BEFORE the os.getenv() calls below: every value in this module is
# resolved once, at import time. ingest.py/query.py previously called this
# AFTER importing this module, which meant .env was read too late to affect
# anything here — a .env pointing at RDS was silently ignored in favor of the
# localhost default. override=False (the default) is deliberate: real
# environment variables injected by docker-compose or CI still win over a .env
# file that happens to be present. See docker-compose.yml's NETWORKING NOTE.
load_dotenv()


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def _env_bool(name: str, default: bool) -> bool:
    """Parse a boolean env var, accepting the usual spellings people reach for."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# --- Paths ---
# Preserves the small project's behavior (a `data/` folder next to wherever
# the app runs), but can be overridden entirely. `app.ingest --from-s3`
# bypasses it and ingests from a temporary download of RAG_S3_BUCKET instead.
DATA_DIR = Path(os.getenv("RAG_DATA_DIR", "data"))

# --- S3 document source (optional — only used by `app.ingest --from-s3`) ---
# Credentials are deliberately NOT read here: boto3's default chain (env vars
# loaded by load_dotenv above, ~/.aws, or an IAM role on AWS) handles them.
S3_BUCKET = os.getenv("RAG_S3_BUCKET")
S3_PREFIX = os.getenv("RAG_S3_PREFIX", "")
# botocore only reads AWS_DEFAULT_REGION when creating a client; AWS_REGION is
# accepted too because it's the name most people (and .env.example) reach for.
S3_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")

# --- Vector store: Postgres + pgvector ---
# Replaces the small project's local Chroma directory (RAG_DB_DIR / chroma_db).
# Defaults match docker-compose.yml's local Postgres service — override via
# .env for a different local setup, and via real secrets management once
# this points at RDS in Phase 3.
DATABASE_URL = os.getenv(
    "RAG_DATABASE_URL",
    "postgresql+psycopg://biogent:biogent@localhost:5432/biogent_rag",
)
# pgvector stores multiple "collections" (logical groupings of vectors) in
# one database — this is the name for this service's collection, distinct
# from any other vector data that might eventually share the same database
# (e.g. the data analyst agent, if it ever needs embeddings of its own).
COLLECTION_NAME = os.getenv("RAG_COLLECTION_NAME", "biogent_rag_documents")

# --- Embeddings ---
# Settled on BAAI/bge-small-en-v1.5 after the small project's retrieval
# debugging session — see the small project's README Troubleshooting Log.
# Swaps to BGE-M3 once AWS GPU compute is available — see ARCHITECTURE.md.
EMBEDDING_MODEL = os.getenv("RAG_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")

# --- Document parsing ---
# Docling runs OCR over every PDF page by default. Research PDFs are
# born-digital and already carry a text layer, so OCR detects nothing while
# costing roughly 90 seconds per run (35 consecutive "text detection result is
# empty" warnings on a two-PDF corpus). Off by default; turn on for scanned or
# image-only documents. See KNOWN_ISSUES.md.
DO_OCR = _env_bool("RAG_DO_OCR", False)

# --- Chunking (plain text only — PDFs use Docling's HybridChunker instead,
# which sizes itself from EMBEDDING_MODEL's own tokenizer, not these) ---
CHUNK_SIZE = _env_int("RAG_CHUNK_SIZE", 1000)
CHUNK_OVERLAP = _env_int("RAG_CHUNK_OVERLAP", 400)

# --- Retrieval ---
RETRIEVER_K = _env_int("RAG_RETRIEVER_K", 4)

# --- LLM ---
ANTHROPIC_MODEL = os.getenv("RAG_ANTHROPIC_MODEL", "claude-sonnet-5")

PROMPT_TEMPLATE = """
Answer the question using only the context below. If the answer isn't
in the context, say you don't know — don't make something up.

Context:
{context}

Question:
{question}
"""