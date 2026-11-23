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
if name == "curl":
    status = os.environ.get("CURL_HTTP_STATUS", "200")
    print(status)
    sys.exit(0 if status.startswith(("2", "3")) else 22)
if name == "gcloud":
    if args[:2] == ["auth", "list"]:
        print("tester@example.com")
    elif args[:3] == ["run", "services", "describe"]:
        print("https://api.example.run.app" if args[3] == "beat-the-crowd-api"
              else "https://app.example.run.app")
    elif args[:3] == ["artifacts", "repositories", "describe"]:
        sys.exit(1 if os.environ.get("REPOSITORY_MISSING") else 0)
"""
    for name in ("gcloud", "docker", "curl"):
        cli = tmp_path / name
        cli.write_text(executable.replace("PYTHON", sys.executable), encoding="utf-8")
        cli.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k not in {
        "BUILD_MODE", "API_URL", "PROJECT_ID", "REGION", "API_SERVICE",
        "FRONTEND_SERVICE", "ARTIFACT_REPOSITORY", "CURL_HTTP_STATUS",
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


def test_success_checks_public_health_without_credentials(fake_cloud):
    result, calls = fake_cloud()
    assert result.returncode == 0, result.stderr
    checks = [call for call in calls if call[0] == "curl"]
    assert [call[-1] for call in checks] == [
        "https://api.example.run.app/health",
        "https://app.example.run.app/_stcore/health",
    ]
    for call in checks:
        assert call[1] == "--disable"  # Ignore any auth configured in .curlrc.
        assert "--fail" in call
        assert "--max-time" in call and call[call.index("--max-time") + 1] == "60"
        assert not any("Authorization" in arg for arg in call)
    assert result.stdout.count("Public access verified:") == 2


@pytest.mark.parametrize("status", ["401", "403"])
def test_denied_api_invocation_is_not_reported_as_success(fake_cloud, status):
    result, calls = fake_cloud(CURL_HTTP_STATUS=status)
    assert result.returncode != 0
    assert len(deployments(calls)) == 1  # Do not continue "all" after an inaccessible API.
    assert "API_URL=" not in result.stdout
    assert f"HTTP {status}" in result.stderr
    assert "gcloud run services add-iam-policy-binding" in result.stderr
    assert "beat-the-crowd-api" in result.stderr
    assert "--member=allUsers" in result.stderr
    assert "--role=roles/run.invoker" in result.stderr
    # The owner command is advice only, never executed.
    assert not any("add-iam-policy-binding" in call for call in calls)


def test_denied_frontend_names_correct_service(fake_cloud):
    result, calls = fake_cloud("frontend", CURL_HTTP_STATUS="403")
    assert result.returncode != 0
    assert "beat-the-crowd-app" in result.stderr
    assert "FRONTEND_URL=" not in result.stdout
    assert not any("add-iam-policy-binding" in call for call in calls)


@pytest.mark.parametrize("status", ["000", "302", "503"])
def test_other_public_check_failures_do_not_suggest_iam_grants(fake_cloud, status):
    result, _ = fake_cloud("api", CURL_HTTP_STATUS=status)
    assert result.returncode != 0
    assert "Public access verified:" not in result.stdout
    assert "API_URL=" not in result.stdout
    assert "service logs and readiness" in result.stderr
    assert "add-iam-policy-binding" not in result.stderr
