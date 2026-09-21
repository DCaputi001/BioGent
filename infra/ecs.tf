# ecs.tf
# The RAG service itself: an ECR repository, a Fargate task definition, and the
# service keeping it running behind the load balancer.

resource "aws_ecr_repository" "rag" {
  name                 = "${var.project}-rag"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

# Images are tagged with the commit SHA, so old ones accumulate forever without
# this. Keeps the last 10 for rollback and expires anything untagged.
resource "aws_ecr_lifecycle_policy" "rag" {
  repository = aws_ecr_repository.rag.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep the last 10 images"
        selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 10 }
        action       = { type = "expire" }
      },
    ]
  })
}

resource "aws_cloudwatch_log_group" "rag" {
  name              = "/ecs/${var.project}-rag"
  retention_in_days = var.log_retention_days
}

resource "aws_ecs_cluster" "main" {
  name = "${var.project}-cluster"
}

# Built as a local, not inline, because the LangSmith entries are conditional
# on langsmith_secret_arn being set -- jsonencode() has no "if" of its own, so
# the conditional has to happen in the list before encoding.
locals {
  # Shared by both services: the worker talks to the same database, the same
  # bucket and the same queue. Split out so the two cannot drift -- a worker
  # pointed at a different queue than the API writes to would simply never see
  # any work, with nothing reporting an error.
  shared_container_environment = [
    { name = "RAG_DB_SECRET_ID", value = var.db_secret_arn },
    { name = "RAG_DB_HOST", value = var.db_host },
    { name = "RAG_DB_NAME", value = var.db_name },
    { name = "RAG_S3_BUCKET", value = var.documents_bucket },
    { name = "AWS_REGION", value = var.aws_region },
    { name = "RAG_INGESTION_QUEUE_URL", value = aws_sqs_queue.ingestion.id },
  ]

  rag_container_environment = concat(
    local.shared_container_environment,
    [
      # Identifiers, not credentials: the API uses them to check that a token
      # was issued by this pool for this app client. The SPA client has no
      # secret at all, so neither value belongs in Secrets Manager.
      { name = "RAG_COGNITO_USER_POOL_ID", value = aws_cognito_user_pool.main.id },
      { name = "RAG_COGNITO_CLIENT_ID", value = aws_cognito_user_pool_client.web.id },
      { name = "RAG_MAX_UPLOAD_BYTES", value = tostring(var.max_upload_bytes) },
    ],
    var.langsmith_secret_arn != "" ? [
      { name = "LANGSMITH_TRACING", value = "true" },
      # Matches services/rag/.env.example's local dev default of
      # "biogent-rag-dev" minus the "-dev" suffix, so production and local
      # tracing share one base project name in the LangSmith dashboard rather
      # than reading as two unrelated apps.
      { name = "LANGSMITH_PROJECT", value = "${var.project}-rag" },
    ] : []
  )

  # The worker traces too: its chain calls are the ingestion half of the same
  # pipeline, and a LangSmith project missing them would show retrieval quality
  # with no view of what was indexed.
  worker_container_environment = concat(
    local.shared_container_environment,
    var.langsmith_secret_arn != "" ? [
      { name = "LANGSMITH_TRACING", value = "true" },
      { name = "LANGSMITH_PROJECT", value = "${var.project}-rag" },
    ] : []
  )

  rag_container_secrets = var.langsmith_secret_arn != "" ? [
    { name = "LANGSMITH_API_KEY", valueFrom = var.langsmith_secret_arn },
  ] : []
}

resource "aws_ecs_task_definition" "rag" {
  family                   = "${var.project}-rag"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name = "rag"
      # :bootstrap for the very first apply; after that the deploy workflow
      # registers new revisions pinned to a commit SHA. ignore_changes below
      # stops Terraform from reverting the image a deploy just rolled out.
      image     = "${aws_ecr_repository.rag.repository_url}:bootstrap"
      essential = true

      portMappings = [{ containerPort = 8000, protocol = "tcp" }]

      # No password here by design: the app fetches it from Secrets Manager at
      # runtime using the task role. See services/rag/app/db_credentials.py.
      environment = local.rag_container_environment

      # LANGSMITH_API_KEY only, when langsmith_secret_arn is set. Resolved by
      # ECS itself using the execution role before the container starts (see
      # iam.tf) -- unlike RAG_DB_SECRET_ID above, no application code fetches
      # this one; it just needs to already be an environment variable.
      secrets = local.rag_container_secrets

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.rag.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "rag"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "rag" {
  name            = "${var.project}-rag"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.rag.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets         = data.aws_subnets.default.ids
    security_groups = [aws_security_group.tasks.id]
    # Required without a NAT gateway: the task needs a route to ECR and to the
    # Anthropic API. The security group is what keeps it private.
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.rag.arn
    container_name   = "rag"
    container_port   = 8000
  }

  # The image pull plus model load takes a while; without this grace period the
  # health check can kill a task that was still starting up.
  health_check_grace_period_seconds = 180

  lifecycle {
    # The deploy workflow owns which image is running. Without this, the next
    # `terraform apply` would roll production back to :bootstrap.
    ignore_changes = [task_definition]
  }

  depends_on = [aws_lb_listener.http]
}
