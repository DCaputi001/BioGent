"""Database credentials: resolve the vector store connection URL at call time.

On RDS the password lives only in AWS Secrets Manager (RAG_DB_SECRET_ID) and
is fetched when a connection is first needed. It never passes through env
vars, .env, or committed files. Without a secret ID this falls back to
config.DATABASE_URL, the local docker-compose Postgres.

Nothing here runs at import time, so importing ingest.py or query.py (as the
unit tests do) needs no AWS credentials and makes no network calls.
"""

import json
from functools import lru_cache

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy.engine import URL

from app import config

POSTGRES_DRIVER = "postgresql+psycopg"


def resolve_database_url(client=None) -> str:
    """Build the connection URL from Secrets Manager, or return the local URL.

    Uncached, and reads config at call time, so tests can monkeypatch config
    and pass a fake client. Application code should call get_database_url().

    Raises RuntimeError naming the secret ID (never any secret value) when the
    secret cannot be fetched, is malformed, or leaves host/database unset.
    """
    secret_id = config.DB_SECRET_ID
    if not secret_id:
        return config.DATABASE_URL

    secret = _fetch_secret(secret_id, client)
    return _build_url(secret, secret_id)


@lru_cache(maxsize=1)
def get_database_url() -> str:
    """Cached resolve_database_url(): one Secrets Manager call per process.

    KNOWN GAP: the cache is never refreshed, so a long-running process keeps
    the old password after an RDS rotation. Fine for the current CLI scripts;
    see KNOWN_ISSUES.md.
    """
    return resolve_database_url()


def _fetch_secret(secret_id: str, client) -> dict:
    client = client or boto3.client("secretsmanager", region_name=config.AWS_REGION)
    try:
        response = client.get_secret_value(SecretId=secret_id)
    except (ClientError, BotoCoreError) as exc:
        raise RuntimeError(
            f"Failed to read database secret {secret_id!r} from AWS Secrets Manager. "
            f"Check RAG_DB_SECRET_ID and secretsmanager:GetSecretValue permission. "
            f"{config.AWS_CREDENTIALS_HINT}"
        ) from exc

    # "from None" on parse failures: the chained exception can carry the raw
    # secret text (JSONDecodeError.doc), which must not reach logs or tracebacks.
    try:
        secret = json.loads(response["SecretString"])
    except (KeyError, TypeError, json.JSONDecodeError):
        raise RuntimeError(
            f"Database secret {secret_id!r} is not a JSON SecretString."
        ) from None
    # RuntimeError rather than TypeError: callers handle one exception type for
    # every unusable-secret case.
    if isinstance(secret, dict):
        return secret
    raise RuntimeError(f"Database secret {secret_id!r} is not a JSON object.")


def _build_url(secret: dict, secret_id: str) -> str:
    username = secret.get("username")
    password = secret.get("password")
    if not username or not password:
        raise RuntimeError(
            f"Database secret {secret_id!r} is missing 'username' or 'password'."
        )

    # RDS-managed master secrets hold only username/password; a secret that
    # also carries connection details is treated as the source of truth.
    host = secret.get("host") or config.DB_HOST
    port = secret.get("port") or config.DB_PORT
    database = secret.get("dbname") or config.DB_NAME
    if not host or not database:
        raise RuntimeError(
            f"Database secret {secret_id!r} has no host/dbname, and RAG_DB_HOST or "
            "RAG_DB_NAME is unset. Set them in services/rag/.env."
        )

    # URL.create escapes the password itself. RDS-generated passwords contain
    # characters such as @ / : % that corrupt a hand-concatenated URL.
    url = URL.create(
        POSTGRES_DRIVER,
        username=username,
        password=password,
        host=host,
        port=int(port),
        database=database,
        query={"sslmode": config.DB_SSLMODE},
    )
    return url.render_as_string(hide_password=False)
