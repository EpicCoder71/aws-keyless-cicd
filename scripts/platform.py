"""Repeatable project lifecycle; standard Python + Terraform + AWS CLI only."""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = "381491979691"
REGION = "us-east-1"
BUCKET = f"keyless-cicd-state-{ACCOUNT}-{REGION}"
REPO = "EpicCoder71/aws-keyless-cicd"
WORKFLOW = "pipeline.yml"


def run(args, capture=False):
    result = subprocess.run([str(a) for a in args], cwd=ROOT, check=True,
                            text=True, stdout=subprocess.PIPE if capture else None)
    return result.stdout if capture else None


def aws(*args):
    output = run(["aws", *args, "--region", REGION, "--output", "json"], True)
    return json.loads(output) if output.strip() else {}


def terraform():
    candidate = os.getenv("TERRAFORM") or str(ROOT / ".tools/terraform")
    if not Path(candidate).is_file():
        candidate = shutil.which(candidate) or shutil.which("terraform")
    if not candidate:
        raise RuntimeError("Install Terraform >=1.10 or set TERRAFORM=/path/to/terraform.")
    info = json.loads(run([candidate, "version", "-json"], True))
    version = tuple(int(p) for p in info["terraform_version"].split("-")[0].split("."))
    if not (version >= (1, 10, 0) and version < (2, 0, 0)):
        raise RuntimeError("Terraform >=1.10 and <2 is required. Set TERRAFORM to a suitable binary.")
    return candidate


def tf(directory, *args, capture=False):
    return run([terraform(), f"-chdir={ROOT / directory}", *args], capture)


@contextmanager
def lifecycle_lock():
    (ROOT / ".build").mkdir(exist_ok=True)
    with (ROOT / ".build/lifecycle.lock").open("w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another local lifecycle command is running. Wait for it to finish.") from None
        yield


def identity():
    caller = aws("sts", "get-caller-identity")
    if caller["Account"] != ACCOUNT:
        raise RuntimeError(f"Wrong AWS account: {caller['Account']}; expected {ACCOUNT}.")
    print(f"AWS account {ACCOUNT} · {REGION}", flush=True)


def inventory():
    return {
        "functions": [f["FunctionName"] for f in aws("lambda", "list-functions")["Functions"]
                      if f["FunctionName"].startswith("keyless-cicd-")],
        "log_groups": [g["logGroupName"] for g in aws("logs", "describe-log-groups",
                       "--log-group-name-prefix", "/aws/lambda/keyless-cicd-")["logGroups"]],
        "roles": [r["RoleName"] for r in aws("iam", "list-roles")["Roles"]
                  if r["RoleName"].startswith("keyless-cicd-")],
        "buckets": [b["Name"] for b in aws("s3api", "list-buckets")["Buckets"]
                    if b["Name"].startswith("keyless-cicd-")],
    }


def pause_ci():
    # Refuse local Terraform mutations while a remote run might be using state.
    run(["gh", "workflow", "disable", WORKFLOW, "--repo", REPO])
    active = json.loads(run(["gh", "api", f"repos/{REPO}/actions/workflows/{WORKFLOW}/runs?per_page=100"], True))
    pending = [r["html_url"] for r in active["workflow_runs"]
               if r["status"] != "completed"]
    if pending:
        raise RuntimeError("Wait for or cancel active GitHub runs before continuing: " + ", ".join(pending))
    print("GitHub deployment workflow paused for local Terraform operations.", flush=True)


def init_app(env):
    tf("terraform", "init", "-reconfigure", "-input=false",
       f"-backend-config=bucket={BUCKET}", f"-backend-config=key={env}/terraform.tfstate",
       f"-backend-config=region={REGION}", "-backend-config=encrypt=true",
       "-backend-config=use_lockfile=true")


def plan_and_apply(directory, env=None, destroy=False, apply=True):
    plan = "lifecycle.tfplan"
    args = ["plan", "-input=false", "-lock-timeout=5m", f"-var=account_id={ACCOUNT}"]
    if env:
        args.append(f"-var=environment={env}")
    if destroy:
        args.append("-destroy")
    tf(directory, *args, f"-out={plan}")
    if apply:
        tf(directory, "apply", "-input=false", plan)
    # Do not leave a stale executable plan on disk.
    (ROOT / directory / plan).unlink(missing_ok=True)


def bootstrap():
    pause_ci()
    tf("bootstrap", "init", "-input=false")
    plan_and_apply("bootstrap")
    print("Bootstrap ready. Run make apply, or make github for GitHub OIDC deployment.")


def app(env, operation):
    pause_ci()
    resources = inventory()
    if BUCKET not in resources["buckets"]:
        if operation == "destroy" and not any(
            name == f"keyless-cicd-{env}" for name in resources["functions"]
        ) and f"/aws/lambda/keyless-cicd-{env}" not in resources["log_groups"]:
            print(f"{env}: already destroyed; no state bucket exists.")
            return
        raise RuntimeError("Bootstrap is missing. Run make bootstrap first.")
    init_app(env)
    plan_and_apply("terraform", env, destroy=operation == "destroy", apply=operation != "plan")
    if operation == "apply":
        response = ROOT / ".build/health.json"
        result = aws("lambda", "invoke", "--function-name", f"keyless-cicd-{env}",
                     "--cli-binary-format", "raw-in-base64-out", "--payload",
                     '{"rawPath":"/health"}', str(response))
        body = json.loads(response.read_text())
        if result.get("FunctionError") or body.get("statusCode") != 200 or json.loads(body["body"]).get("status") != "ok":
            raise RuntimeError("Lambda health check failed.")
        print(f"{env}: deployed; health check passed.")
    elif operation == "destroy":
        print(f"{env}: destroyed. Bootstrap retained; make apply will rebuild it.")


def empty_bucket():
    # Verify all current state objects before deleting any historical version.
    objects = aws("s3api", "list-object-versions", "--bucket", BUCKET)
    versions = objects.get("Versions", []) + objects.get("DeleteMarkers", [])
    allowed = {f"{env}/terraform.tfstate{suffix}" for env in ("dev", "prod") for suffix in ("", ".tflock")}
    if any(x["Key"] not in allowed for x in versions):
        raise RuntimeError("Unexpected state bucket content; refusing to delete it.")
    if any(x["IsLatest"] and x["Key"].endswith(".tflock") for x in objects.get("Versions", [])):
        raise RuntimeError("A state lock exists; refusing full cleanup while Terraform may be running.")
    for x in objects.get("Versions", []):
        if x["IsLatest"] and not x["Key"].endswith(".tflock"):
            target = ROOT / ".build/cleanup-state.json"
            run(["aws", "s3api", "get-object", "--bucket", BUCKET, "--key", x["Key"],
                 "--region", REGION, str(target)], True)
            state = json.loads(target.read_text())
            target.unlink()
            if any(r.get("mode") == "managed" and r.get("instances") for r in state.get("resources", [])):
                raise RuntimeError("Managed resources remain in remote state; refusing to delete state.")
    for i in range(0, len(versions), 1000):
        payload = {"Objects": [{"Key": x["Key"], "VersionId": x["VersionId"]}
                               for x in versions[i:i+1000]], "Quiet": True}
        result = aws("s3api", "delete-objects", "--bucket", BUCKET, "--delete", json.dumps(payload))
        if result.get("Errors"):
            raise RuntimeError(str(result["Errors"]))
    for upload in aws("s3api", "list-multipart-uploads", "--bucket", BUCKET).get("Uploads", []):
        aws("s3api", "abort-multipart-upload", "--bucket", BUCKET,
            "--key", upload["Key"], "--upload-id", upload["UploadId"])


def clean_all():
    pause_ci()
    resources = inventory()
    if not any(resources.values()):
        print("AWS project resources are already removed.")
    else:
        state = ROOT / "bootstrap/terraform.tfstate"
        if not state.exists() or not any(r.get("mode") == "managed" and r.get("instances")
                                        for r in json.loads(state.read_text()).get("resources", [])):
            raise RuntimeError("Bootstrap state is missing or empty while AWS resources exist. Recover/import state first.")
        for env in ("dev", "prod"):
            app(env, "destroy")
        remaining = inventory()
        if remaining["functions"] or remaining["log_groups"]:
            raise RuntimeError("Application resources remain; bootstrap cleanup aborted.")
        # Isolated copy removes the guard for this command only. Original source stays protected.
        directory = Path(".build/bootstrap-cleanup")
        target = ROOT / directory
        target.mkdir(exist_ok=True)
        for source in (ROOT / "bootstrap").glob("*.tf"):
            (target / source.name).write_text(source.read_text().replace("prevent_destroy = true", "prevent_destroy = false"))
        shutil.copy2(ROOT / "bootstrap/.terraform.lock.hcl", target / ".terraform.lock.hcl")
        (target / "local-backend.tf").write_text('terraform {\n backend "local" {\n path = ' + json.dumps(str(state)) + '\n }\n}\n')
        tf(directory, "init", "-reconfigure", "-input=false")
        # Review the full bootstrap destruction before permanently deleting state versions.
        tf(directory, "plan", "-destroy", "-input=false", "-lock-timeout=5m",
           f"-var=account_id={ACCOUNT}", "-out=lifecycle.tfplan")
        if BUCKET in remaining["buckets"]:
            empty_bucket()
        tf(directory, "apply", "-input=false", "lifecycle.tfplan")
        (target / "lifecycle.tfplan").unlink(missing_ok=True)
    for env in ("dev", "prod"):
        existing = json.loads(run(["gh", "api", f"repos/{REPO}/environments"], True))
        if any(e["name"] == env for e in existing["environments"]):
            run(["gh", "api", "--method", "DELETE", f"repos/{REPO}/environments/{env}"])
    final = inventory()
    if any(final.values()):
        raise RuntimeError("Unexpected remaining project resources: " + json.dumps(final))
    print("Full cleanup verified. Project resources and GitHub environments removed; shared OIDC provider preserved.")


def main():
    parser = argparse.ArgumentParser(description="Keyless CI/CD: make bootstrap | apply | destroy | status | github | clean-all; ENV=dev (default) or prod. Local Terraform commands pause GitHub deployments. clean-all destroys both environments and bootstrap.")
    parser.add_argument("command", choices=["bootstrap", "plan", "apply", "destroy", "status", "github", "clean-all"])
    parser.add_argument("--env", choices=["dev", "prod"], default="dev")
    args = parser.parse_args()
    with lifecycle_lock():
        identity()
        if args.command == "status":
            print(json.dumps(inventory(), indent=2))
        elif args.command == "bootstrap":
            bootstrap()
        elif args.command == "github":
            pause_ci()
            if BUCKET not in inventory()["buckets"]:
                raise RuntimeError("Run make bootstrap first.")
            run([sys.executable, "scripts/configure_github.py"])
            run(["gh", "workflow", "enable", WORKFLOW, "--repo", REPO])
            print("GitHub deployments enabled. Main pushes deploy dev; manual dispatch supports dev/prod.")
        elif args.command == "clean-all":
            clean_all()
        else:
            app(args.env, args.command)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Stopped: {exc}", file=sys.stderr)
        sys.exit(1)
