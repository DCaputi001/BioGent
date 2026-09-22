"""Reads and writes for the `questions` table: a researcher's question history.

Same rule as app/documents.py: every function that reaches a specific entry
takes both its id and the owner's user_id and filters on both. A question id is
a UUID a caller could hold from anywhere, so looking one up by id alone would
let a researcher read or delete someone else's history.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Question

# Enough to scroll back through a working session without the list becoming
# one enormous response. Older entries are kept; they are just not returned.
DEFAULT_HISTORY_LIMIT = 50
MAX_HISTORY_LIMIT = 200


def record(
    session: Session, user_id: str, question: str, answer: str, sources: list[str]
) -> Question:
    entry = Question(user_id=user_id, question=question, answer=answer, sources=list(sources))
    session.add(entry)
    session.flush()
    return entry


def list_for_user(
    session: Session, user_id: str, limit: int = DEFAULT_HISTORY_LIMIT
) -> list[Question]:
    """Newest first -- the order the ix_questions_user_created index serves."""
    return list(
        session.scalars(
            select(Question)
            .where(Question.user_id == user_id)
            .order_by(Question.created_at.desc())
            .limit(min(limit, MAX_HISTORY_LIMIT))
        )
    )


def get(session: Session, user_id: str, question_id: uuid.UUID) -> Question | None:
    return session.scalars(
        select(Question).where(Question.id == question_id, Question.user_id == user_id)
    ).one_or_none()


def delete(session: Session, entry: Question) -> None:
    session.delete(entry)
    session.flush()
