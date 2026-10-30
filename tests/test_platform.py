"""Exercise lifecycle safety boundaries without contacting AWS or GitHub."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock
import pytest

spec = importlib.util.spec_from_file_location("platform_cli", Path(__file__).parents[1] / "scripts/platform.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


def test_wrong_account_stops(monkeypatch):
    monkeypatch.setattr(cli, "aws", lambda *a: {"Account": "000000000000"})
    with pytest.raises(RuntimeError, match="Wrong AWS account"):
        cli.identity()


def test_active_ci_run_stops_local_mutations(monkeypatch):
    calls = Mock(side_effect=[None, json.dumps({"workflow_runs": [{"status": "in_progress", "html_url": "run-url"}]})])
    monkeypatch.setattr(cli, "run", calls)
    with pytest.raises(RuntimeError, match="active GitHub runs"):
        cli.pause_ci()
    assert calls.call_args_list[0].args[0][1:3] == ["workflow", "disable"]


def test_prod_backend_is_explicit(monkeypatch):
    calls = Mock()
    monkeypatch.setattr(cli, "tf", calls)
    cli.init_app("prod")
    assert "-backend-config=key=prod/terraform.tfstate" in calls.call_args.args
    assert "-backend-config=use_lockfile=true" in calls.call_args.args


def test_normal_destroy_keeps_bootstrap(monkeypatch):
    monkeypatch.setattr(cli, "pause_ci", lambda: None)
    monkeypatch.setattr(cli, "inventory", lambda: {"buckets": [cli.BUCKET]})
    init, plan = Mock(), Mock()
    monkeypatch.setattr(cli, "init_app", init)
    monkeypatch.setattr(cli, "plan_and_apply", plan)
    cli.app("dev", "destroy")
    init.assert_called_once_with("dev")
    plan.assert_called_once_with("terraform", "dev", destroy=True, apply=True)


def test_apply_requires_bootstrap(monkeypatch):
    monkeypatch.setattr(cli, "pause_ci", lambda: None)
    monkeypatch.setattr(cli, "inventory", lambda: {"buckets": []})
    with pytest.raises(RuntimeError, match="bootstrap first"):
        cli.app("dev", "apply")


def test_repeated_destroy_is_noop(monkeypatch):
    monkeypatch.setattr(cli, "pause_ci", lambda: None)
    monkeypatch.setattr(cli, "inventory", lambda: {"buckets": [], "functions": [], "log_groups": []})
    plan = Mock()
    monkeypatch.setattr(cli, "plan_and_apply", plan)
    cli.app("dev", "destroy")
    plan.assert_not_called()


def test_full_cleanup_refuses_missing_bootstrap_state(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "pause_ci", lambda: None)
    monkeypatch.setattr(cli, "inventory", lambda: {"roles": ["keyless-cicd-dev-runtime"]})
    with pytest.raises(RuntimeError, match="state is missing or empty"):
        cli.clean_all()


@pytest.mark.parametrize("objects,message", [
    ({"Versions": [{"Key": "unrelated-file", "VersionId": "v1"}]}, "Unexpected"),
    ({"Versions": [{"Key": "dev/terraform.tfstate.tflock", "VersionId": "v1", "IsLatest": True}]}, "state lock"),
])
def test_bucket_deletion_refuses_unexpected_content_and_locks(monkeypatch, objects, message):
    calls = Mock(return_value=objects)
    monkeypatch.setattr(cli, "aws", calls)
    with pytest.raises(RuntimeError, match=message):
        cli.empty_bucket()
    calls.assert_called_once_with("s3api", "list-object-versions", "--bucket", cli.BUCKET)


def test_managed_state_blocks_version_deletion(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    (tmp_path / ".build").mkdir()
    objects = {"Versions": [{"Key": "dev/terraform.tfstate", "VersionId": "v1", "IsLatest": True}]}
    calls = Mock(return_value=objects)
    monkeypatch.setattr(cli, "aws", calls)
    def download(*args):
        (tmp_path / ".build/cleanup-state.json").write_text(json.dumps({"resources": [{"mode": "managed", "instances": [{}]}]}))
    monkeypatch.setattr(cli, "run", download)
    with pytest.raises(RuntimeError, match="Managed resources remain"):
        cli.empty_bucket()
    assert calls.call_count == 1


def test_terraform_version_rejects_old_system_binary(monkeypatch):
    monkeypatch.setattr(cli, "run", lambda *a: '{"terraform_version":"1.8.2"}')
    with pytest.raises(RuntimeError, match="Terraform >=1.10"):
        cli.terraform()


def test_full_cleanup_keeps_source_guard_and_orders_state_deletion(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    (tmp_path / ".build").mkdir()
    boot = tmp_path / "bootstrap"
    boot.mkdir()
    source = 'resource "aws_s3_bucket" "state" {\n lifecycle { prevent_destroy = true }\n}\n'
    (boot / "main.tf").write_text(source)
    (boot / ".terraform.lock.hcl").write_text("")
    (boot / "terraform.tfstate").write_text(json.dumps({"resources": [{"mode": "managed", "instances": [{}]}]}))
    inventories = iter([
        {"functions": ["keyless-cicd-dev"], "log_groups": [], "roles": ["role"], "buckets": [cli.BUCKET]},
        {"functions": [], "log_groups": [], "roles": ["role"], "buckets": [cli.BUCKET]},
        {"functions": [], "log_groups": [], "roles": [], "buckets": []},
    ])
    monkeypatch.setattr(cli, "inventory", lambda: next(inventories))
    monkeypatch.setattr(cli, "pause_ci", lambda: None)
    applications = Mock()
    monkeypatch.setattr(cli, "app", applications)
    events = []
    monkeypatch.setattr(cli, "tf", lambda directory, action, *a: events.append(action))
    monkeypatch.setattr(cli, "empty_bucket", lambda: events.append("empty-state"))
    monkeypatch.setattr(cli, "run", lambda *a: '{"environments":[]}')
    cli.clean_all()
    assert [c.args for c in applications.call_args_list] == [("dev", "destroy"), ("prod", "destroy")]
    assert events == ["init", "plan", "empty-state", "apply"]
    assert (boot / "main.tf").read_text() == source
    isolated = tmp_path / ".build/bootstrap-cleanup"
    assert "prevent_destroy = false" in (isolated / "main.tf").read_text()
    assert str(boot / "terraform.tfstate") in (isolated / "local-backend.tf").read_text()


def test_full_cleanup_on_empty_project_skips_terraform(monkeypatch):
    monkeypatch.setattr(cli, "pause_ci", lambda: None)
    monkeypatch.setattr(cli, "inventory", lambda: {"functions": [], "log_groups": [], "roles": [], "buckets": []})
    monkeypatch.setattr(cli, "run", lambda *a: '{"environments":[]}')
    terraform_calls = Mock()
    monkeypatch.setattr(cli, "tf", terraform_calls)
    cli.clean_all()
    terraform_calls.assert_not_called()
