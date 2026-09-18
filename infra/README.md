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

Unlike the database password, the LangSmith key is not fetched by application
code: ECS resolves it into `LANGSMITH_API_KEY` before the container starts,
using the execution role (see the `secrets` field in `ecs.tf`), because it is
a plain string with no parsing to do. The project name is `biogent-rag`,
matching local dev's default of `biogent-rag-dev` minus the `-dev` suffix --
see `services/rag/.env.example`.

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
