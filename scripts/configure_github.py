"""Configure project-only GitHub environments. Requires authenticated gh CLI."""
import json
import subprocess

repo = "repos/EpicCoder71/aws-keyless-cicd"
def api(path, payload):
    result = subprocess.run(["gh", "api", "--method", "PUT", path, "--input", "-"], input=json.dumps(payload), text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr)

for environment in ("dev", "prod"):
    api(f"{repo}/environments/{environment}", {"deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}})
    path = f"{repo}/environments/{environment}/deployment-branch-policies"
    existing = json.loads(subprocess.check_output(["gh", "api", path], text=True))
    if not any(p["name"] == "main" for p in existing["branch_policies"]):
        subprocess.run(["gh", "api", "--method", "POST", path, "-f", "name=main", "-f", "type=branch"], check=True, stdout=subprocess.DEVNULL)
    values = {"AWS_ACCOUNT_ID": "381491979691", "AWS_REGION": "us-east-1", "TF_STATE_BUCKET": "keyless-cicd-state-381491979691-us-east-1", "AWS_DEPLOY_ROLE_ARN": f"arn:aws:iam::381491979691:role/keyless-cicd-{environment}-deploy"}
    for name, value in values.items():
        subprocess.run(["gh", "variable", "set", name, "--repo", "EpicCoder71/aws-keyless-cicd", "--env", environment, "--body", value], check=True)
    print(f"Configured {environment}: main branch only, four non-secret variables")
