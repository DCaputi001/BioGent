"""Unit tests for app.queue, against a fake SQS client.

The message body is the contract between the API and the worker, so these
pin its shape. parse_document_id's tolerance of junk matters most: a message
that cannot be read must not be able to stop the worker.
"""

import json

import pytest

from app import queue

QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/000000000000/biogent-ingestion"


class FakeSQS:
    def __init__(self, messages=None):
        self.sent = []
        self.received = []
        self.deleted = []
        self._messages = messages or []

    def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return {"MessageId": "message-1"}

    def receive_message(self, **kwargs):
        self.received.append(kwargs)
        return {"Messages": self._messages} if self._messages else {}

    def delete_message(self, **kwargs):
        self.deleted.append(kwargs)


def test_enqueue_sends_only_the_document_id():
    """Nothing else belongs in the body.

    A message carrying its own copy of the filename or S3 key would be a second
    source of truth, stale the moment the row is corrected.
    """
    client = FakeSQS()

    queue.enqueue("doc-1", queue_url=QUEUE_URL, client=client)

    assert json.loads(client.sent[0]["MessageBody"]) == {"document_id": "doc-1"}
    assert client.sent[0]["QueueUrl"] == QUEUE_URL


def test_enqueue_without_a_queue_configured_explains_what_to_set():
    with pytest.raises(RuntimeError, match="RAG_INGESTION_QUEUE_URL"):
        queue.enqueue("doc-1", queue_url=None, client=FakeSQS())


def test_receive_claims_one_message_at_a_time():
    """A document occupies a worker for minutes.

    Claiming a batch would hold later messages invisible behind work that has
    not started, until their visibility timeout expired and they were
    redelivered.
    """
    client = FakeSQS(messages=[{"Body": "{}", "ReceiptHandle": "r"}])

    queue.receive(queue_url=QUEUE_URL, client=client, wait_seconds=20)

    assert client.received[0]["MaxNumberOfMessages"] == 1
    assert client.received[0]["WaitTimeSeconds"] == 20


def test_receive_returns_nothing_when_the_queue_is_empty():
    assert queue.receive(queue_url=QUEUE_URL, client=FakeSQS(), wait_seconds=0) == []


def test_delete_acknowledges_by_receipt_handle():
    client = FakeSQS()

    queue.delete("receipt-abc", queue_url=QUEUE_URL, client=client)

    assert client.deleted == [{"QueueUrl": QUEUE_URL, "ReceiptHandle": "receipt-abc"}]


# --- parsing --------------------------------------------------------------


def test_a_well_formed_message_yields_its_document_id():
    message = {"Body": json.dumps({"document_id": "doc-42"})}

    assert queue.parse_document_id(message) == "doc-42"


@pytest.mark.parametrize(
    "body",
    ["not json at all", "", "[]", json.dumps({"something_else": 1}), json.dumps({"document_id": ""})],
)
def test_an_unreadable_message_is_reported_as_none_rather_than_raising(body):
    """A malformed message must not be able to stop the worker.

    Returning None lets the loop acknowledge it and move on; raising here would
    take down the process handling every other researcher's uploads.
    """
    assert queue.parse_document_id({"Body": body}) is None


def test_a_message_with_no_body_at_all_is_handled():
    assert queue.parse_document_id({}) is None
