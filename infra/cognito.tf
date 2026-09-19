# cognito.tf
# User accounts for the researcher-facing app (Phase 8). A user pool, a public
# SPA client, and the AWS-hosted sign-in page the frontend redirects to.
#
# The pool's `sub` for each user becomes the owner id stamped onto every chunk
# that user ingests, and the value every retrieval filters by -- so this pool
# is not just a login, it is the identity the stored data is keyed on.

locals {
  app_origin = "https://${aws_cloudfront_distribution.main.domain_name}"

  # Both the bare origin and the trailing-slash form. Cognito matches a
  # redirect_uri exactly, and whether a SPA's origin carries a trailing slash
  # depends on how the client derives it -- allowing both turns a silent
  # "redirect_mismatch" error page into a non-issue.
  cognito_redirect_urls = concat(
    [local.app_origin, "${local.app_origin}/"],
    var.cognito_local_dev_urls,
  )
}

resource "aws_cognito_user_pool" "main" {
  name = "${var.project}-users"

  # Researchers sign in with the email they already know, rather than inventing
  # a username they will forget.
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_numbers                  = true
    require_uppercase                = true
    require_symbols                  = false
    temporary_password_validity_days = 7
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  # Cognito's own email sender, which is capped near 50 messages a day. Fine for
  # the two test accounts Phase 8's checkpoint calls for; a real launch needs SES
  # configured here instead.
  email_configuration {
    email_sending_account = "COGNITO_DEFAULT"
  }

  # Destroying this pool would orphan every document already ingested: the
  # user_id in chunk metadata is a sub issued by THIS pool, and a replacement
  # pool issues different ones. The chunks would survive with no reachable owner.
  deletion_protection = "ACTIVE"
}

resource "aws_cognito_user_pool_client" "web" {
  name         = "${var.project}-web"
  user_pool_id = aws_cognito_user_pool.main.id

  # No client secret, deliberately: a single-page app ships its whole bundle to
  # the browser and cannot keep one. Authorization-code flow with PKCE is what
  # makes a public client safe, and the SDK adds PKCE automatically.
  generate_secret = false

  allowed_oauth_flows                  = ["code"]
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]

  callback_urls = local.cognito_redirect_urls
  logout_urls   = local.cognito_redirect_urls

  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    # Without this the session ends when the access token expires an hour in,
    # interrupting a researcher mid-question rather than renewing quietly.
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  access_token_validity  = 60
  id_token_validity      = 60
  refresh_token_validity = 30

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }

  # Cognito otherwise answers "no such user" differently from "wrong password",
  # which lets anyone test whether a given researcher has an account here.
  prevent_user_existence_errors = "ENABLED"
}

resource "aws_cognito_user_pool_domain" "main" {
  # Cognito domain prefixes share one global namespace, so the account id is
  # what keeps this from colliding with an unrelated AWS customer's pool.
  domain       = "${var.project}-${data.aws_caller_identity.current.account_id}"
  user_pool_id = aws_cognito_user_pool.main.id
}
