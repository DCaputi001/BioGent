"""One database engine and session factory, shared by the API and the worker.

Separate from db_credentials.py, which resolves the connection *string*, and
from documents.py, which uses the sessions. Kept in its own module so both
long-running processes open exactly one pool with the same configuration,
rather than each growing its own.

Nothing here runs at import time: the engine is built on first use, so importing
app.db in a test or a CLI never reaches for AWS or Postgres.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import db_credentials


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """The process-wide engine.

    pool_pre_ping matters for the worker specifically: it can sit idle between
    uploads for longer than Postgres or an idle NAT/firewall will hold a
    connection open, and without it the first query after a quiet spell fails
    on a socket the pool still believes is good.

    Inherits the credential-caching gap in KNOWN_ISSUES.md -- an RDS password
    rotation is not picked up until the process restarts, which matters more
    for a worker that can idle for days than it did for a CLI run.
    """
    return create_engine(db_credentials.get_database_url(), pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """A transactional session: commits on success, rolls back on any error.

    expire_on_commit is off in the factory above so attributes read after the
    block are still usable -- otherwise touching a returned object would emit a
    query against a session that has already closed.
    """
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
