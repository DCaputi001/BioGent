# outputs.tf
# Values needed to deploy, to configure CI, and to check the thing works.
# The origin secret is intentionally absent: it lives in state, not in output.

output "app_url" {
  description = "The researcher-facing URL. Serves the app, and the API under /api."
  value       = "https://${aws_cloudfront_distribution.main.domain_name}"
}

output "ecr_repository_url" {
  description = "Push target for the RAG image."
  value       = aws_ecr_repository.rag.repository_url
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "ecs_service_name" {
  value = aws_ecs_service.rag.name
}

output "task_definition_family" {
  value = aws_ecs_task_definition.rag.family
}

output "frontend_bucket" {
  description = "Sync the built SPA here."
  value       = aws_s3_bucket.frontend.id
}

output "cloudfront_distribution_id" {
  description = "Needed to invalidate the cache after a frontend deploy."
  value       = aws_cloudfront_distribution.main.id
}

output "github_actions_role_arn" {
  description = "Set as the AWS_DEPLOY_ROLE variable in the GitHub repository. Not a secret."
  value       = aws_iam_role.github_actions.arn
}

output "ingestion_queue_url" {
  description = "Set as RAG_INGESTION_QUEUE_URL to run the API or worker locally against the real queue."
  value       = aws_sqs_queue.ingestion.id
}

output "worker_service_name" {
  value = aws_ecs_service.worker.name
}

output "worker_task_family" {
  value = aws_ecs_task_definition.worker.family
}

output "cognito_user_pool_id" {
  description = "Set as RAG_COGNITO_USER_POOL_ID for the API. Not a secret."
  value       = aws_cognito_user_pool.main.id
}

output "cognito_client_id" {
  description = "Set as VITE_COGNITO_CLIENT_ID and RAG_COGNITO_CLIENT_ID. A public SPA client id, not a secret."
  value       = aws_cognito_user_pool_client.web.id
}

output "cognito_authority" {
  description = "OIDC issuer the frontend discovers sign-in endpoints from. Set as VITE_COGNITO_AUTHORITY."
  value       = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.main.id}"
}

output "cognito_hosted_ui_domain" {
  description = "The hosted sign-in page's domain. Needed for sign-OUT, which is not part of OIDC discovery."
  value       = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${var.aws_region}.amazoncognito.com"
}

output "alb_dns_name" {
  description = "For verification only: hitting this directly should return 403."
  value       = aws_lb.main.dns_name
}
