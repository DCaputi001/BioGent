"""Centralized configuration for the RAG service.

Every value here was a hardcoded constant in the original small-project
scripts (DATA_DIR, embedding model name, chunk size, k, etc.). Pulling them
into one place, sourced from environment variables with sensible defaults,
is what "generalized beyond the hardcoded data/ folder" means in practice —
nothing below should need to be edited in code to change behavior.
"""

import os
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


# --- Paths ---
# Preserves the small project's behavior (a `data/` folder next to wherever
# the app runs), but can be overridden entirely — e.g. once Phase 3 swaps
# this for reading from S3 instead of local disk.
DATA_DIR = Path(os.getenv("RAG_DATA_DIR", "data"))

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