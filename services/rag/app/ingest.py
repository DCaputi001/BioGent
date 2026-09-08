"""Ingestion: parse, structure-aware chunk, and embed documents into the vector store.

Replaces pypdf + RecursiveCharacterTextSplitter with Docling (layout-aware PDF
parsing — headings, sections, tables detected structurally, not by character
count) + HybridChunker (splits along that structure, sized to the embedding
model's own tokenizer). See ARCHITECTURE.md — "Document parsing & chunking:
Docling + HybridChunker" for the full reasoning and the corpus comparison
this was based on.

CAVEAT: Docling's API has moved fast across versions. The chunker
construction below (HuggingFaceTokenizer wrapping a transformers
AutoTokenizer) matches the pattern documented in Docling's own examples as of
this writing, but double-check `docling.chunking` / `docling_core` import
paths against whatever version `uv sync` actually installs — if either
import fails, the fix is almost always a renamed module/class in a newer
release, not a logic error here.

NOTE: HybridChunker's tokenizer must match the embedding model actually used
for retrieval — chunk sizes are measured in that model's tokens. Currently
tokenizer-matched to BAAI/bge-small-en-v1.5 (config.EMBEDDING_MODEL). If the
embedding model changes (e.g. to BGE-M3 once AWS GPU compute is available —
see ARCHITECTURE.md open questions), this must be re-paired and the vector
store rebuilt, same as any other embedding model swap.
"""

from pathlib import Path

from dotenv import load_dotenv
from docling.chunking import HybridChunker
from docling.document_converter import DocumentConverter
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
from langchain_chroma import Chroma
from langchain_core.documents import Document as LCDocument
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from transformers import AutoTokenizer

from app import config

load_dotenv()

# Reused across calls — Docling's converter loads its layout/table models
# once; re-instantiating per file would reload them every time.
_converter = DocumentConverter()


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
    (Chroma, the retriever in query.py) is unchanged by this swap — the
    change is isolated to how chunks get produced, not how they're stored
    or searched.
    """
    chunker = _build_chunker(embedding_model)
    documents: list[LCDocument] = []

    for pdf_path in sorted(Path(data_dir).glob("**/*.pdf")):
        result = _converter.convert(str(pdf_path))
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
    db_dir: Path = config.DB_DIR,
    embedding_model: str = config.EMBEDDING_MODEL,
) -> Chroma:
    """Embed chunks and persist them to a local Chroma vector store."""
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
    pdf_chunks = load_and_chunk_pdfs(data_dir)
    plaintext_chunks = load_and_chunk_plaintext(data_dir)
    chunks = pdf_chunks + plaintext_chunks

    if not chunks:
        return {"chunks": 0, "status": "no documents found"}

    build_vector_store(chunks, db_dir=db_dir)
    return {
        "pdf_chunks": len(pdf_chunks),
        "plaintext_chunks": len(plaintext_chunks),
        "total_chunks": len(chunks),
        "status": "ok",
    }


if __name__ == "__main__":
    result = run_ingestion()
    print(result)