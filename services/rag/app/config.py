"""Centralized configuration for the RAG service.

Every value here was a hardcoded constant in the original small-project
scripts (DATA_DIR, embedding model name, chunk size, k, etc.). Pulling them
into one place, sourced from environment variables with sensible defaults,
is what "generalized beyond the hardcoded data/ folder" means in practice —
nothing below should need to be edited in code to change behavior.
"""

import logging
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

# The chunk-metadata key holding the owning researcher's Cognito sub. Phase 8
# isolates users by filtering on this key rather than by giving each one their
# own collection (ARCHITECTURE.md -- "Per-user data and persistence"). Lives
# here so ingest.py (which writes it) and query.py (which filters on it) share
# one definition; a rename touching only one side would return nothing rather
# than fail. Deliberately NOT environment-overridable: changing it would orphan
# every chunk already written under the old key.
OWNER_METADATA_KEY = "user_id"

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

# --- Evaluation ---
# The model that judges eval runs (evals/). Separate from ANTHROPIC_MODEL so a
# judge can stay fixed while the answering model changes -- otherwise swapping
# the answering model silently moves the scoring baseline too, and a run is no
# longer comparable with the reports committed before it.
EVAL_JUDGE_MODEL = os.getenv("RAG_EVAL_JUDGE_MODEL", ANTHROPIC_MODEL)

# The identity that owns the eval corpus. Phase 8 filters every retrieval by
# user_id, but an eval run never authenticates, so without an identity of its
# own the filter would match nothing and every case would fail for a scoping
# reason rather than a quality one (KNOWN_ISSUES.md called this out before the
# filtering landed). Deliberately a fixed sentinel string, not a real Cognito
# sub: the eval corpus is seeded by `app.ingest --user-id`, belongs to no human
# account, and must stay reproducible from a fresh clone.
EVAL_USER_ID = os.getenv("RAG_EVAL_USER_ID", "eval-fixture")

# --- LangSmith tracing (Phase 6) ---
# Not read by this app's own code -- LangChain's SDK picks these three up
# directly from os.environ at invoke time, so setting them is enough to trace
# every chain call. Exposed here anyway, so this stays the one place to see
# every environment variable the service responds to, per this file's own
# stated purpose. LANGSMITH_* is the current name; the older LANGCHAIN_*
# spelling still works but is not what new setup should use.
LANGSMITH_TRACING = _env_bool("LANGSMITH_TRACING", False)
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "biogent-rag-dev")


def _warn_if_tracing_misconfigured(tracing: bool, has_key: bool) -> None:
    """Log once if tracing is on but has nothing to authenticate with.

    A plain function rather than bare module-level code so a test can call it
    directly with arbitrary inputs, instead of having to reload this module
    under different environment variables to exercise both branches.

    Not fatal: the LangSmith client swallows trace-submission failures, so a
    missing key would not break a real query -- it would just silently
    produce zero traces, which is a worse failure mode than a log line.
    """
    if tracing and not has_key:
        logging.getLogger(__name__).warning(
            "LANGSMITH_TRACING is enabled but LANGSMITH_API_KEY is unset. "
            "Tracing will silently produce no traces until it is set."
        )


_warn_if_tracing_misconfigured(LANGSMITH_TRACING, bool(os.getenv("LANGSMITH_API_KEY")))

# --- Authentication: Amazon Cognito (Phase 8) ---
# Identifies WHO is asking, which is a separate question from the Anthropic key,
# which only decides who PAYS. Both are required on a query: the token scopes
# retrieval to the caller's own documents, the key bills that caller's Anthropic
# account. Neither is a secret to this service -- the pool and client ids are
# public identifiers, and the client is a public SPA client with no secret at
# all, so these are plain environment variables rather than Secrets Manager
# entries. Unset locally means the API refuses to start an authenticated route;
# see app/auth.py.
COGNITO_USER_POOL_ID = os.getenv("RAG_COGNITO_USER_POOL_ID")
COGNITO_CLIENT_ID = os.getenv("RAG_COGNITO_CLIENT_ID")

# --- HTTP API ---
# Origins the browser may call the API from. Defaults to Vite's dev server.
# Comma-separated, so deployments can add their CloudFront domain. The
# researcher's Anthropic key is never read from the environment here: it
# arrives per request, per the BYO-key decision in ARCHITECTURE.md.
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("RAG_CORS_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]

PROMPT_TEMPLATE = """
Answer the question using only the context below. If the answer isn't
in the context, say you don't know — don't make something up.

Context:
{context}

Question:
{question}
"""