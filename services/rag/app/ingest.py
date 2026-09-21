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

from docling.chunking import HybridChunker
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
from langchain_core.documents import Document as LCDocument
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_postgres import PGVector
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from transformers import AutoTokenizer

from app import config, db_credentials, storage

# Short on purpose: this is a reachability probe, not a real query. A database
# that cannot answer in this long is down as far as ingestion is concerned.
DATABASE_PREFLIGHT_TIMEOUT_SECONDS = 5


@lru_cache(maxsize=1)
def _get_converter(do_ocr: bool = config.DO_OCR) -> DocumentConverter:
    """Lazily create (and cache) Docling's converter.

    Deliberately NOT instantiated at module import time — that would mean
    just importing this file (e.g. to unit test load_and_chunk_plaintext(),
    which has nothing to do with Docling) triggers Docling's model loading.
    lru_cache means the first real call pays that cost once, and every
    call after reuses the same instance, same as the old module-level
    approach — just deferred until actually needed.

    OCR is off unless config.DO_OCR says otherwise: a bare DocumentConverter()
    enables it, which wastes minutes on born-digital PDFs that already have a
    text layer. See config.DO_OCR and KNOWN_ISSUES.md.
    """
    pipeline_options = PdfPipelineOptions(do_ocr=do_ocr)
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
    )


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


def _chunk_metadata(source_name: str, user_id: str, document_id: str | None = None) -> dict:
    """The metadata written onto every chunk, whatever produced it.

    One definition for both loaders so the two cannot drift. The owner key is
    the one query.owner_filter() matches on, and both sides take its name from
    config.OWNER_METADATA_KEY — a chunk written without it is retrievable by
    nobody, which is silent rather than loud.

    document_id is absent for the operator's bulk --from-s3 ingest, which has
    no documents row behind it; uploaded documents always carry one.
    """
    metadata = {"source": source_name, config.OWNER_METADATA_KEY: user_id}
    if document_id is not None:
        metadata[config.DOCUMENT_METADATA_KEY] = str(document_id)
    return metadata


def chunk_ids(document_id, count: int, start: int = 0) -> list[str]:
    """Deterministic ids for one document's chunks: "{document_id}:{index}".

    This is what makes re-ingesting a corrected file safe. PGVector writes with
    ON CONFLICT (id) DO UPDATE, so the same id overwrites in place -- the
    duplicate-chunk bug in KNOWN_ISSUES.md stops being possible rather than
    being something a delete-then-insert has to get right. It also means a
    crash midway through leaves the document half-updated rather than
    half-duplicated, and the next run corrects it.

    Deleting works from the same rule: PGVector.delete() accepts only ids, not
    a metadata filter, so knowing a document's id and chunk count is exactly
    enough to remove it without touching langchain-postgres's tables directly.
    """
    return [f"{document_id}:{index}" for index in range(start, count)]


def load_and_chunk_pdfs(
    user_id: str,
    data_dir: Path = config.DATA_DIR,
    embedding_model: str = config.EMBEDDING_MODEL,
) -> list[LCDocument]:
    """Parse every PDF in data_dir with Docling, chunk with HybridChunker.

    Returns plain LangChain Document objects so everything downstream
    (the vector store, the retriever in query.py) is unchanged by this
    swap — the change is isolated to how chunks get produced, not how
    they're stored or searched.

    Every chunk is stamped with user_id, which is what makes it retrievable by
    that researcher and invisible to everyone else.
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
                LCDocument(page_content=text, metadata=_chunk_metadata(pdf_path.name, user_id))
            )

    return documents


def chunk_one_file(
    path: Path,
    user_id: str,
    document_id,
    do_ocr: bool = config.DO_OCR,
    embedding_model: str = config.EMBEDDING_MODEL,
) -> list[LCDocument]:
    """Parse and chunk a single uploaded file.

    The bulk loaders above glob a directory, which is right for the operator's
    --from-s3 run and wrong for an upload: the worker handles one file that it
    already knows the identity of, and globbing a temp directory to find it
    again would lose the document_id linking chunks back to their row.

    do_ocr is decided per document rather than read from the global setting,
    which is the gap KNOWN_ISSUES.md describes -- OCR costs roughly 90 seconds
    and finds nothing on a born-digital paper, so it has to be enabled only for
    the files that need it.
    """
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        chunker = _build_chunker(embedding_model)
        docling_doc = _get_converter(do_ocr).convert(str(path)).document
        texts = [chunker.contextualize(chunk) for chunk in chunker.chunk(docling_doc)]
    else:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=config.CHUNK_SIZE, chunk_overlap=config.CHUNK_OVERLAP
        )
        texts = splitter.split_text(path.read_text(encoding="utf-8"))

    metadata = _chunk_metadata(path.name, user_id, document_id)
    # A fresh dict per chunk: LangChain hands the same object through to the
    # vector store, so sharing one would make every chunk alias the same
    # metadata and any later per-chunk edit would apply to all of them.
    return [LCDocument(page_content=text, metadata=dict(metadata)) for text in texts]


def load_and_chunk_plaintext(
    user_id: str,
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
                LCDocument(page_content=chunk_text, metadata=_chunk_metadata(path.name, user_id))
            )

    return documents


def _check_database_connection(
    database_url: str,
    timeout_seconds: int = DATABASE_PREFLIGHT_TIMEOUT_SECONDS,
) -> None:
    """Fail fast when the vector store is unreachable.

    Parsing and embedding run for minutes before build_vector_store() opens its
    first connection, so without this probe an unreachable database burns that
    entire run before surfacing a connection error at the very end.

    Raises RuntimeError with the target host but never the password — the URL
    carries real credentials and this message ends up in logs and tracebacks.
    """
    safe_url = make_url(database_url).render_as_string(hide_password=True)
    engine = create_engine(database_url, connect_args={"connect_timeout": timeout_seconds})
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise RuntimeError(
            f"Cannot reach the vector store at {safe_url}. "
            "For RDS, check RAG_DB_SECRET_ID, RAG_DB_HOST, and RAG_DB_NAME in "
            "services/rag/.env. For local runs, check RAG_DATABASE_URL, or start "
            "the local database with 'docker compose up -d'."
        ) from exc
    finally:
        engine.dispose()


def build_vector_store(
    chunks: list[LCDocument],
    database_url: str | None = None,
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
    database_url = database_url or db_credentials.get_database_url()
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


def open_vector_store(
    database_url: str | None = None,
    collection_name: str = config.COLLECTION_NAME,
    embedding_model: str = config.EMBEDDING_MODEL,
) -> PGVector:
    """An existing collection, without writing anything to it."""
    return PGVector(
        embeddings=HuggingFaceEmbeddings(model_name=embedding_model),
        connection=database_url or db_credentials.get_database_url(),
        collection_name=collection_name,
        use_jsonb=True,
    )


def replace_document_chunks(
    chunks: list[LCDocument],
    document_id,
    previous_chunk_count: int | None = None,
    store: PGVector | None = None,
) -> int:
    """Write one document's chunks, superseding whatever it had before.

    Returns the new chunk count.

    Writes under deterministic ids, so PGVector's ON CONFLICT (id) DO UPDATE
    overwrites the previous version of each chunk in place. The only leftovers
    are the tail: if the corrected file produces fewer chunks than the original
    did, the surplus ids from the old run would otherwise linger and keep being
    retrieved as part of a document that no longer contains them.
    """
    store = store or open_vector_store()

    new_count = len(chunks)
    if new_count:
        store.add_documents(chunks, ids=chunk_ids(document_id, new_count))

    if previous_chunk_count and previous_chunk_count > new_count:
        store.delete(ids=chunk_ids(document_id, previous_chunk_count, start=new_count))

    return new_count


def delete_document_chunks(document_id, chunk_count: int | None, store: PGVector | None = None):
    """Remove every chunk belonging to one document.

    A null chunk_count means the document never finished ingesting, so there is
    nothing to remove -- not that its chunks are unknown.
    """
    if not chunk_count:
        return

    store = store or open_vector_store()
    store.delete(ids=chunk_ids(document_id, chunk_count))


def run_ingestion(
    user_id: str,
    data_dir: Path = config.DATA_DIR,
    database_url: str | None = None,
    collection_name: str = config.COLLECTION_NAME,
    reset: bool = False,
) -> dict:
    """Full ingestion pipeline. Returns counts for logging/verification.

    Every chunk is written owned by user_id and is retrievable only by them.

    reset=False (default): add to whatever's already in the collection.
    reset=True: wipe the collection first, then ingest — a clean rebuild.

    Note that reset wipes the WHOLE collection, not just this user's documents:
    it predates per-user ownership and is an operator's clean-rebuild tool, not
    a per-researcher one. Scoped deletion arrives with the documents table in
    Phase 8's upload stage (see KNOWN_ISSUES.md).

    database_url=None resolves it via db_credentials (Secrets Manager or local).
    """
    database_url = database_url or db_credentials.get_database_url()
    _check_database_connection(database_url)

    pdf_chunks = load_and_chunk_pdfs(user_id, data_dir)
    plaintext_chunks = load_and_chunk_plaintext(user_id, data_dir)
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
    import tempfile

    parser = argparse.ArgumentParser(description="Ingest documents into the RAG vector store.")
    parser.add_argument(
        "--user-id",
        required=True,
        help="Who will own these documents: a Cognito sub, or the eval fixture id "
        "(RAG_EVAL_USER_ID) when seeding the eval corpus. Only this owner can "
        "retrieve them.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Wipe the collection before ingesting (a full clean rebuild), "
        "instead of the default additive behavior.",
    )
    parser.add_argument(
        "--from-s3",
        action="store_true",
        help="Download documents from RAG_S3_BUCKET into a temporary directory and "
        "ingest those, instead of the local data/ folder.",
    )
    args = parser.parse_args()

    if args.from_s3:
        # Temporary so downloaded research documents are deleted when the run
        # ends, even on failure, instead of accumulating on local disk.
        with tempfile.TemporaryDirectory(prefix="biogent-s3-") as download_dir:
            downloaded = storage.download_documents_from_s3(Path(download_dir))
            print(f"Downloaded {len(downloaded)} documents from s3://{config.S3_BUCKET}")
            result = run_ingestion(
                args.user_id, data_dir=Path(download_dir), reset=args.reset
            )
    else:
        result = run_ingestion(args.user_id, reset=args.reset)
    print(result)