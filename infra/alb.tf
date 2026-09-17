# alb.tf
# Load balancer in front of the ECS tasks.
#
# It speaks plain HTTP and holds no certificate: CloudFront terminates TLS for
# the researcher and is the only thing allowed to reach this. Two independent
# controls enforce that, because either one alone is weak -- the security group
# restricts by IP range (see network.tf), and the listener below demands a
# shared secret header that only CloudFront sends. Without the header check,
# anything inside those published CloudFront ranges could reach the API
# directly, bypassing the distribution.

resource "aws_lb" "main" {
  name               = "${var.project}-alb"
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = data.aws_subnets.default.ids

  # Docling parsing and a Claude round trip both take real time; the 60s
  # default would cut off a slow answer mid-flight.
  idle_timeout = 120
}

resource "aws_lb_target_group" "rag" {
  name        = "${var.project}-rag"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = data.aws_vpc.default.id
  target_type = "ip"

  health_check {
    path = "/api/health"
    # /api/health deliberately touches neither RDS nor Secrets Manager, so a
    # database outage does not also make ECS kill every healthy task.
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    matcher             = "200"
  }

  # Give a shutting-down task time to finish an in-flight answer.
  deregistration_delay = 30
}

# The shared secret proving a request came through CloudFront. Generated here
# and stored in state, never committed; rotate by tainting this resource.
resource "random_password" "origin_secret" {
  length  = 48
  special = false
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  # Default: refuse. Only requests matching the rule below get through.
  default_action {
    type = "fixed-response"

    fixed_response {
      content_type = "application/json"
      # Same error shape the API itself uses, so a caller that somehow reaches
      # the ALB directly still gets something parseable rather than HTML.
      message_body = jsonencode({
        error = {
          code      = "forbidden"
          message   = "This service is reachable only through its public endpoint."
          retryable = false
        }
      })
      status_code = "403"
    }
  }
}

resource "aws_lb_listener_rule" "from_cloudfront" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 100

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.rag.arn
  }

  condition {
    http_header {
      http_header_name = "X-Origin-Secret"
      values           = [random_password.origin_secret.result]
    }
  }
}
