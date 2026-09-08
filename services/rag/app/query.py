"""Query: retrieve relevant chunks and ask Claude, grounded in that context.

Ported from the small learning project's query.py. The chain-building logic
is unchanged (same LCEL pipeline); what's new is that every setting that was
a bare constant before now comes from config.py, and build_chain() takes
parameters so a future caller (e.g. an HTTP endpoint) can override any of
them per-request if needed.
"""

from pathlib import Path

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_chroma import Chroma
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_huggingface import HuggingFaceEmbeddings

from app import config

load_dotenv()


def format_docs(docs: list) -> str:
    return "\n\n---\n\n".join(doc.page_content for doc in docs)


def build_chain(
    db_dir: Path = config.DB_DIR,
    embedding_model: str = config.EMBEDDING_MODEL,
    k: int = config.RETRIEVER_K,
    anthropic_model: str = config.ANTHROPIC_MODEL,
):
    """Assemble the retrieve -> prompt -> Claude -> parse chain."""
    embeddings = HuggingFaceEmbeddings(model_name=embedding_model)
    db = Chroma(persist_directory=str(db_dir), embedding_function=embeddings)
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


if __name__ == "__main__":
    chain = build_chain()
    print("Ask questions about your documents. Type 'exit' to quit.\n")

    while True:
        question = input("You: ")
        if question.strip().lower() in ("exit", "quit"):
            break
        answer = chain.invoke(question)
        print(f"\nAnswer: {answer}\n")