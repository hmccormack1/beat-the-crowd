"""Exercise deployment commands with fake CLIs; never use cloud credentials."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "deploy_cloud_run.sh"


@pytest.fixture
def fake_cloud(tmp_path):
    log = tmp_path / "calls.jsonl"
    executable = """#!PYTHON
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["MOCK_LOG"], "a") as stream:
    stream.write(json.dumps([name, *args]) + "\\n")
if name == "docker" and args[0] == os.environ.get("FAIL_DOCKER"):
    sys.exit(1)
if name == "gcloud":
    if args[:2] == ["auth", "list"]:
        print("tester@example.com")
    elif args[:3] == ["run", "services", "describe"]:
        print("https://api.example.run.app" if args[3] == "beat-the-crowd-api"
              else "https://app.example.run.app")
    elif args[:3] == ["artifacts", "repositories", "describe"]:
        sys.exit(1 if os.environ.get("REPOSITORY_MISSING") else 0)
"""
    for name in ("gcloud", "docker"):
        cli = tmp_path / name
        cli.write_text(executable.replace("PYTHON", sys.executable), encoding="utf-8")
        cli.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k not in {
        "BUILD_MODE", "API_URL", "PROJECT_ID", "REGION", "API_SERVICE",
        "FRONTEND_SERVICE", "ARTIFACT_REPOSITORY",
    }}
    env.update(PATH=f"{tmp_path}:{env['PATH']}", MOCK_LOG=str(log))

    def run(target="all", **overrides):
        result = subprocess.run(["bash", str(SCRIPT), target], env={**env, **overrides},
                                capture_output=True, text=True, check=False)
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return result, calls

    return run


def deployments(calls):
    return [call for call in calls if call[:3] == ["gcloud", "run", "deploy"]]


def test_local_builds_pushes_and_deploys_both_services(fake_cloud):
    result, calls = fake_cloud(BUILD_MODE="local")
    assert result.returncode == 0, result.stderr
    builds = [call for call in calls if call[:2] == ["docker", "build"]]
    pushes = [call for call in calls if call[:2] == ["docker", "push"]]
    assert len(builds) == len(pushes) == 2
    assert [call[call.index("-f") + 1] for call in builds] == ["Dockerfile", "Dockerfile.frontend"]
    for build, push, deploy in zip(builds, pushes, deployments(calls)):
        image = build[build.index("-t") + 1]
        assert image.startswith(
            "us-east1-docker.pkg.dev/project-48739550-1716-4b50-877/beat-the-crowd/")
        assert "--platform=linux/amd64" in build
        assert push == ["docker", "push", image]
        assert f"--image={image}" in deploy
        assert "--source=." not in deploy
        assert calls.index(push) < calls.index(deploy)
        assert "--max-instances=2" in deploy
        assert "--min-instances=0" in deploy
        assert "--allow-unauthenticated" in deploy
    auth = [call for call in calls if call[:3] == ["gcloud", "auth", "configure-docker"]]
    assert auth == [["gcloud", "auth", "configure-docker", "us-east1-docker.pkg.dev", "--quiet"]]
    assert not any(call[:2] == ["gcloud", "builds"] for call in calls)
    assert not any("cloudbuild.googleapis.com" in call for call in calls)
    assert not any("iam" in item or "print-access-token" in item for call in calls for item in call)
    assert "--update-env-vars=API_URL=https://api.example.run.app" in deployments(calls)[1]
    assert "FRONTEND_URL=https://app.example.run.app" in result.stdout


def test_cloud_remains_the_default(fake_cloud):
    result, calls = fake_cloud()
    assert result.returncode == 0, result.stderr
    assert not any(call[0] == "docker" for call in calls)
    assert "--source=." in deployments(calls)[0]
    assert any(call[:3] == ["gcloud", "builds", "submit"] for call in calls)
    assert any("cloudbuild.googleapis.com" in call for call in calls)


def test_local_frontend_reuses_existing_repository_and_explicit_api(fake_cloud):
    result, calls = fake_cloud(
        "frontend", BUILD_MODE="local", ARTIFACT_REPOSITORY="cloud-run-source-deploy",
        API_URL="https://existing.example.run.app/",
    )
    assert result.returncode == 0, result.stderr
    assert not any(call[:4] == ["gcloud", "artifacts", "repositories", "create"] for call in calls)
    assert not any(call[:4] == ["gcloud", "run", "services", "describe"]
                   and call[4] == "beat-the-crowd-api" for call in calls)
    deploy = deployments(calls)[0]
    assert "--update-env-vars=API_URL=https://existing.example.run.app" in deploy
    assert any("/cloud-run-source-deploy/beat-the-crowd-app:" in arg for arg in deploy)


@pytest.mark.parametrize("stage", ["info", "build", "push"])
def test_local_docker_failures_stop_before_deployment(fake_cloud, stage):
    result, calls = fake_cloud("api", BUILD_MODE="local", FAIL_DOCKER=stage)
    assert result.returncode != 0
    assert not deployments(calls)
    if stage == "info":
        assert not any(call[0] == "gcloud" for call in calls)


def test_invalid_build_mode_exits_before_cloud_access(fake_cloud):
    result, calls = fake_cloud(BUILD_MODE="invalid")
    assert result.returncode == 2
    assert "BUILD_MODE must be cloud or local" in result.stderr
    assert calls == []
