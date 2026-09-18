# network.tf
# Networking for the RAG service: the default VPC, plus the two security groups
# that decide who may talk to what.
#
# WHY THE DEFAULT VPC: building a VPC would mean private subnets, which would
# mean a NAT gateway (~$32/month) purely so tasks can reach ECR, Secrets
# Manager and the Anthropic API. Public subnets with tightly scoped security
# groups get the same isolation for this workload at no extra cost. Revisit if
# Phase 8 brings data that should never touch a public subnet.

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# CloudFront's published origin-facing IP ranges, maintained by AWS. Used below
# so the load balancer answers CloudFront and nothing else.
data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

resource "aws_security_group" "alb" {
  name        = "${var.project}-alb"
  description = "Public entry point, reachable only from CloudFront"
  vpc_id      = data.aws_vpc.default.id

  tags = { Name = "${var.project}-alb" }
}

resource "aws_vpc_security_group_ingress_rule" "alb_from_cloudfront" {
  security_group_id = aws_security_group.alb.id
  description       = "HTTP from CloudFront edge locations only"
  from_port         = 80
  to_port           = 80
  ip_protocol       = "tcp"
  prefix_list_id    = data.aws_ec2_managed_prefix_list.cloudfront.id
}

resource "aws_vpc_security_group_egress_rule" "alb_all" {
  security_group_id = aws_security_group.alb.id
  description       = "To the tasks"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_security_group" "tasks" {
  name        = "${var.project}-tasks"
  description = "RAG service tasks"
  vpc_id      = data.aws_vpc.default.id

  tags = { Name = "${var.project}-tasks" }
}

# The tasks hold a public IP (needed to pull images and reach Anthropic without
# a NAT gateway) but accept traffic from the load balancer alone.
resource "aws_vpc_security_group_ingress_rule" "tasks_from_alb" {
  security_group_id            = aws_security_group.tasks.id
  description                  = "App port, from the ALB only"
  from_port                    = 8000
  to_port                      = 8000
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.alb.id
}

resource "aws_vpc_security_group_egress_rule" "tasks_all" {
  security_group_id = aws_security_group.tasks.id
  description       = "Outbound: ECR, Secrets Manager, RDS, Anthropic"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

# Lets the tasks reach Postgres. Added to the EXISTING RDS security group,
# which is why that group's id is an input rather than something created here.
resource "aws_vpc_security_group_ingress_rule" "rds_from_tasks" {
  security_group_id            = var.rds_security_group_id
  description                  = "Postgres from the RAG tasks"
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.tasks.id
}
