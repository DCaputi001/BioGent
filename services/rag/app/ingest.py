"""Ingestion: load, split, and embed documents into the vector store.

Ported from the small learning project's ingest.py, generalized to take
paths as parameters (defaulting to config.py values) instead of hardcoding
them, so this can be called with a different data directory per caller —
e.g. a per-user directory once multi-tenancy lands (Phase 8).
"""

from pathlib import Path

from langchain_chroma import Chroma
from langchain_community.document_loaders import DirectoryLoader, PyPDFLoader, TextLoader
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app import config


def load_documents(data_dir: Path = config.DATA_DIR) -> list:
    """Load every PDF, .txt, and .md file from data_dir into Document objects."""
    pdf_loader = DirectoryLoader(str(data_dir), glob="**/*.pdf", loader_cls=PyPDFLoader)
    txt_loader = DirectoryLoader(
        str(data_dir), glob="**/*.txt", loader_cls=TextLoader,
        loader_kwargs={"encoding": "utf-8"},  # Windows cp1252 fix, from the small project
    )
    md_loader = DirectoryLoader(
        str(data_dir), glob="**/*.md", loader_cls=TextLoader,
        loader_kwargs={"encoding": "utf-8"},
    )

    docs = pdf_loader.load() + txt_loader.load() + md_loader.load()
    return docs


def split_documents(
    docs: list,
    chunk_size: int = config.CHUNK_SIZE,
    chunk_overlap: int = config.CHUNK_OVERLAP,
) -> list:
    """Split loaded documents into overlapping chunks."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )
    return splitter.split_documents(docs)


def build_vector_store(
    chunks: list,
    db_dir: Path = config.DB_DIR,
    embedding_model: str = config.EMBEDDING_MODEL,
) -> Chroma:
    """Embed chunks and persist them to a local Chroma vector store.

    NOTE: still Chroma at this stage deliberately — swapping to Postgres +
    pgvector is Step 2's job, kept separate so a break in that step is
    obviously a database-layer issue, not a regression in this logic.
    """
    embeddings = HuggingFaceEmbeddings(model_name=embedding_model)
    db = Chroma.from_documents(
        documents=chunks, embedding=embeddings, persist_directory=str(db_dir)
    )
    return db


def run_ingestion(
    data_dir: Path = config.DATA_DIR,
    db_dir: Path = config.DB_DIR,
) -> dict:
    """Full ingestion pipeline. Returns counts for logging/verification."""
    documents = load_documents(data_dir)
    if not documents:
        return {"documents": 0, "chunks": 0, "status": "no documents found"}

    chunks = split_documents(documents)
    build_vector_store(chunks, db_dir=db_dir)
    return {"documents": len(documents), "chunks": len(chunks), "status": "ok"}


if __name__ == "__main__":
    result = run_ingestion()
    print(result)