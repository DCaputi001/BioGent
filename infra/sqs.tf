# sqs.tf
# The ingestion work queue (Phase 8). The API enqueues a document id after an
# upload completes; the worker service in worker.tf consumes it.
#
# A queue exists here because parsing with Docling and embedding the result
# takes minutes -- far longer than a browser request can wait, and far longer
# than an ALB would hold the connection open (ARCHITECTURE.md, "Pipeline
# execution").

resource "aws_sqs_queue" "ingestion_dlq" {
  name = "${var.project}-ingestion-dlq"

  # Long enough to notice and investigate a batch of failures. A message only
  # lands here after the main queue gave up on it, so it is evidence.
  message_retention_seconds = 1209600 # 14 days
}

resource "aws_sqs_queue" "ingestion" {
  name = "${var.project}-ingestion"

  # Must exceed the longest realistic processing time. A timeout shorter than
  # the work makes the message visible again while a worker is still on it, so
  # a second worker picks up the same document and ingests it concurrently.
  # Deterministic chunk ids make that survivable rather than duplicating, but
  # it still burns an embedding run for nothing.
  visibility_timeout_seconds = 900

  # Long polling. Without it an idle worker bills for a spin loop returning
  # nothing; 20 is the maximum SQS allows.
  receive_wait_time_seconds = 20

  message_retention_seconds = 345600 # 4 days

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.ingestion_dlq.arn
    # Three attempts, not one: a transient S3 or database blip should be
    # retried. A document that fails three times has a real problem, and its
    # row already records why -- the worker writes the reason before the
    # message is retried at all.
    maxReceiveCount = 3
  })
}

# Standard queues, not FIFO, deliberately. Ordering between two researchers'
# uploads is meaningless, and FIFO's per-group serialization would make one
# slow document block every later upload from the same researcher.
