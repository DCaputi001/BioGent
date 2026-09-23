# s3.tf
# CORS on the documents bucket, so a researcher's browser can post a file
# straight to S3 with a presigned POST.
#
# The bucket itself is NOT managed here -- it predates this Terraform and is
# referenced only as var.documents_bucket, the same as the RDS instance and its
# secret. This resource attaches one piece of configuration to it rather than
# adopting it.
#
# Note this REPLACES any CORS rules the bucket already had: an S3 bucket has
# exactly one CORS configuration, so Terraform owns all of it or none of it.
# The bucket had none before this.

resource "aws_s3_bucket_cors_configuration" "documents" {
  bucket = var.documents_bucket

  cors_rule {
    # POST, not PUT: only a presigned POST carries a policy, which is what lets
    # S3 itself enforce the upload size limit instead of trusting the client.
    allowed_methods = ["POST"]

    # Every origin the app is served from -- the cloudfront.net URL, any custom
    # domain, and the Vite dev server. Not "*": these are authenticated uploads
    # into a researcher's own prefix, and there is no reason for another site to
    # be able to drive one from a browser that happens to hold a valid
    # presigned form.
    #
    # Bare origins only, unlike the Cognito redirect list that shares these
    # locals: a browser's Origin header is scheme-host-port by definition and
    # never carries a trailing slash, so the extra forms Cognito needs would be
    # dead entries here. An origin missing from this list fails at the preflight
    # -- the upload never starts, and the document is left waiting on bytes that
    # never arrive.
    allowed_origins = concat(
      [local.app_origin],
      local.custom_domain_origins,
      var.cognito_local_dev_urls,
    )

    allowed_headers = ["*"]

    # The browser reads nothing back from the upload response beyond status,
    # but ETag is what a future resumable or multipart upload would need.
    expose_headers  = ["ETag"]
    max_age_seconds = 3000
  }
}
