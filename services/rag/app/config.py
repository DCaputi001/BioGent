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
# Defaults preserve the small project's behavior (a `data/` folder next to
# wherever the app runs), but can be overridden entirely — e.g. once Phase 3
# swaps this for reading from S3 instead of local disk.
DATA_DIR = Path(os.getenv("RAG_DATA_DIR", "data"))
DB_DIR = Path(os.getenv("RAG_DB_DIR", "chroma_db"))  # swapped for pgvector in Step 2

# --- Embeddings ---
# Settled on BAAI/bge-small-en-v1.5 after the small project's retrieval
# debugging session — see the small project's README Troubleshooting Log.
EMBEDDING_MODEL = os.getenv("RAG_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")

# --- Chunking ---
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