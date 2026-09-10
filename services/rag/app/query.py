"""Query: retrieve relevant chunks and ask Claude, grounded in that context.
 
Vector storage: Postgres + pgvector, via langchain-postgres's PGVector class
— same swap as ingest.py. The chain-building logic itself (retrieve ->
prompt -> Claude -> parse) is unchanged from Step 1; only how the retriever
connects to the vector store changed.
"""

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_postgres import PGVector

from app import config

load_dotenv()


def format_docs(docs: list) -> str:
    return "\n\n---\n\n".join(doc.page_content for doc in docs)


def build_chain(
    database_url: str = config.DATABASE_URL,
    collection_name: str = config.COLLECTION_NAME,
    embedding_model: str = config.EMBEDDING_MODEL,
    k: int = config.RETRIEVER_K,
    anthropic_model: str = config.ANTHROPIC_MODEL,
):
    """Assemble the retrieve -> prompt -> Claude -> parse chain."""
    embeddings = HuggingFaceEmbeddings(model_name=embedding_model)
    db = PGVector(
        embeddings=embeddings,
        connection=database_url,
        collection_name=collection_name,
        use_jsonb=True,
    )
    retriever = db.as_retriever(search_kwargs={"k": k})

    prompt = ChatPromptTemplate.from_template(config.PROMPT_TEMPLATE)
    llm = ChatAnthropic(model=anthropic_model)

    chain = (
        {"context": retriever | format_docs, "question": RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )
    return chain


def ask(question: str) -> str:
    """Convenience entry point: build a chain and answer one question."""
    chain = build_chain()
    return chain.invoke(question)


def build_retriever(
    database_url: str = config.DATABASE_URL,
    collection_name: str = config.COLLECTION_NAME,
    embedding_model: str = config.EMBEDDING_MODEL,
    k: int = config.RETRIEVER_K,
):
    """The retriever alone, without the rest of the chain.
 
    Split out so the eval harness (services/rag/evals/) can inspect what
    was actually retrieved for a question, not just the final answer —
    needed for a faithfulness check ("does the answer's content actually
    come from this context, or did the model drift beyond it?").
    """
    embeddings = HuggingFaceEmbeddings(model_name=embedding_model)
    db = PGVector(
        embeddings=embeddings,
        connection=database_url,
        collection_name=collection_name,
        use_jsonb=True,
    )
    return db.as_retriever(search_kwargs={"k": k})
 
 
def ask_with_context(question: str) -> dict:
    """Like ask(), but also returns the retrieved context that produced it.
 
    Returns {"answer": str, "context": str} — used by the eval harness for
    faithfulness checks. Kept separate from ask() rather than changing
    ask()'s return type, so nothing that already depends on ask() returning
    a plain string breaks.
    """
    retriever = build_retriever()
    retrieved_docs = retriever.invoke(question)
    context = format_docs(retrieved_docs)
 
    prompt = ChatPromptTemplate.from_template(config.PROMPT_TEMPLATE)
    llm = ChatAnthropic(model=config.ANTHROPIC_MODEL)
    chain = prompt | llm | StrOutputParser()
 
    answer = chain.invoke({"context": context, "question": question})
    return {"answer": answer, "context": context}

if __name__ == "__main__":
    chain = build_chain()
    print("Ask questions about your documents. Type 'exit' to quit.\n")

    while True:
        question = input("You: ")
        if question.strip().lower() in ("exit", "quit"):
            break
        answer = chain.invoke(question)
        print(f"\nAnswer: {answer}\n")