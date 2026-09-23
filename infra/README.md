# infra

Terraform for the BioGent AWS deployment (Phase 5). Creates ECR, ECS Fargate,
an ALB, the frontend S3 bucket, one CloudFront distribution serving both, and
the IAM role GitHub Actions assumes to deploy.

It does **not** create the RDS instance, its Secrets Manager secret, or the
documents bucket — those already exist and are referenced as inputs.

## Shape of it

```
                 researcher
                     |  https
            CloudFront distribution
            /                      \
   default → S3 (SPA)        /api/* → ALB → ECS Fargate task
                                              |        |
                                     Secrets Manager   RDS (pgvector)
```

One distribution for both means no custom domain is needed, TLS is free, and
the app and API share an origin — so **CORS does not apply in production**.
The ALB is reachable only from CloudFront: its security group allows only
CloudFront's IP ranges, and its listener demands a secret header that only the
distribution sends. Hitting the ALB directly returns 403.

## One-time setup

**1. Admin profile.** Provisioning needs more than the everyday `biogent`
profile (S3 and Secrets Manager only). Create an IAM user with
`AdministratorAccess`, then:

```powershell
aws configure --profile biogent-admin
```

**2. State bucket.** Terraform cannot create the bucket its own state lives in.
Versioning matters: it turns a corrupted state file into a restore.

```powershell
$acct = aws sts get-caller-identity --query Account --output text --profile biogent-admin
aws s3api create-bucket --bucket "biogent-tfstate-$acct" --region us-east-1 --profile biogent-admin
aws s3api put-bucket-versioning --bucket "biogent-tfstate-$acct" --versioning-configuration Status=Enabled --profile biogent-admin
aws s3api put-public-access-block --bucket "biogent-tfstate-$acct" --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true --profile biogent-admin
```

If the account id is not `396913715360`, update `bucket` in `versions.tf`.

**3. Variables.**

```powershell
Copy-Item terraform.tfvars.example terraform.tfvars
# then fill in the RDS security group id and confirm the ARNs
```

## First apply, in three steps

The ordering matters: an ECS service cannot start a task until an image exists
in ECR, but ECR is created by Terraform. So:

```powershell
terraform init
terraform apply -target=aws_ecr_repository.rag      # 1. the repository alone

# 2. the bootstrap image
$acct = aws sts get-caller-identity --query Account --output text --profile biogent-admin
$repo = "$acct.dkr.ecr.us-east-1.amazonaws.com/biogent-rag"
aws ecr get-login-password --region us-east-1 --profile biogent-admin | docker login --username AWS --password-stdin $repo
docker build -t "${repo}:bootstrap" ../services/rag
docker push "${repo}:bootstrap"

terraform apply                                      # 3. everything else
```

The first `apply` takes a while — CloudFront distributions are slow to create.

## After it is up

```powershell
terraform output app_url        # the researcher-facing URL
terraform output github_actions_role_arn
```

Set three **repository variables** in GitHub (Settings → Secrets and variables
→ Actions → Variables). None is a secret — they are identifiers, and the role
ARN is useless without the OIDC trust relationship restricting it to this
repository:

| Variable | Value from |
|---|---|
| `AWS_DEPLOY_ROLE` | `terraform output github_actions_role_arn` |
| `FRONTEND_BUCKET` | `terraform output frontend_bucket` |
| `CLOUDFRONT_DISTRIBUTION_ID` | `terraform output cloudfront_distribution_id` |

Also create an **Environment** named `production` (Settings → Environments)
and add yourself as a required reviewer. That is what turns a merge into a
deploy *proposal* rather than an immediate rollout.

From then on the deploy workflow owns what runs. `terraform apply` will not
roll the image back: the service ignores `task_definition` changes for exactly
that reason.

## Verifying

```powershell
curl "$(terraform output -raw app_url)/api/health"                # {"status":"ok"}
curl "http://$(terraform output -raw alb_dns_name)/api/health"    # times out
```

The direct-to-ALB check **times out rather than returning 403**, which is the
stronger outcome: the security group drops the packet before HTTP happens, so
there is no response at all. The listener's 403 is the second line of defense,
reached only by a request that already comes from a CloudFront IP range but
lacks the secret header.

## LangSmith tracing (Phase 6)

Optional and off by default -- `langsmith_secret_arn` defaults to `""`, and a
`terraform plan` with it unset shows no changes at all. To turn tracing on in
production:

```powershell
aws secretsmanager create-secret --name biogent/langsmith-api-key `
  --secret-string "lsv2_..." --profile biogent-admin
```

Set `langsmith_secret_arn` to that secret's ARN in `terraform.tfvars`, then
`terraform apply`. That run only adds one IAM statement to the execution role
and updates the task definition -- nothing destructive.

**The apply alone does not turn tracing on.** The service ignores
`task_definition` changes (the deploy workflow owns which image runs), so the
apply registers a new revision and leaves the running task on the old one. The
next deploy run activates it: the workflow reads the family's *latest* revision,
which is the one Terraform just wrote, swaps in a freshly built image, and
deploys that. Do not shortcut it with `aws ecs update-service --task-definition`
pointed at Terraform's revision -- that revision carries the `:bootstrap` image
and would roll production back to the first build ever pushed.

Unlike the database password, the LangSmith key is not fetched by application
code: ECS resolves it into `LANGSMITH_API_KEY` before the container starts,
using the execution role (see the `secrets` field in `ecs.tf`), because it is
a plain string with no parsing to do. The project name is `biogent-rag`,
matching local dev's default of `biogent-rag-dev` minus the `-dev` suffix --
see `services/rag/.env.example`.

## Cognito sign-in (Phase 8)

`cognito.tf` creates the user pool, a public SPA client and the hosted sign-in
page. Callback and logout URLs are derived from the CloudFront domain
automatically, plus `http://localhost:5173` for local development
(`cognito_local_dev_urls`), so there is nothing to fill in by hand.

After `terraform apply`, three outputs feed the frontend build. Set them as
GitHub **repository variables**, the same way as `FRONTEND_BUCKET` — none is a
secret, and a public SPA client has no client secret at all:

| Variable | Value from |
|---|---|
| `COGNITO_AUTHORITY` | `terraform output cognito_authority` |
| `COGNITO_CLIENT_ID` | `terraform output cognito_client_id` |
| `COGNITO_HOSTED_UI_DOMAIN` | `terraform output cognito_hosted_ui_domain` |

The API gets its two (`RAG_COGNITO_USER_POOL_ID`, `RAG_COGNITO_CLIENT_ID`)
directly from Terraform through the task definition, so they need no manual
step. As with LangSmith, **the apply alone does not put them on the running
task** — the next deploy does.

Create accounts from the hosted sign-up page, or from the CLI:

```powershell
aws cognito-idp admin-create-user --user-pool-id (terraform output -raw cognito_user_pool_id) `
  --username researcher@example.org --profile biogent-admin
```

**`deletion_protection` is ACTIVE on the pool, deliberately.** Every ingested
chunk is stamped with a `sub` issued by this pool; a replacement pool issues
different ones, so destroying it would leave every document owned by an
identity nobody can sign in as. Disable it consciously or not at all.

## Uploads and the ingestion worker (Phase 8)

```
  browser ──presigned POST──> S3 (users/{sub}/documents/)
     │                              │
     └── POST /complete ──> SQS ──> worker (Fargate) ──> RDS (pgvector)
```

The file never passes through the service. That is partly cost, but mostly
necessity: **CloudFront caps a POST/PUT body at 1MB**, a hard service quota, so
routing a real paper through `/api/*` could not work. The upload size limit is
enforced by S3 itself through the presigned POST policy (`max_upload_bytes`),
not by the API — there is no point at which the API could refuse an oversized
file, because it never sees one.

The worker is a **second ECS service running the same image**, started with
`python -m app.worker` instead of uvicorn. One image, two services: no second
build and no second ECR repository. It has no load balancer, no target group
and no health check, because nothing connects to it.

```powershell
terraform output ingestion_queue_url   # set as RAG_INGESTION_QUEUE_URL to run either locally
aws logs tail /ecs/biogent-worker --follow --profile biogent-admin
```

To pause ingestion without touching the API:

```powershell
terraform apply -var worker_desired_count=0
```

Uploads then queue up and sit at "processing" until a worker returns — visible
to the researcher rather than silently lost. Raising the count above 1 is safe:
deterministic chunk ids mean two workers on the same document overwrite rather
than duplicate.

**The documents bucket's CORS is now managed here** (`s3.tf`), though the bucket
itself still is not. A bucket has exactly one CORS configuration, so Terraform
owns all of it or none of it; it had none before this.

## Schema migrations (Phase 8)

This project's own tables are managed by Alembic from `services/rag`. The
`langchain_pg_*` tables are not — langchain-postgres creates and owns those,
and `alembic/env.py` filters them out of autogenerate.

```powershell
cd services/rag
uv run alembic upgrade head
uv run alembic current        # what is applied now
uv run alembic history        # what exists
```

The connection comes from `db_credentials.get_database_url()`, the same
Secrets Manager path the service uses, so there is no URL in `alembic.ini` to
keep in sync or to leak.

**Migrations are an operator step, run from a workstation — not part of the
deploy.** `alembic/` is deliberately not in the container image
(`.dockerignore`), and the workflow does not call it. Automating it would mean
a deploy that can roll back to a previous image while the schema only moves
forward, which needs its own thinking about backward-compatible migrations.
Until then: apply the migration, confirm it, then deploy.

Reaching RDS from a workstation needs your IP on the RDS security group, the
same rule that lets `app.ingest` run locally.

## Custom domain

`biogent.io` and `www.biogent.io` were set up directly in the AWS console
(CloudFront aliases, a validated ACM certificate, and the two Cognito
callback/logout URLs) before this was brought into Terraform, so bringing it
in meant reconciling state to already-live reality rather than provisioning
something new.

Both `custom_domain_names` and `acm_certificate_arn` default to empty, so a
fresh clone of this repo deploys with only the `*.cloudfront.net` URL and
inherits nothing about this domain. To point a fresh deployment at a domain
you own instead:

1. Request and validate an ACM certificate **in us-east-1** for it — CloudFront
   reads certificates from nowhere else, regardless of which region the rest
   of the stack runs in.
2. Set `custom_domain_names` and `acm_certificate_arn` in `terraform.tfvars`.
3. If the domain's DNS is a Route 53 hosted zone in this account,
   `infra/route53.tf` manages its alias records — but only as a `data` source
   plus the specific records this app owns, never the zone itself, since
   destroying that would take the domain's nameserver delegation with it. A
   zone Route 53 Registrar created automatically (buying the domain through
   AWS) already has one; point `data.aws_route53_zone.biogent`'s `name` at it.
4. `terraform apply`.

If the DNS records already exist (as `biogent.io`'s did, from the console
setup), `apply` alone tries to *create* them and fails on Route 53's "already
exists" error. Import them first — once per record, using the format
`ZONEID_recordname_TYPE`:

```powershell
terraform import 'aws_route53_record.apex["biogent.io"]' Z0713174912H8BTJHQUB_biogent.io_A
terraform import 'aws_route53_record.apex_ipv6["biogent.io"]' Z0713174912H8BTJHQUB_biogent.io_AAAA
terraform import 'aws_route53_record.apex["www.biogent.io"]' Z0713174912H8BTJHQUB_www.biogent.io_A
terraform import 'aws_route53_record.apex_ipv6["www.biogent.io"]' Z0713174912H8BTJHQUB_www.biogent.io_AAAA
```

A `terraform plan` showing changes to these records right after import means
the alias block doesn't match what is actually live — worth a second look
before applying, not just clicking through it.

## Cost

Roughly **$50-60/month** on top of RDS: ALB ~$17, Fargate (1 vCPU / 4 GB,
always on) ~$36, CloudFront and ECR a few dollars. To pause between sessions:

```powershell
terraform apply -var desired_count=0
```

That stops the Fargate charge. The ALB bills regardless; destroying everything
is `terraform destroy`, which leaves RDS, the documents bucket and the secret
untouched since Terraform does not manage them.

## Gotchas

- **`image_tag_mutability = "IMMUTABLE"`** on the ECR repository: a tag cannot
  be overwritten, so `:bootstrap` can be pushed only once. Deploys use commit
  SHAs, so this only matters if you try to re-push the bootstrap tag.
- **The origin secret** lives in Terraform state, never in git. Rotate with
  `terraform taint random_password.origin_secret && terraform apply`, which
  updates both the distribution and the listener rule in one pass.
- **`create_github_oidc_provider`**: AWS allows one provider per URL per
  account. Set it to `false` if something else already created it.
