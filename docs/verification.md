# Deployment verification — October 30, 2026

Historical deployment record. Infrastructure has since been destroyed; see [cleanup record](cleanup.md).

- AWS account: 381491979691; region: us-east-1.
- Local application tests: 5 passed.
- Application Checkov scan: 6 passed, 0 failed, 7 documented skips.
- Application and bootstrap Terraform validation: passed.
- Bootstrap: private versioned SSE-S3 state bucket, TLS-only policy, two runtime roles and two OIDC deployment roles provisioned.
- Existing Cloud Resume OIDC provider reused as a data source.
- GitHub dev/prod environments restricted to branch main; environment variables contain identifiers, not secrets.
- Successful Actions run: https://github.com/EpicCoder71/aws-keyless-cicd/actions/runs/41009129439
- That run authenticated through GitHub OIDC, deployed `keyless-cicd-dev`, and passed the Lambda `/health` invocation assertion.
- Prod application has not been deployed. Prod deployment is manual; no required-reviewer gate has been configured.
- Destroy workflow is implemented but has not been executed. Full bootstrap teardown requires the documented local state-bucket deletion steps.
- Bootstrap Terraform state is in this workspace's ignored `bootstrap/terraform.tfstate`; retain a secure backup. Application state is remote in S3 under `dev/terraform.tfstate`.

The first live run exposed the CloudWatch distinction between a log-group ARN and an ARN ending in `:*`. The corrected policy includes both forms, scoped to the matching environment's project log group. No blanket logging permissions were added beyond the read-only DescribeLogGroups API.

Reference documentation: [GitHub immutable OIDC subjects](https://docs.github.com/en/actions/reference/security/oidc), [Terraform native S3 locking](https://developer.hashicorp.com/terraform/language/backend/s3).
