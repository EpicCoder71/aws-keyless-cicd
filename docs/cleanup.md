# Cleanup — October 30, 2026

User-requested full project teardown in AWS account `381491979691`, region `us-east-1`.

- Disabled the repository deployment workflow before destruction; no active runs were present.
- Terraform destroyed the dev Lambda and CloudWatch log group: 2 resources.
- Prod was never deployed; inventory found no prod application resources or state.
- Removed 15 S3 state/lock versions and delete markers after confirming no managed application resources remained in remote state.
- Terraform destroyed all 13 bootstrap resources, including four IAM roles and their inline policies, and the dedicated state bucket and its configuration.
- Removed the repository's dev/prod GitHub environments and their deployment variables.
- Restored the bucket deletion guard in source for any future rebuild.
- Retained source, architecture, deployment history, and project completion evidence.

Final inventory verified no project Lambda functions, log groups, IAM roles, or S3 buckets. Bootstrap state contains no managed resources. The shared GitHub OIDC provider and the Cloud Resume S3/CloudFront website remain intact.

Rebuilding requires deliberate bootstrap provisioning, recreating environment configuration, and reenabling the workflow. Existing instructions describe that build process; they do not imply resources are currently running.
