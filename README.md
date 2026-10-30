# Keyless CI/CD Deployment Platform

Python Lambda deployments using Terraform and GitHub Actions OIDC. No AWS access keys belong in GitHub. Repository: https://github.com/EpicCoder71/aws-keyless-cicd

**Current status: completed and torn down on October 30, 2026.** Terraform destroyed the dev application and all bootstrap resources. The project state bucket (including every version and delete marker), all project IAM roles, and its GitHub environments were removed. The deployment workflow is disabled. The shared OIDC provider and Cloud Resume site were preserved. The source remains available for a deliberate rebuild.

Dev deployment was previously verified successfully: [Actions run](https://github.com/EpicCoder71/aws-keyless-cicd/actions/runs/41009129439). See [verification details](docs/verification.md) and [cleanup record](docs/cleanup.md).

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

## Easy repeatable commands

Run these from the project folder using your authenticated local AWS and GitHub CLI sessions:

```sh
make bootstrap       # Create the state bucket and dev/prod IAM roles
make apply           # Deploy dev and run its health check
make destroy         # Remove dev Lambda + logs; keep bootstrap ready
make apply           # Rebuild dev whenever you want
make status          # List remaining project resources
make clean-all       # Destroy BOTH environments, roles, and ALL state versions/bucket
```

`ENV=dev` is the default. Use `make apply ENV=prod` or `make destroy ENV=prod` for prod. `make plan ENV=dev` previews application changes. Each apply/destroy command prints a Terraform plan and executes it without an extra prompt. `make clean-all` is the explicit full-teardown command: it permanently removes historical Terraform state too. Source code, diagrams, and the shared Cloud Resume OIDC provider stay intact.

Local lifecycle commands pause the GitHub deployment workflow and refuse to proceed while a GitHub run is active. This prevents a push from rebuilding Lambda just after you destroy it. Local commands are serialized within this checkout, and Terraform S3 locks protect application state. Avoid running lifecycle commands from multiple checkouts at once, especially full cleanup.

Requirements: Python 3, Terraform >=1.10 and <2, AWS CLI, GitHub CLI, and `make`. No Python packages are required for lifecycle commands. They verify account `381491979691` and use `us-east-1`. Authenticate AWS with your local session and GitHub with `gh auth login`. The project-local `.tools/terraform` is preferred; otherwise use the system Terraform or override it:

```sh
TERRAFORM=/path/to/terraform make apply
```

Bootstrap state remains local in ignored `bootstrap/terraform.tfstate`; securely retain it between sessions. Application state lives in S3 with separate dev/prod keys. Bootstrap must exist before an application apply. Repeated application destroy and full cleanup handle an already-empty project. If AWS resources exist but bootstrap state is missing, full cleanup stops so you can recover/import state.

### Optional GitHub OIDC deployment

```sh
make bootstrap
make github          # Recreate environment variables/rules and enable the workflow
```

Push main to deploy dev, or use **Actions → Test and deploy → Run workflow** on main for dev/prod apply/destroy. `make github` enables CI deployment; the next local plan/apply/destroy/bootstrap/clean-all pauses it again. Enable it deliberately when returning to GitHub-driven deployments. For prod, configure required reviewers where your GitHub plan supports them.

Trust uses the verified immutable subject prefix `repo:EpicCoder71@57415684/aws-keyless-cicd@1439298585` plus `:environment:dev` or `:environment:prod`. GitHub environments are restricted to main. `make github` sets non-secret account, region, bucket, and environment role identifiers. Checkov scans application Terraform; bootstrap is validated separately and requires IAM review.

Full cleanup automatically uses an isolated bootstrap configuration with the bucket deletion guard removed only for that operation. The source guard stays enabled. It destroys both application environments first, refuses to delete state if managed resources or an active state lock remain, removes all state versions/delete markers, destroys bootstrap, removes GitHub deployment environments, and checks for remaining project resources.

## Cost and limitations

No NAT gateway, API Gateway, database, or always-running compute. Light invocation, S3 state requests/storage, CloudWatch logs and X-Ray may incur small charges; $0–$1 is a target, not a billing cap. Check your account's free-tier eligibility. The verified account concurrency quota is 10. Reserved concurrency is disabled because AWS requires at least 100 unreserved executions to configure it; a documented Checkov exception covers this constraint. Logs retain seven days. SSE-S3 encrypts state at rest; TLS-only bucket policy protects transport.

Security improvements for a production platform: add code signing, protected required checks, and a separately reviewed bootstrap pipeline.
