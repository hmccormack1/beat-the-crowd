"""Publish a freshly trained corrected model and deploy from its exact source.

Cloud Shell:
    bash scripts/publish_corrected_model.sh
    bash scripts/publish_corrected_model.sh --publish-only
    bash scripts/publish_corrected_model.sh --deploy-only

Requires a clean, committed corrected checkout and the existing gcloud identity.
Only Python's standard library is needed on the host; Docker supplies ML packages.
The destination is the NEW serving.model_url in config.yaml. Existing releases
are never overwritten. An identical, verified release can be reused for deployment.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ARTIFACTS = ("model.joblib", "model_card.json", "effective_config.json")
DEFAULT_PROJECT = "project-48739550-1716-4b50-877"

READ_CONFIG = "import json,yaml;print(json.dumps(yaml.safe_load(open('/app/config.yaml'))))"
CHECK_MODEL = """
import json, math
from src.serving.predictor import Predictor
from scripts.smoke_test import sample_payload, validate_prediction
cfg=json.load(open('/release/effective_config.json'))
cfg['serving']['model_path']='/release/models/model.joblib'
p=Predictor(cfg)
payload=sample_payload()
payload.update(event_n_markets=1,neg_risk=False)
result=p.predict_raw(**payload)
validate_prediction(result)
assert abs(result['crowd_probability']-0.51)<0.0001
print(json.dumps({'model_probability':result['model_probability'],
                  'crowd_probability':result['crowd_probability']}))
"""


def run(args: list[str], *, cwd: Path | None = None, capture: bool = False,
        env: dict | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, env=env, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else ""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def destination(cfg: dict) -> tuple[str, str]:
    """Allow only a new model directory in the configured public data bucket."""
    parsed = urlsplit(cfg["serving"]["model_url"])
    parts = parsed.path.strip("/").split("/")
    require(parsed.scheme == "https" and parsed.netloc == "storage.googleapis.com"
            and not parsed.query and not parsed.fragment,
            "serving.model_url must be a plain public storage.googleapis.com URL.")
    require(len(parts) >= 3 and all(re.fullmatch(r"[A-Za-z0-9_.-]+", p) for p in parts)
            and not any(p in {".", ".."} for p in parts),
            "Model URL contains an invalid bucket or object path.")
    require(parts[0] == cfg["storage"]["bucket"] and parts[-1] == "model.joblib",
            "Model destination must use the configured bucket and model.joblib filename.")
    require(cfg["storage"]["prefix"] == "v1", "Keep cleaned source data on the v1 prefix.")
    require(parts[1] != "v1", "Refusing to overwrite or publish beneath the flawed v1 model prefix.")
    expected_object = cfg["storage"].get("model_prefix", "") + "/" + cfg["storage"]["files"]["model"]
    require("/".join(parts[1:]) == expected_object,
            "serving.model_url and storage.model_prefix/files.model disagree.")
    base = parsed.scheme + "://" + parsed.netloc + "/" + "/".join(parts[:-1])
    return base, "gs://" + "/".join(parts[:-1])


def effective_config(cfg: dict) -> dict:
    result = copy.deepcopy(cfg)
    result["ingest"]["processed_dir"] = "/release/data"
    result["output"]["model_dir"] = "/release/models"
    result["output"]["reports_dir"] = "/release/reports"
    result["mlflow"]["tracking_uri"] = "sqlite:////release/mlflow.db"
    return result


def validate_card(card: dict, cfg: dict, commit: str, started_at: str | None = None) -> None:
    require(card.get("git_commit") == commit, "Model card does not identify this exact source commit.")
    require(card.get("model_type") == cfg["model"]["type"], "Model type differs from the selected config.")
    expected = hashlib.sha1(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:10]
    require(card.get("config_hash") == expected, "Model card config hash differs from the effective config.")
    trained = datetime.fromisoformat(card["trained_at"])
    require(trained.tzinfo is not None, "Model training timestamp must include its timezone.")
    if started_at:
        started = datetime.fromisoformat(started_at)
        require(trained >= started, "Model artifact predates this fresh training run.")
    require(card.get("n_snapshots", 0) > 0 and card.get("n_markets", 0) > 0,
            "Model card has no training examples.")
    metrics = card.get("metrics", {})
    require("test_model_brier" in metrics and "test_crowd_brier" in metrics,
            "Model card is missing test evaluation metrics.")
    require(all(type(v) in (int, float) and math.isfinite(v) for v in metrics.values()),
            "Model card contains nonfinite or nonnumeric metrics.")


def fetch(url: str, path: Path | None = None, *, missing_ok: bool = False) -> bytes | None:
    """Public HTTP only; no gcloud credential or service-account token is attached."""
    try:
        with urlopen(Request(url, headers={"Cache-Control": "no-cache"}), timeout=120) as response:
            if path:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("wb") as stream:
                    shutil.copyfileobj(response, stream)
                return b""
            return response.read()
    except HTTPError as exc:
        if exc.code == 404 and missing_ok:
            return None
        raise


def ensure_unpublished(base: str) -> None:
    for name in (*ARTIFACTS, "manifest.json"):
        require(fetch(base + "/" + name, missing_ok=True) is None,
                f"Existing object at {base}/{name}; refusing to overwrite a partial release. "
                "Choose a new committed serving.model_url directory.")


def artifact_path(release: Path, name: str) -> Path:
    return release / name if name == "effective_config.json" else release / "models" / name


def verify_manifest(manifest: dict, commit: str, config_sha: str, cfg: dict) -> None:
    require(manifest.get("schema_version") == 1, "Unrecognized release manifest.")
    require(manifest.get("source_commit") == commit,
            "This release belongs to a different source commit. Check out its source_commit "
            "to retry deployment, or commit a new model destination.")
    require(manifest.get("source_config_sha256") == config_sha, "Published config provenance differs.")
    require(manifest.get("model_type") == cfg["model"]["type"], "Published model type differs.")
    entries = manifest.get("artifacts", {})
    require(set(entries) == set(ARTIFACTS), "Release manifest has unexpected or missing artifacts.")
    for name in ARTIFACTS:
        require(bool(re.fullmatch(r"[a-f0-9]{64}", entries[name].get("sha256", ""))),
                f"Invalid checksum for {name}.")


def download_release(base: str, release: Path, manifest: dict, cfg: dict, commit: str) -> None:
    for name in ARTIFACTS:
        path = artifact_path(release, name)
        fetch(base + "/" + name, path)
        require(sha256(path) == manifest["artifacts"][name]["sha256"],
                f"Published {name} checksum does not match its manifest.")
        require(path.stat().st_size == manifest["artifacts"][name]["bytes"],
                f"Published {name} size differs from its manifest.")
    actual_cfg = json.loads((release / "effective_config.json").read_text())
    require(actual_cfg == effective_config(cfg), "Published effective training configuration differs.")
    card = json.loads((release / "models/model_card.json").read_text())
    validate_card(card, actual_cfg, commit, manifest["training_started_at"])


def docker_check(image: str, release: Path) -> None:
    run(["docker", "run", "--rm", "--mount", f"type=bind,source={release},target=/release,readonly",
         "--entrypoint", "python", image, "-c", CHECK_MODEL])


def create_manifest(release: Path, cfg: dict, commit: str, config_sha: str,
                    started_at: str, image_id: str) -> dict:
    card = json.loads((release / "models/model_card.json").read_text())
    validate_card(card, cfg, commit, started_at)
    artifacts = {}
    for name in ARTIFACTS:
        path = artifact_path(release, name)
        artifacts[name] = {"sha256": sha256(path), "bytes": path.stat().st_size}
    data = {}
    for kind in ("markets", "prices"):
        name = cfg["storage"]["files"][kind]
        data[kind] = {
            "url": f"https://storage.googleapis.com/{cfg['storage']['bucket']}/v1/{name}",
            "sha256": sha256(release / "data" / name),
        }
    return {
        "schema_version": 1, "source_commit": commit, "source_config_sha256": config_sha,
        "training_started_at": started_at, "trained_at": card["trained_at"],
        "training_image_id": image_id, "model_type": card["model_type"],
        "data": data, "artifacts": artifacts,
    }


def publish(base: str, gcs_base: str, release: Path, manifest: dict, project: str) -> None:
    # Generation-match zero is an atomic no-overwrite condition, not a best-effort skip.
    for name in ARTIFACTS:
        run(["gcloud", "storage", "cp", str(artifact_path(release, name)), gcs_base + "/" + name,
             "--if-generation-match=0", "--project=" + project])
    # Verify uploaded bytes through public HTTP before marking the release complete.
    for name in ARTIFACTS:
        remote = release / "public-verification" / name
        fetch(base + "/" + name, remote)
        require(sha256(remote) == manifest["artifacts"][name]["sha256"],
                f"Public checksum verification failed for {name}; deployment stopped.")
    manifest_path = release / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    run(["gcloud", "storage", "cp", str(manifest_path), gcs_base + "/manifest.json",
         "--if-generation-match=0", "--project=" + project])
    require(json.loads(fetch(base + "/manifest.json")) == manifest,
            "Public release manifest verification failed.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--publish-only", action="store_true", help="Train/publish or verify an identical release.")
    mode.add_argument("--deploy-only", action="store_true", help="Require and deploy an existing verified release.")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    for command in ("git", "docker", "gcloud", "curl", "tar"):
        require(shutil.which(command) is not None, f"{command} is required; use Cloud Shell.")
    require(not run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=root, capture=True),
            "Commit tracked changes before publishing; the release must match a reviewable Git revision.")
    commit = run(["git", "rev-parse", "HEAD"], cwd=root, capture=True)
    require(bool(re.fullmatch(r"[a-f0-9]{40}", commit)), "Expected a complete Git commit SHA.")
    run(["docker", "info"], capture=True)
    require(bool(run(["gcloud", "auth", "list", "--filter=status:ACTIVE",
                      "--format=value(account)", "--limit=1"], capture=True)), "No active gcloud account.")
    project = os.environ.get("PROJECT_ID", DEFAULT_PROJECT)

    # Only committed files enter the image; ignored host models/data are excluded.
    (root / "tmp").mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="corrected-release-", dir=root / "tmp"))
    source, release = work / "source", work / "release"
    source.mkdir()
    release.mkdir()
    print(f"Release work and MLflow outputs will be retained at {work}", flush=True)
    archive = work / "source.tar"
    run(["git", "archive", "--format=tar", "--output", str(archive), commit], cwd=root)
    run(["tar", "-xf", str(archive), "-C", str(source)])
    require(not any(source.rglob("*.joblib")), "Tracked model binaries are not permitted.")
    image = "beat-the-crowd-release:" + commit[:12]
    run(["docker", "build", "--platform=linux/amd64", "-t", image, "."], cwd=source)
    cfg = json.loads(run(["docker", "run", "--rm", "--entrypoint", "python",
                          image, "-c", READ_CONFIG], capture=True))
    base, gcs_base = destination(cfg)
    config_sha = sha256(source / "config.yaml")
    manifest_bytes = fetch(base + "/manifest.json", missing_ok=True)

    if manifest_bytes is not None:
        manifest = json.loads(manifest_bytes)
        verify_manifest(manifest, commit, config_sha, cfg)
        download_release(base, release, manifest, cfg, commit)
        docker_check(image, release)
        print("Existing release matches this source and all public artifact checksums.", flush=True)
    else:
        require(not args.deploy_only, "No complete published release exists; run without --deploy-only first.")
        ensure_unpublished(base)
        effective = effective_config(cfg)
        (release / "effective_config.json").write_text(json.dumps(effective, indent=2) + "\n")
        started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        # The working directory also keeps local MLflow artifact paths inside /release.
        run(["docker", "run", "--rm", "--workdir", "/release",
             "--mount", f"type=bind,source={release},target=/release",
             "--env", "PYTHONPATH=/app", "--env", "BTC_SOURCE_COMMIT=" + commit,
             "--env", "BTC_CONFIG=/release/effective_config.json", image, "train"])
        image_id = run(["docker", "image", "inspect", image, "--format={{.Id}}"], capture=True)
        manifest = create_manifest(release, effective, commit, config_sha, started_at, image_id)
        docker_check(image, release)
        publish(base, gcs_base, release, manifest, project)
        print(f"Published and verified {base}/manifest.json", flush=True)

    if not args.publish_only:
        # These are the verified artifacts from this release, never host models/.
        target = Path(cfg["serving"]["model_path"])
        require(not target.is_absolute() and ".." not in target.parts,
                "serving.model_path must remain inside the isolated source checkout.")
        target = source / target
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(release / "models/model.joblib", target)
        shutil.copy2(release / "models/model_card.json", target.with_name("model_card.json"))
        env = dict(os.environ, PROJECT_ID=project, BUILD_MODE="local")
        run(["bash", str(source / "scripts/deploy_cloud_run.sh"), "all"], cwd=source, env=env)
        api = run(["gcloud", "run", "services", "describe", env.get("API_SERVICE", "beat-the-crowd-api"),
                   "--project=" + project, "--region=" + env.get("REGION", "us-east1"),
                   "--format=value(status.url)"], capture=True)
        deployed = json.loads(fetch(api + "/model"))
        expected = json.loads((release / "models/model_card.json").read_text())
        require(deployed == expected, "Deployed model metadata differs from the published release.")
        frontend = run(["gcloud", "run", "services", "describe",
                        env.get("FRONTEND_SERVICE", "beat-the-crowd-app"),
                        "--project=" + project, "--region=" + env.get("REGION", "us-east1"),
                        "--format=value(status.url)"], capture=True)
        run(["docker", "run", "--rm", "--mount", f"type=bind,source={release},target=/release",
             "--entrypoint", "python", image, "scripts/smoke_test.py",
             "--api-url", api, "--frontend-url", frontend,
             "--output", "/release/deployment-verification.json"])
        print("Both services deployed; corrected-model identity and public HTTP smoke checks passed.",
              flush=True)
    print(f"Model URL: {base}/model.joblib\nProvenance: {base}/manifest.json\nLocal evidence: {work}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"Corrected release stopped: {exc}") from exc
