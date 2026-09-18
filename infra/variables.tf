# variables.tf
# Inputs for the Phase 5 infrastructure. Nothing secret belongs here: the
# database password lives only in Secrets Manager, and the researcher's
# Anthropic key arrives per request from the browser.

variable "aws_region" {
  description = "Region for all resources. Must match the existing RDS instance and documents bucket."
  type        = string
  default     = "us-east-1"
}

variable "aws_profile" {
  description = "Local AWS CLI profile used to provision. Deliberately not the everyday 'biogent' profile, which is scoped to S3 and Secrets Manager only."
  type        = string
  default     = "biogent-admin"
}

variable "project" {
  description = "Name prefix for created resources."
  type        = string
  default     = "biogent"
}

# --- Existing resources this build attaches to (created outside Terraform) ---

variable "db_secret_arn" {
  description = "ARN of the RDS-managed Secrets Manager secret. The task role is granted GetSecretValue on this ARN alone."
  type        = string
}

variable "db_host" {
  description = "RDS endpoint hostname."
  type        = string
}

variable "db_name" {
  description = "Database name inside the RDS instance."
  type        = string
  default     = "biogent_rag"
}

variable "rds_security_group_id" {
  description = "Security group attached to the RDS instance. An ingress rule is added allowing Postgres from the ECS tasks."
  type        = string
}

variable "documents_bucket" {
  description = "S3 bucket holding source documents, read by `app.ingest --from-s3`."
  type        = string
}

variable "langsmith_secret_arn" {
  description = <<-EOT
    ARN of a Secrets Manager secret holding the LangSmith API key as a plain
    string. Unlike db_secret_arn, this key is not parsed by application code:
    it is resolved into LANGSMITH_API_KEY by ECS itself before the container
    starts, using the execution role, so no Python code needs to know Secrets
    Manager exists for this value.

    Create it with:
      aws secretsmanager create-secret --name biogent/langsmith-api-key \
        --secret-string "lsv2_..." --profile biogent-admin

    Optional: leave unset (empty string) to deploy with tracing disabled.
  EOT
  type        = string
  default     = ""
}

# --- Service sizing ---

variable "task_cpu" {
  description = "Fargate vCPU units. 1024 = 1 vCPU."
  type        = number
  default     = 1024
}

variable "task_memory" {
  description = "Fargate memory (MiB). PyTorch plus the embedding model does not sit comfortably in 2GB."
  type        = number
  default     = 4096
}

variable "desired_count" {
  description = "Running tasks. Set to 0 between sessions to stop paying for Fargate; the ALB bills regardless."
  type        = number
  default     = 1
}

variable "log_retention_days" {
  description = "CloudWatch retention. Logs are the only record of a failed request, but keeping them forever costs money for no benefit."
  type        = number
  default     = 14
}

# --- CI ---

variable "github_repo" {
  description = "owner/repo allowed to assume the deploy role via OIDC."
  type        = string
  default     = "DCaputi001/BioGent"
}

variable "github_repo_immutable" {
  description = <<-EOT
    The same repository in GitHub's immutable OIDC subject format,
    "owner@<owner_id>/repo@<repo_id>". GitHub now issues tokens whose subject
    embeds the numeric ids so the identity survives a rename, and a trust
    policy matching only the human-readable name is rejected with
    "Not authorized to perform sts:AssumeRoleWithWebIdentity".

    Find the ids in the CloudTrail AssumeRoleWithWebIdentity event, or via
    `gh api repos/OWNER/REPO --jq '{owner: .owner.id, repo: .id}'`.
  EOT
  type        = string
  default     = "DCaputi001@173270718/BioGent@1359512510"
}

variable "create_github_oidc_provider" {
  description = "Create the GitHub OIDC provider, or reference one already in this account. AWS permits only one per URL, so set this false if another workload created it."
  type        = bool
  default     = true
}
