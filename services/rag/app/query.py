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

Isolation (Phase 8): retrieval is always scoped to one user_id, which is a
required argument rather than an optional filter. A default would mean "search
everything", so forgetting to pass one would silently return another
researcher's documents — the exact failure this scoping exists to prevent.
Callers get the id from a verified token (app/auth.py), never from the request
body.
"""

import argparse
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
    user_id: str,
    database_url: str | None = None,
    collection_name: str = config.COLLECTION_NAME,
    embedding_model: str = config.EMBEDDING_MODEL,
    k: int = config.RETRIEVER_K,
    anthropic_model: str = config.ANTHROPIC_MODEL,
    anthropic_api_key: str | None = None,
):
    """Assemble the retrieve -> prompt -> Claude -> parse chain for one user."""
    retriever = build_retriever(
        user_id,
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


def ask(question: str, user_id: str, anthropic_api_key: str | None = None) -> str:
    """Convenience entry point: build a chain and answer one question."""
    chain = build_chain(user_id, anthropic_api_key=anthropic_api_key)
    return chain.invoke(question)


def owner_filter(user_id: str) -> dict:
    """The metadata filter restricting retrieval to one researcher's documents.

    Defined once here because ingest.py writes the matching key: the filter and
    the metadata it matches are one piece of knowledge, and a rename that
    touched only one of them would silently return nothing rather than fail.
    """
    return {config.OWNER_METADATA_KEY: {"$eq": user_id}}


def build_retriever(
    user_id: str,
    database_url: str | None = None,
    collection_name: str = config.COLLECTION_NAME,
    embedding_model: str = config.EMBEDDING_MODEL,
    k: int = config.RETRIEVER_K,
):
    """A retriever scoped to one user's documents, without the rest of the chain.

    Split out so the eval harness (services/rag/evals/) can inspect what
    was actually retrieved for a question, not just the final answer —
    needed for a faithfulness check ("does the answer's content actually
    come from this context, or did the model drift beyond it?").

    database_url=None resolves it via db_credentials (Secrets Manager or local).

    Prefer get_retriever() in anything long-lived: this reloads the embedding
    model on every call.
    """
    database_url = database_url or db_credentials.get_database_url()
    embeddings = HuggingFaceEmbeddings(model_name=embedding_model)
    db = PGVector(
        embeddings=embeddings,
        connection=database_url,
        collection_name=collection_name,
        use_jsonb=True,
    )
    return db.as_retriever(search_kwargs={"k": k, "filter": owner_filter(user_id)})


@lru_cache(maxsize=1)
def _get_vector_store() -> PGVector:
    """The embedding model and pgvector connection, built once per process.

    This, not the retriever, is what is expensive: HuggingFaceEmbeddings loads
    ~130MB of model. The store is identical for every researcher — only the
    filter applied on top of it differs — so it is shared, and get_retriever()
    layers a per-user filter over it cheaply. Caching whole retrievers per user
    instead would reload the model for each one.
    """
    return PGVector(
        embeddings=HuggingFaceEmbeddings(model_name=config.EMBEDDING_MODEL),
        connection=db_credentials.get_database_url(),
        collection_name=config.COLLECTION_NAME,
        use_jsonb=True,
    )


def get_retriever(user_id: str, k: int = config.RETRIEVER_K):
    """A retriever for one user, over the process-wide shared vector store.

    Cheap enough to call per request: as_retriever() only wraps the store that
    _get_vector_store() already holds.
    """
    return _get_vector_store().as_retriever(
        search_kwargs={"k": k, "filter": owner_filter(user_id)}
    )


def ask_with_context(
    question: str,
    retriever,
    anthropic_api_key: str | None = None,
) -> dict:
    """Like ask(), but also returns the retrieved context that produced it.

    Returns {"answer": str, "context": str, "sources": list[str]} — used by the
    eval harness for faithfulness checks, and by the HTTP API, which passes the
    cached retriever and the researcher's own key. Kept separate from ask()
    rather than changing ask()'s return type, so nothing that already depends
    on ask() returning a plain string breaks.

    The retriever is required, not built on demand from a default: it carries
    the identity whose documents are searched, so every caller has to have
    decided whose question this is before asking it.
    """
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
        # The raw chunks, for callers that need to judge them individually --
        # context precision scores each retrieved chunk, which the joined
        # context string cannot support. The HTTP API ignores this key.
        "documents": retrieved_docs,
    }

if __name__ == "__main__":
    # --user-id is required for the same reason it is required in code: this
    # REPL searches one researcher's documents, and there is no sensible
    # "everyone" default now that the corpus is shared between accounts.
    parser = argparse.ArgumentParser(description="Ask questions about ingested documents.")
    parser.add_argument(
        "--user-id",
        required=True,
        help="Whose documents to search (a Cognito sub, or the eval fixture id).",
    )
    args = parser.parse_args()

    chain = build_chain(args.user_id)
    print("Ask questions about your documents. Type 'exit' to quit.\n")

    while True:
        question = input("You: ")
        if question.strip().lower() in ("exit", "quit"):
            break
        answer = chain.invoke(question)
        print(f"\nAnswer: {answer}\n")