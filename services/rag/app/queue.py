"""The ingestion work queue: SQS, wrapped thinly.

The API enqueues a document id after an upload completes; the worker consumes.
Nothing else goes through here.

The message body is only the document id, deliberately. Everything else about a
document lives in the `documents` table, and a message carrying its own copy of
the filename or the S3 key would be a second source of truth that goes stale
the moment a row is corrected -- or, worse, lets a caller assert facts about a
document the queue never checked against the table.
"""

import json
import logging

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app import config

logger = logging.getLogger(__name__)


def _client(client=None):
    return client or boto3.client("sqs", region_name=config.AWS_REGION)


def _require_queue_url(queue_url: str | None) -> str:
    if not queue_url:
        raise RuntimeError(
            "RAG_INGESTION_QUEUE_URL is not set, so uploads cannot be queued for "
            "processing. Set it in services/rag/.env (terraform output ingestion_queue_url)."
        )
    return queue_url


def enqueue(document_id, queue_url: str | None = None, client=None) -> str:
    """Queue one document for ingestion. Returns the SQS message id."""
    queue_url = _require_queue_url(queue_url or config.INGESTION_QUEUE_URL)

    try:
        response = _client(client).send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({"document_id": str(document_id)}),
        )
    except (ClientError, BotoCoreError) as exc:
        raise RuntimeError(
            f"Could not queue document {document_id} for processing. "
            f"{config.AWS_CREDENTIALS_HINT}"
        ) from exc

    return response["MessageId"]


def receive(queue_url: str | None = None, client=None, wait_seconds: int | None = None) -> list:
    """Long-poll for work.

    MaxNumberOfMessages is 1 on purpose: one document occupies a worker for
    minutes, so claiming a batch would hold messages invisible behind work that
    has not started, and they would time out and be redelivered.
    """
    queue_url = _require_queue_url(queue_url or config.INGESTION_QUEUE_URL)
    wait = config.WORKER_POLL_SECONDS if wait_seconds is None else wait_seconds

    response = _client(client).receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=1,
        WaitTimeSeconds=wait,
    )
    return response.get("Messages", [])


def delete(receipt_handle: str, queue_url: str | None = None, client=None) -> None:
    """Acknowledge a message, so it is not redelivered.

    Called only after the work is recorded in the database. Deleting earlier
    would lose the document on a crash; deleting later is merely a retry.
    """
    queue_url = _require_queue_url(queue_url or config.INGESTION_QUEUE_URL)
    _client(client).delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)


def parse_document_id(message: dict) -> str | None:
    """Pull the document id out of a message body.

    Returns None for anything unreadable rather than raising: a malformed
    message must not be able to stop the worker, and it will fall through to
    the dead-letter queue on its own after the redrive policy's retries.
    """
    try:
        body = json.loads(message.get("Body", ""))
    except (TypeError, ValueError):
        logger.warning("Discarding a queue message whose body is not JSON")
        return None

    document_id = body.get("document_id") if isinstance(body, dict) else None
    if not document_id:
        logger.warning("Discarding a queue message with no document_id")
        return None

    return document_id
