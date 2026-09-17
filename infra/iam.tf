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

resource "aws_iam_role" "task" {
  name               = "${var.project}-ecs-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

# Everything the application is allowed to do, and nothing more: read its own
# database credentials, and read the documents bucket for --from-s3 ingestion.
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
      "arn:aws:s3:::${var.documents_bucket}",
      "arn:aws:s3:::${var.documents_bucket}/*",
    ]
  }
}

resource "aws_iam_role_policy" "task" {
  name   = "${var.project}-task"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}
