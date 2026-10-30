# Keyless CI/CD Deployment Platform

Python Lambda deployments using Terraform and GitHub Actions OIDC. No AWS access keys belong in GitHub. Repository: https://github.com/EpicCoder71/aws-keyless-cicd

Dev deployment verified successfully: [Actions run](https://github.com/EpicCoder71/aws-keyless-cicd/actions/runs/41009129439). See [verification details](docs/verification.md). Prod is configured but not deployed.

## Architecture

Pull request → pytest + Terraform validation + Checkov. Main → the same checks → GitHub environment → OIDC → environment-specific deployment role → Terraform S3 state → Lambda → invocation smoke test.

The Lambda implements `/` and `/health` HTTP-style events, but has **no public endpoint**. Invoke it with the AWS CLI. This avoids exposing an unauthenticated demo API. Dev and prod have separate functions, runtime roles, deployment roles, and state keys. The deploy roles cannot modify IAM, the state bucket configuration, or the existing OIDC provider.

## Local checks

Use Terraform >=1.10 (native S3 lock support), Python 3.12+, AWS CLI, and GitHub CLI.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
terraform fmt -check -recursive
terraform -chdir=bootstrap init
terraform -chdir=bootstrap validate
terraform -chdir=terraform init -backend=false
terraform -chdir=terraform validate
.venv/bin/python .venv/bin/checkov -d terraform --framework terraform --quiet
```

## Bootstrap once with your local AWS session

Verified intended account: `381491979691`, region `us-east-1`. Always run `aws sts get-caller-identity` before planning. Existing GitHub OIDC provider is read as a data source and remains owned by Cloud Resume.

```sh
terraform -chdir=bootstrap plan -var='account_id=381491979691' -out=bootstrap.tfplan
terraform -chdir=bootstrap apply bootstrap.tfplan
terraform -chdir=bootstrap output
```

Bootstrap state is local and ignored. Back it up securely; losing it makes cleanup and ownership tracking harder. The state bucket has deletion protection and versioning. Bootstrap is privileged; CI cannot apply it.

Create GitHub environments `dev` and `prod`, each with deployment branch policy restricted to `main`. For prod, enable required reviewers where your GitHub plan supports it. Set these environment variables using the bootstrap outputs:

| Variable | Value |
| --- | --- |
| AWS_ACCOUNT_ID | 381491979691 |
| AWS_REGION | us-east-1 |
| TF_STATE_BUCKET | bootstrap state_bucket output |
| AWS_DEPLOY_ROLE_ARN | matching deployment_roles output |

Trust uses the verified immutable subject prefix `repo:EpicCoder71@57415684/aws-keyless-cicd@1439298585` plus `:environment:dev` or `:environment:prod`. Environment branch restrictions are essential because the environment subject itself does not identify a branch.

Push main to deploy dev. Use **Actions → Test and deploy → Run workflow** on main to apply prod. Checkov scans application Terraform; bootstrap requires separate IAM review and is validated for syntax/provider compatibility. Checkov exceptions in application code document deliberate demo cost/scope tradeoffs.

## Teardown

Run the workflow with operation `destroy` and confirmation `destroy-dev` or `destroy-prod`. This removes the chosen Lambda and log group; state and bootstrap roles remain so redeploying works. Destroy both environments before removing bootstrap resources. The shared Cloud Resume OIDC provider is never destroyed here.

To remove the bootstrap stack completely, first securely retain any needed state, review and remove the bucket's `prevent_destroy` guard, empty **all object versions and delete markers**, then plan and apply bootstrap destruction using your local AWS session. This permanently deletes project state; keep this a deliberate local operation.

## Cost and limitations

No NAT gateway, API Gateway, database, or always-running compute. Light invocation, S3 state requests/storage, CloudWatch logs and X-Ray may incur small charges; $0–$1 is a target, not a billing cap. Check your account's free-tier eligibility. The verified account concurrency quota is 10. Reserved concurrency is disabled because AWS requires at least 100 unreserved executions to configure it; a documented Checkov exception covers this constraint. Logs retain seven days. SSE-S3 encrypts state at rest; TLS-only bucket policy protects transport.

Security improvements for a production platform: add code signing, protected required checks, and a separately reviewed bootstrap pipeline.
