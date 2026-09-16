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

# --- AWS (shared by S3 and Secrets Manager) ---
# Credentials are deliberately NOT read here. boto3's default chain resolves
# them for every service: AWS_PROFILE (~/.aws) locally, the IAM role on AWS.
# Raw AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY in .env are not the supported
# method — the chain checks them BEFORE AWS_PROFILE, so stale keys left beside
# a profile would silently win.
# botocore only reads AWS_DEFAULT_REGION when creating a client; AWS_REGION is
# accepted too because it's the name most people (and .env.example) reach for.
AWS_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
# Appended to every AWS failure message so S3 and Secrets Manager errors point
# at the same place to look.
AWS_CREDENTIALS_HINT = (
    "Check AWS_PROFILE and AWS_REGION in services/rag/.env "
    "(or the IAM role, when running on AWS)."
)

# --- S3 document source (optional — only used by `app.ingest --from-s3`) ---
S3_BUCKET = os.getenv("RAG_S3_BUCKET")
S3_PREFIX = os.getenv("RAG_S3_PREFIX", "")

# --- Vector store: Postgres + pgvector ---
# Replaces the small project's local Chroma directory (RAG_DB_DIR / chroma_db).
# Always read the connection through app.db_credentials.get_database_url(),
# never these values directly: it picks between the two sources below.
#
# Source 1 (RDS): RAG_DB_SECRET_ID names a Secrets Manager secret holding the
# username/password. The password never appears in env vars or files. An
# RDS-managed master secret holds only username/password, so host, port, and
# database name come from the non-secret settings here; a secret that does
# include host/port/dbname takes precedence over them.
DB_SECRET_ID = os.getenv("RAG_DB_SECRET_ID")
DB_HOST = os.getenv("RAG_DB_HOST")
DB_PORT = _env_int("RAG_DB_PORT", 5432)
DB_NAME = os.getenv("RAG_DB_NAME")
DB_SSLMODE = os.getenv("RAG_DB_SSLMODE", "require")
#
# Source 2 (local dev only, used when RAG_DB_SECRET_ID is unset): a full URL.
# The default matches docker-compose.yml's throwaway local Postgres login.
# Never point this at RDS — that would put a real password back into .env.
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