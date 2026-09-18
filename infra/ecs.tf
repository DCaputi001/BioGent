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
      environment = [
        { name = "RAG_DB_SECRET_ID", value = var.db_secret_arn },
        { name = "RAG_DB_HOST", value = var.db_host },
        { name = "RAG_DB_NAME", value = var.db_name },
        { name = "RAG_S3_BUCKET", value = var.documents_bucket },
        { name = "AWS_REGION", value = var.aws_region },
      ]

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
