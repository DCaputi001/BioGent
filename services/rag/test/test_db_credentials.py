"""Unit tests for app.db_credentials — connection URL resolution against a fake client.

No network and no AWS credentials: a fake Secrets Manager client returns a
canned SecretString. This checks how the URL is assembled and that failures
never leak the password. Fetching a real secret is left to the manual RDS check.
"""

import json

import pytest
from botocore.exceptions import ClientError
from sqlalchemy.engine import make_url

from app import config
from app.db_credentials import resolve_database_url

SECRET_ID = "biogent/rds/master"
PASSWORD = "p@ss/w:rd%"


class FakeSecretsManagerClient:
    """Stands in for boto3's Secrets Manager client; returns one fixed secret."""

    def __init__(self, secret_string: str):
        self._secret_string = secret_string
        self.requested_ids: list[str] = []

    # Capitalized parameter name mirrors boto3's keyword argument.
    def get_secret_value(self, SecretId: str) -> dict:
        self.requested_ids.append(SecretId)
        return {"SecretString": self._secret_string}


class FailingSecretsManagerClient:
    def get_secret_value(self, SecretId: str) -> dict:
        raise ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "not authorized"}},
            "GetSecretValue",
        )


def _client_for(secret: dict) -> FakeSecretsManagerClient:
    return FakeSecretsManagerClient(json.dumps(secret))


@pytest.fixture
def rds_config(monkeypatch):
    """Config as it looks on RDS: a secret ID plus non-secret connection details."""
    monkeypatch.setattr(config, "DB_SECRET_ID", SECRET_ID)
    monkeypatch.setattr(config, "DB_HOST", "env-host.rds.example")
    monkeypatch.setattr(config, "DB_PORT", 5432)
    monkeypatch.setattr(config, "DB_NAME", "env_db")
    monkeypatch.setattr(config, "DB_SSLMODE", "require")


def test_without_secret_id_returns_local_url(monkeypatch):
    monkeypatch.setattr(config, "DB_SECRET_ID", None)
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/db")

    assert resolve_database_url() == "postgresql+psycopg://u:p@localhost:5432/db"


def test_rds_managed_secret_uses_env_connection_details(rds_config):
    client = _client_for({"username": "admin", "password": PASSWORD})

    url = make_url(resolve_database_url(client=client))

    assert client.requested_ids == [SECRET_ID]
    assert url.drivername == "postgresql+psycopg"
    assert url.username == "admin"
    assert url.host == "env-host.rds.example"
    assert url.port == 5432
    assert url.database == "env_db"
    assert url.query["sslmode"] == "require"


def test_connection_details_in_secret_take_precedence(rds_config):
    client = _client_for(
        {
            "username": "admin",
            "password": PASSWORD,
            "host": "secret-host.rds.example",
            "port": "6543",
            "dbname": "secret_db",
        }
    )

    url = make_url(resolve_database_url(client=client))

    assert url.host == "secret-host.rds.example"
    assert url.port == 6543
    assert url.database == "secret_db"


def test_password_with_special_characters_round_trips(rds_config):
    """Regression guard: RDS-generated passwords contain URL delimiters, which
    break a hand-concatenated URL.
    """
    client = _client_for({"username": "admin", "password": PASSWORD})

    url = make_url(resolve_database_url(client=client))

    assert url.password == PASSWORD
    assert url.host == "env-host.rds.example"


def test_aws_failure_names_secret_without_leaking_password(rds_config):
    with pytest.raises(RuntimeError, match=SECRET_ID) as excinfo:
        resolve_database_url(client=FailingSecretsManagerClient())

    assert PASSWORD not in str(excinfo.value)


def test_secret_missing_password_raises(rds_config):
    client = _client_for({"username": "admin"})

    with pytest.raises(RuntimeError, match="missing 'username' or 'password'"):
        resolve_database_url(client=client)


def test_non_json_secret_raises_without_echoing_it(rds_config):
    client = FakeSecretsManagerClient(f"not-json {PASSWORD}")

    with pytest.raises(RuntimeError, match="not a JSON SecretString") as excinfo:
        resolve_database_url(client=client)

    assert PASSWORD not in str(excinfo.value)
    assert excinfo.value.__cause__ is None


def test_missing_host_raises(rds_config, monkeypatch):
    monkeypatch.setattr(config, "DB_HOST", None)
    client = _client_for({"username": "admin", "password": PASSWORD})

    with pytest.raises(RuntimeError, match="RAG_DB_HOST"):
        resolve_database_url(client=client)
