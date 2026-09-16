"""Query: retrieve relevant chunks and ask Claude, grounded in that context.
 
Vector storage: Postgres + pgvector, via langchain-postgres's PGVector class
— same swap as ingest.py. The chain-building logic itself (retrieve ->
prompt -> Claude -> parse) is unchanged from Step 1; only how the retriever
connects to the vector store changed.

BYO-key: every entry point takes an optional anthropic_api_key, which the HTTP
API (app/api.py) fills in per request so each query runs on the researcher's
own key. The key is passed to ChatAnthropic for that one call and never stored.
Left as None, ChatAnthropic falls back to ANTHROPIC_API_KEY in the environment
— the CLI and the eval harness rely on that, the web app must never use it.
"""

from functools import lru_cache

from langchain_anthropic import ChatAnthropic
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_postgres import PGVector

from app import config, db_credentials


def format_docs(docs: list) -> str:
    return "\n\n---\n\n".join(doc.page_content for doc in docs)


def source_names(docs: list) -> list[str]:
    """Unique source filenames behind an answer, kept in retrieval order.

    Ordered by relevance rather than sorted, so the strongest match reads
    first when the UI shows what an answer was grounded in.
    """
    names: list[str] = []
    for doc in docs:
        name = doc.metadata.get("source")
        if name and name not in names:
            names.append(name)
    return names


def _build_llm(anthropic_model: str, anthropic_api_key: str | None) -> ChatAnthropic:
    """ChatAnthropic on the caller's key when given one, else the env var.

    Passing api_key=None explicitly would override ChatAnthropic's own
    environment lookup, so the argument is omitted entirely in that case —
    that fallback is what the CLI and the evals run on.
    """
    if anthropic_api_key:
        return ChatAnthropic(model=anthropic_model, api_key=anthropic_api_key)
    return ChatAnthropic(model=anthropic_model)


def build_chain(
    database_url: str | None = None,
    collection_name: str = config.COLLECTION_NAME,
    embedding_model: str = config.EMBEDDING_MODEL,
    k: int = config.RETRIEVER_K,
    anthropic_model: str = config.ANTHROPIC_MODEL,
    anthropic_api_key: str | None = None,
):
    """Assemble the retrieve -> prompt -> Claude -> parse chain."""
    retriever = build_retriever(
        database_url=database_url,
        collection_name=collection_name,
        embedding_model=embedding_model,
        k=k,
    )

    prompt = ChatPromptTemplate.from_template(config.PROMPT_TEMPLATE)
    llm = _build_llm(anthropic_model, anthropic_api_key)

    chain = (
        {"context": retriever | format_docs, "question": RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )
    return chain


def ask(question: str, anthropic_api_key: str | None = None) -> str:
    """Convenience entry point: build a chain and answer one question."""
    chain = build_chain(anthropic_api_key=anthropic_api_key)
    return chain.invoke(question)


def build_retriever(
    database_url: str | None = None,
    collection_name: str = config.COLLECTION_NAME,
    embedding_model: str = config.EMBEDDING_MODEL,
    k: int = config.RETRIEVER_K,
):
    """The retriever alone, without the rest of the chain.
 
    Split out so the eval harness (services/rag/evals/) can inspect what
    was actually retrieved for a question, not just the final answer —
    needed for a faithfulness check ("does the answer's content actually
    come from this context, or did the model drift beyond it?").

    database_url=None resolves it via db_credentials (Secrets Manager or local).
    """
    database_url = database_url or db_credentials.get_database_url()
    embeddings = HuggingFaceEmbeddings(model_name=embedding_model)
    db = PGVector(
        embeddings=embeddings,
        connection=database_url,
        collection_name=collection_name,
        use_jsonb=True,
    )
    return db.as_retriever(search_kwargs={"k": k})


@lru_cache(maxsize=1)
def get_retriever():
    """The default retriever, built once per process.

    build_retriever() loads the embedding model (~130MB) and opens a new
    pgvector connection every call. That is fine for a CLI run that calls it
    once, but the HTTP API would otherwise pay it on EVERY request. Long-lived
    callers use this; anything needing non-default settings still calls
    build_retriever() directly.
    """
    return build_retriever()


def ask_with_context(
    question: str,
    anthropic_api_key: str | None = None,
    retriever=None,
) -> dict:
    """Like ask(), but also returns the retrieved context that produced it.

    Returns {"answer": str, "context": str, "sources": list[str]} — used by the
    eval harness for faithfulness checks, and by the HTTP API, which passes the
    cached retriever and the researcher's own key. Kept separate from ask()
    rather than changing ask()'s return type, so nothing that already depends
    on ask() returning a plain string breaks.
    """
    retriever = retriever or build_retriever()
    retrieved_docs = retriever.invoke(question)
    context = format_docs(retrieved_docs)

    prompt = ChatPromptTemplate.from_template(config.PROMPT_TEMPLATE)
    llm = _build_llm(config.ANTHROPIC_MODEL, anthropic_api_key)
    chain = prompt | llm | StrOutputParser()

    answer = chain.invoke({"context": context, "question": question})
    return {
        "answer": answer,
        "context": context,
        "sources": source_names(retrieved_docs),
    }

if __name__ == "__main__":
    chain = build_chain()
    print("Ask questions about your documents. Type 'exit' to quit.\n")

    while True:
        question = input("You: ")
        if question.strip().lower() in ("exit", "quit"):
            break
        answer = chain.invoke(question)
        print(f"\nAnswer: {answer}\n")