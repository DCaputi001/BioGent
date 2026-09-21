# worker.tf
# The background ingestion worker (Phase 8): a second Fargate service that
# drains the SQS queue, parses uploaded documents and embeds them.
#
# It runs THE SAME IMAGE as the API, with a different command. The Dockerfile
# declares no ENTRYPOINT precisely so this works. ARCHITECTURE.md's
# containerization section anticipated a separate Dockerfile per service, but
# this worker runs the same app.ingest code against the same models, and that
# image already bakes in Docling, CPU torch and the embedding weights -- a
# second image would be a near-identical 3.8GB build, doubling CI time and ECR
# storage to ship the same bytes.

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/${var.project}-worker"
  retention_in_days = var.log_retention_days
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${var.project}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.worker_cpu
  memory                   = var.worker_memory
  execution_role_arn       = aws_iam_role.execution.arn
  # Not the API's task role: the worker consumes the queue the API only writes
  # to, and reads objects the API only signs for. See iam.tf.
  task_role_arn = aws_iam_role.worker_task.arn

  container_definitions = jsonencode([
    {
      name = "worker"
      # Same repository and the same :bootstrap convention as the API; the
      # deploy workflow replaces the tag with a commit SHA.
      image     = "${aws_ecr_repository.rag.repository_url}:bootstrap"
      essential = true

      # The only difference from the API's definition. uvicorn is the image's
      # default command; this replaces it with the queue consumer.
      command = ["python", "-m", "app.worker"]

      # No portMappings: nothing connects to a worker. It reaches out to SQS,
      # S3 and RDS and listens for nothing, which is also why there is no
      # target group or health check below.
      environment = local.worker_container_environment
      secrets     = local.rag_container_secrets

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.worker.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "worker"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "worker" {
  name            = "${var.project}-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = var.worker_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets = data.aws_subnets.default.ids
    # Reuses the API's security group, which carries the rds_from_tasks rule in
    # network.tf -- that is what gives the worker Postgres access. Its one
    # ingress rule (port 8000 from the ALB) is unused here and unreachable,
    # since nothing routes to a worker. A dedicated group would need its own
    # RDS ingress rule added for no benefit.
    security_groups = [aws_security_group.tasks.id]
    # Required without a NAT gateway: the task needs a route to ECR, S3, SQS
    # and Secrets Manager.
    assign_public_ip = true
  }

  lifecycle {
    # Same reasoning as the API service: the deploy workflow owns which image
    # runs, and without this the next `terraform apply` would roll the worker
    # back to :bootstrap.
    ignore_changes = [task_definition]
  }
}
