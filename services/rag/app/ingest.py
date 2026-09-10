"""Ingestion: parse, structure-aware chunk, and embed documents into the vector store.

Vector storage: Postgres + pgvector, via langchain-postgres's PGVector class
— replaces the local Chroma directory used in Step 1. See ARCHITECTURE.md —
"Data layer: one unified database instead of many" for why.

Chunking: Docling (layout-aware PDF parsing) + HybridChunker (splits along
that structure, sized to the embedding model's own tokenizer), replacing
pypdf + RecursiveCharacterTextSplitter. See ARCHITECTURE.md — "Document
parsing & chunking: Docling + HybridChunker".

CAVEAT: Docling's API has moved fast across versions. If the
docling.chunking / docling_core import paths below fail, it's almost always
a renamed module/class in a newer release, not a logic error here.

NOTE: HybridChunker's tokenizer must match the embedding model actually used
for retrieval — chunk sizes are measured in that model's tokens. Currently
tokenizer-matched to BAAI/bge-small-en-v1.5 (config.EMBEDDING_MODEL). If the
embedding model changes (e.g. to BGE-M3), this must be re-paired and the
vector store rebuilt, same as any other embedding model swap.
"""

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from docling.chunking import HybridChunker
from docling.document_converter import DocumentConverter
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
from langchain_core.documents import Document as LCDocument
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_postgres import PGVector
from langchain_text_splitters import RecursiveCharacterTextSplitter
from transformers import AutoTokenizer

from app import config

load_dotenv()


@lru_cache(maxsize=1)
def _get_converter() -> DocumentConverter:
    """Lazily create (and cache) Docling's converter.

    Deliberately NOT instantiated at module import time — that would mean
    just importing this file (e.g. to unit test load_and_chunk_plaintext(),
    which has nothing to do with Docling) triggers Docling's model loading.
    lru_cache means the first real call pays that cost once, and every
    call after reuses the same instance, same as the old module-level
    approach — just deferred until actually needed.
    """
    return DocumentConverter()


def _build_chunker(embedding_model: str = config.EMBEDDING_MODEL) -> HybridChunker:
    """HybridChunker sized to the given embedding model's own tokenizer.

    This is the tokenizer-matching requirement from the module docstring —
    chunk boundaries are computed in terms of THIS model's tokens, so the
    chunker and the embedding model used later in build_vector_store() must
    always be the same one.
    """
    hf_tokenizer = HuggingFaceTokenizer(
        tokenizer=AutoTokenizer.from_pretrained(embedding_model),
    )
    return HybridChunker(tokenizer=hf_tokenizer)


def load_and_chunk_pdfs(
    data_dir: Path = config.DATA_DIR,
    embedding_model: str = config.EMBEDDING_MODEL,
) -> list[LCDocument]:
    """Parse every PDF in data_dir with Docling, chunk with HybridChunker.

    Returns plain LangChain Document objects so everything downstream
    (the vector store, the retriever in query.py) is unchanged by this
    swap — the change is isolated to how chunks get produced, not how
    they're stored or searched.
    """
    chunker = _build_chunker(embedding_model)
    documents: list[LCDocument] = []
    converter = _get_converter()

    for pdf_path in sorted(Path(data_dir).glob("**/*.pdf")):
        result = converter.convert(str(pdf_path))
        docling_doc = result.document

        for chunk in chunker.chunk(docling_doc):
            # contextualize() prepends the chunk's heading trail (e.g.
            # "Modeling > Single-agent model") so a chunk read in isolation
            # still carries the section context it came from.
            text = chunker.contextualize(chunk)
            documents.append(
                LCDocument(page_content=text, metadata={"source": pdf_path.name})
            )

    return documents


def load_and_chunk_plaintext(
    data_dir: Path = config.DATA_DIR,
    chunk_size: int = config.CHUNK_SIZE,
    chunk_overlap: int = config.CHUNK_OVERLAP,
) -> list[LCDocument]:
    """.txt / .md files still use the plain character-based splitter.

    Docling's layout model recovers structure from a PDF's visual layout —
    plain text has no such layout to recover, so there's nothing for Docling
    to add here. RecursiveCharacterTextSplitter remains the right tool for
    this input type specifically.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )
    documents: list[LCDocument] = []

    paths = sorted(Path(data_dir).glob("**/*.txt")) + sorted(Path(data_dir).glob("**/*.md"))
    for path in paths:
        raw_text = path.read_text(encoding="utf-8")  # Windows cp1252 fix, from the small project
        for chunk_text in splitter.split_text(raw_text):
            documents.append(
                LCDocument(page_content=chunk_text, metadata={"source": path.name})
            )

    return documents


def build_vector_store(
    chunks: list[LCDocument],
    database_url: str = config.DATABASE_URL,
    collection_name: str = config.COLLECTION_NAME,
    embedding_model: str = config.EMBEDDING_MODEL,
    reset: bool = False,
) -> PGVector:
    """Embed chunks and add them to the Postgres/pgvector collection.

    By default this is ADDITIVE — existing chunks are kept, new ones are
    added alongside them, so ingesting one more document doesn't wipe out
    everything previously ingested. Pass reset=True to wipe the collection
    first (a full clean rebuild — useful for local dev/testing, or
    eventually a researcher explicitly clearing their project).

    KNOWN GAP: re-ingesting the exact same file with reset=False will
    duplicate that file's chunks, since nothing yet tracks "have I already
    ingested this specific document." See KNOWN_ISSUES.md — proper fix
    needs per-user document tracking (Phase 8).
    """
    embeddings = HuggingFaceEmbeddings(model_name=embedding_model)
    db = PGVector.from_documents(
        documents=chunks,
        embedding=embeddings,
        connection=database_url,
        collection_name=collection_name,
        use_jsonb=True,
        pre_delete_collection=reset,
    )
    return db


def run_ingestion(
    data_dir: Path = config.DATA_DIR,
    database_url: str = config.DATABASE_URL,
    collection_name: str = config.COLLECTION_NAME,
    reset: bool = False,
) -> dict:
    """Full ingestion pipeline. Returns counts for logging/verification.

    reset=False (default): add to whatever's already in the collection.
    reset=True: wipe the collection first, then ingest — a clean rebuild.
    """
    pdf_chunks = load_and_chunk_pdfs(data_dir)
    plaintext_chunks = load_and_chunk_plaintext(data_dir)
    chunks = pdf_chunks + plaintext_chunks

    if not chunks:
        return {"chunks": 0, "status": "no documents found"}

    build_vector_store(
        chunks, database_url=database_url, collection_name=collection_name, reset=reset
    )
    return {
        "pdf_chunks": len(pdf_chunks),
        "plaintext_chunks": len(plaintext_chunks),
        "total_chunks": len(chunks),
        "status": "ok",
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Ingest documents into the RAG vector store.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Wipe the collection before ingesting (a full clean rebuild), "
        "instead of the default additive behavior.",
    )
    args = parser.parse_args()

    result = run_ingestion(reset=args.reset)
    print(result)