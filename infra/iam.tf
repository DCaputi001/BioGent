# iam.tf
# Two roles for the running service, kept separate on purpose:
#
#   execution role - used by the ECS agent BEFORE the container starts, to pull
#                    the image and create log streams.
#   task role      - used by the application code itself, at runtime.
#
# Merging them would hand the application the platform's image-pull rights for
# no reason. Splitting them means a bug in the app cannot touch ECR.

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${var.project}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Lets ECS resolve LANGSMITH_API_KEY from Secrets Manager into a plain
# environment variable before the container starts (the "secrets" field on
# the container definition, in ecs.tf). This belongs on the EXECUTION role,
# not the task role: the execution role is what the ECS agent already uses to
# pull the image and write logs, before the application itself runs. This is
# deliberately a different mechanism from the database password, which
# app/db_credentials.py fetches itself at runtime using the task role --
# a plain API key string needs no such parsing, so ECS's native resolution is
# simpler and needs no application code.
#
# count rather than an unconditional statement: langsmith_secret_arn defaults
# to "", and an IAM policy resource cannot reference an empty resource ARN.
# `terraform apply` with tracing not yet configured must still succeed.
resource "aws_iam_role_policy" "execution_langsmith_secret" {
  count = var.langsmith_secret_arn != "" ? 1 : 0

  name = "${var.project}-execution-langsmith-secret"
  role = aws_iam_role.execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadLangSmithSecret"
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = var.langsmith_secret_arn
      },
    ]
  })
}

resource "aws_iam_role" "task" {
  name               = "${var.project}-ecs-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

# Researcher uploads live under one prefix per user. Both roles below are
# scoped to it rather than to the whole bucket, so neither can reach the
# operator's bulk-ingest documents sitting at the bucket root.
locals {
  documents_bucket_arn = "arn:aws:s3:::${var.documents_bucket}"
  user_uploads_arn     = "arn:aws:s3:::${var.documents_bucket}/users/*"
}

# Everything the API is allowed to do, and nothing more: read its own database
# credentials, read the documents bucket for --from-s3 ingestion, write and
# remove a researcher's uploads, and queue them for processing.
data "aws_iam_policy_document" "task" {
  statement {
    sid       = "ReadDatabaseSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.db_secret_arn]
  }

  statement {
    sid     = "ReadSourceDocuments"
    actions = ["s3:GetObject", "s3:ListBucket"]
    resources = [
      local.documents_bucket_arn,
      "${local.documents_bucket_arn}/*",
    ]
  }

  # PutObject is needed to SIGN a presigned upload, not to perform one: the
  # signature grants only what the signer already holds, so a role without this
  # produces URLs that S3 rejects.
  statement {
    sid       = "WriteResearcherUploads"
    actions   = ["s3:PutObject", "s3:DeleteObject"]
    resources = [local.user_uploads_arn]
  }

  # Send only. The API must never consume ingestion work -- that is the
  # worker's job, and a request thread is the wrong place for a job that runs
  # for minutes.
  statement {
    sid       = "QueueIngestionWork"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.ingestion.arn]
  }
}

resource "aws_iam_role_policy" "task" {
  name   = "${var.project}-task"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}

# --- The ingestion worker ----------------------------------------------------
#
# A separate role from the API's, not the same one reused. The two processes
# need opposite halves of the same resources -- the API signs uploads and sends
# messages, the worker reads objects and consumes messages -- and giving both
# the union would let a bug in the request path drain the work queue.

resource "aws_iam_role" "worker_task" {
  name               = "${var.project}-ecs-worker-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

data "aws_iam_policy_document" "worker_task" {
  statement {
    sid       = "ReadDatabaseSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.db_secret_arn]
  }

  statement {
    sid       = "ReadResearcherUploads"
    actions   = ["s3:GetObject"]
    resources = [local.user_uploads_arn]
  }

  # Receive and acknowledge, never send: a worker that could enqueue could
  # requeue its own failures forever without the redrive policy noticing.
  statement {
    sid = "ConsumeIngestionWork"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:ChangeMessageVisibility",
      "sqs:GetQueueAttributes",
    ]
    resources = [aws_sqs_queue.ingestion.arn]
  }
}

resource "aws_iam_role_policy" "worker_task" {
  name   = "${var.project}-worker-task"
  role   = aws_iam_role.worker_task.id
  policy = data.aws_iam_policy_document.worker_task.json
}
