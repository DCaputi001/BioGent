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

# --- Authentication (Phase 8) ---

variable "cognito_local_dev_urls" {
  description = <<-EOT
    Extra sign-in redirect targets for local development, on top of the
    CloudFront URL, which is added automatically. Vite's dev server by default.

    Set this to [] for a deployment that should not accept a localhost
    redirect. It is not a security hole on its own -- an attacker cannot make
    someone else's browser hand them a code issued to localhost -- but it is
    also not needed in an environment nobody develops against.
  EOT
  type        = list(string)
  default     = ["http://localhost:5173"]
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

# --- Ingestion worker (Phase 8) ---

variable "worker_cpu" {
  description = "Fargate vCPU units for the ingestion worker. Docling parsing is CPU-bound, so this is what decides how long an upload takes."
  type        = number
  default     = 1024
}

variable "worker_memory" {
  description = "Fargate memory (MiB) for the ingestion worker. Matches the API: it loads the same embedding model and PyTorch."
  type        = number
  default     = 4096
}

variable "worker_desired_count" {
  description = <<-EOT
    Running ingestion workers. One is enough for a handful of researchers --
    documents queue up rather than being lost.

    Set to 0 between sessions to stop paying for it; uploads then sit at
    "processing" until a worker returns, which is visible to the researcher
    rather than silent. Raising it above 1 is safe: deterministic chunk ids
    mean two workers on the same document overwrite rather than duplicate.
  EOT
  type        = number
  default     = 1
}

variable "max_upload_bytes" {
  description = "Largest file a researcher may upload. Enforced by S3 itself through the presigned POST policy, not by the API."
  type        = number
  default     = 52428800 # 50 MB
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

# --- Custom domain (optional) ---

variable "custom_domain_names" {
  description = <<-EOT
    Alternate domain names for the CloudFront distribution, e.g.
    ["biogent.io", "www.biogent.io"]. Requires acm_certificate_arn too --
    CloudFront cannot serve a custom domain on its own default certificate.

    Leave both this and acm_certificate_arn empty to serve only the
    *.cloudfront.net URL, which is also what a fresh deployment gets: neither
    has a real default, since nobody else owns this domain.
  EOT
  type        = list(string)
  default     = []
}

variable "acm_certificate_arn" {
  description = <<-EOT
    ACM certificate for custom_domain_names, issued in us-east-1 specifically
    -- CloudFront only reads certificates from that region regardless of
    where the rest of the stack runs. Must already be validated (DNS
    validation adds a CNAME to the zone) before this is set, or the apply
    hangs waiting on a certificate that never issues.
  EOT
  type        = string
  default     = ""
}

variable "create_github_oidc_provider" {
  description = "Create the GitHub OIDC provider, or reference one already in this account. AWS permits only one per URL, so set this false if another workload created it."
  type        = bool
  default     = true
}
