"""Corrected releases bind fresh artifacts to reviewed source without overwrites."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

from scripts import publish_corrected_model as release
from src.data import storage

COMMIT = "a" * 40


@pytest.fixture
def release_cfg(cfg):
    cfg["storage"]["prefix"] = "v1"
    cfg["storage"]["model_prefix"] = "v2-corrected"
    cfg["serving"]["model_url"] = (
        "https://storage.googleapis.com/beat-the-crowd/v2-corrected/model/model.joblib"
    )
    cfg["serving"]["model_path"] = "models/v2-corrected/model.joblib"
    return cfg


def card_for(cfg):
    return {
        "git_commit": COMMIT, "model_type": cfg["model"]["type"],
        "config_hash": hashlib.sha1(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:10],
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_markets": 10, "n_snapshots": 30,
        "metrics": {"test_model_brier": 0.2, "test_crowd_brier": 0.21},
    }


def test_model_upload_prefix_does_not_move_data(release_cfg, monkeypatch):
    monkeypatch.setattr(storage, "load_config", lambda _: release_cfg)
    monkeypatch.setattr(sys, "argv", ["storage", "upload-model"])
    uploaded = []
    monkeypatch.setattr(storage, "upload_file",
                        lambda cfg, local, name, **kw: uploaded.append(
                            storage.blob_name(cfg, name, **kw)))
    storage.main()
    assert uploaded == [
        "v2-corrected/model/model.joblib", "v2-corrected/model/model_card.json",
    ]
    assert storage.blob_name(release_cfg, "markets.parquet") == "v1/markets.parquet"
    assert storage.public_url(release_cfg, "prices.parquet").endswith("/v1/prices.parquet")


def test_model_upload_keeps_legacy_default_when_no_model_prefix(cfg, monkeypatch):
    cfg["storage"].pop("model_prefix", None)
    monkeypatch.setattr(storage, "load_config", lambda _: cfg)
    monkeypatch.setattr(sys, "argv", ["storage", "upload-model"])
    prefixes = []
    monkeypatch.setattr(storage, "upload_file",
                        lambda cfg, local, name, **kw: prefixes.append(kw["prefix"]))
    storage.main()
    assert prefixes == [cfg["storage"]["prefix"]] * 2


def test_new_destination_matches_data_bucket(release_cfg):
    assert release.destination(release_cfg) == (
        "https://storage.googleapis.com/beat-the-crowd/v2-corrected/model",
        "gs://beat-the-crowd/v2-corrected/model",
    )


@pytest.mark.parametrize("url", [
    "https://storage.googleapis.com/beat-the-crowd/v1/model/model.joblib",
    "https://storage.googleapis.com/other-bucket/v2-corrected/model/model.joblib",
    "https://example.com/beat-the-crowd/v2-corrected/model/model.joblib",
    "https://storage.googleapis.com/beat-the-crowd/v2-corrected/../model/model.joblib",
    "https://storage.googleapis.com/beat-the-crowd/v2-corrected/model/model.joblib?token=secret",
    "https://storage.googleapis.com/beat-the-crowd/v3/model/model.joblib",
])
def test_unsafe_or_mismatched_destination_rejected(release_cfg, url):
    release_cfg["serving"]["model_url"] = url
    with pytest.raises(ValueError):
        release.destination(release_cfg)


def test_effective_config_isolated_and_does_not_mutate_source(release_cfg):
    original = json.dumps(release_cfg, sort_keys=True)
    cfg = release.effective_config(release_cfg)
    assert cfg["output"]["model_dir"] == "/release/models"
    assert cfg["ingest"]["processed_dir"] == "/release/data"
    assert cfg["mlflow"]["tracking_uri"] == "sqlite:////release/mlflow.db"
    assert json.dumps(release_cfg, sort_keys=True) == original


@pytest.mark.parametrize("field,value", [
    ("git_commit", "unknown"), ("config_hash", "old-hash"),
    ("model_type", "unselected_model"), ("n_snapshots", 0),
])
def test_stale_or_unrelated_model_card_rejected(release_cfg, field, value):
    cfg = release.effective_config(release_cfg)
    card = card_for(cfg)
    card[field] = value
    with pytest.raises(ValueError):
        release.validate_card(card, cfg, COMMIT)


def test_card_must_come_from_this_fresh_run(release_cfg):
    cfg = release.effective_config(release_cfg)
    card = card_for(cfg)
    card["trained_at"] = "2025-01-01T00:00:00+00:00"
    with pytest.raises(ValueError, match="predates"):
        release.validate_card(card, cfg, COMMIT, "2026-01-01T00:00:00+00:00")


def test_partial_release_is_not_overwritten(monkeypatch):
    monkeypatch.setattr(release, "fetch", lambda *a, **k: b"existing model")
    with pytest.raises(ValueError, match="partial release"):
        release.ensure_unpublished("https://example.com/v2/model")


def test_fresh_publish_and_identical_retry_do_not_touch_host_models(
        release_cfg, monkeypatch, tmp_path):
    """Simulate Docker/GCS at their process/HTTP boundaries; no external services."""
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "models").mkdir()
    host_model = root / "models/model.joblib"
    host_model.write_bytes(b"old flawed model that must never be published")
    source_config = json.dumps(release_cfg, sort_keys=True)
    (root / "config.yaml").write_text(source_config)
    monkeypatch.setattr(release, "__file__", str(root / "scripts/publish_corrected_model.py"))
    monkeypatch.setattr(release.shutil, "which", lambda name: "/mock/" + name)
    monkeypatch.setattr(sys, "argv", ["publish_corrected_model.py", "--publish-only"])
    cloud, calls, training_runs = {}, [], []

    def fake_run(args, *, cwd=None, capture=False, env=None):
        calls.append(args)
        if args[:3] == ["git", "status", "--porcelain"]:
            return ""
        if args[:3] == ["git", "rev-parse", "HEAD"]:
            return COMMIT
        if args[:2] == ["gcloud", "auth"]:
            return "authorized@example.com"
        if args[:2] == ["tar", "-xf"]:
            # Represents the tracked git archive, with no ignored model contents.
            source = Path(args[args.index("-C") + 1])
            (source / "models").mkdir()
            (source / "config.yaml").write_text(source_config)
        if args[:2] == ["docker", "run"] and release.READ_CONFIG in args:
            return json.dumps(release_cfg)
        if args[:2] == ["docker", "run"] and args[-1] == "train":
            training_runs.append(args)
            mount = args[args.index("--mount") + 1]
            local = Path(mount.split("source=")[1].split(",")[0])
            cfg = json.loads((local / "effective_config.json").read_text())
            (local / "models").mkdir()
            (local / "models/model.joblib").write_bytes(b"fresh corrected model")
            (local / "models/model_card.json").write_text(json.dumps(card_for(cfg)))
            (local / "data").mkdir()
            for name in ("markets.parquet", "prices.parquet"):
                (local / "data" / name).write_bytes(b"public v1 source data")
        if args[:3] == ["docker", "image", "inspect"]:
            return "sha256:" + "b" * 64
        if args and args[0] == "bash":
            target = cwd / release_cfg["serving"]["model_path"]
            assert target.read_bytes() == b"fresh corrected model"
            assert env["BUILD_MODE"] == "local"
        if args[:4] == ["gcloud", "run", "services", "describe"]:
            return "https://api.example.com" if args[4] == "beat-the-crowd-api" else "https://app.example.com"
        if args[:3] == ["gcloud", "storage", "cp"]:
            assert "--if-generation-match=0" in args
            destination = args[4].replace("gs://", "https://storage.googleapis.com/")
            assert destination not in cloud
            cloud[destination] = Path(args[3]).read_bytes()
        return ""

    def fake_fetch(url, path=None, *, missing_ok=False):
        if url == "https://api.example.com/model":
            return cloud[release_cfg["serving"]["model_url"].replace("model.joblib", "model_card.json")]
        if url not in cloud:
            assert missing_ok
            return None
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(cloud[url])
            return b""
        return cloud[url]

    monkeypatch.setattr(release, "run", fake_run)
    monkeypatch.setattr(release, "fetch", fake_fetch)
    release.main()
    release.main()  # Publication/deployment recovery reuses exactly verified artifacts.
    monkeypatch.setattr(sys, "argv", ["publish_corrected_model.py", "--deploy-only"])
    release.main()
    assert any("scripts/smoke_test.py" in call for call in calls)
    assert len(training_runs) == 1
    assert "BTC_SOURCE_COMMIT=" + COMMIT in training_runs[0]
    assert host_model.read_bytes() == b"old flawed model that must never be published"
    uploads = [call for call in calls if call[:3] == ["gcloud", "storage", "cp"]]
    assert len(uploads) == 4
    assert uploads[-1][4].endswith("/manifest.json")
    assert not any("/v1/" in call[4] for call in uploads)
    model_url = release_cfg["serving"]["model_url"]
    assert cloud[model_url] == b"fresh corrected model"
    manifest = json.loads(cloud[model_url.replace("model.joblib", "manifest.json")])
    assert manifest["source_commit"] == COMMIT
    assert manifest["artifacts"]["model.joblib"]["sha256"] == hashlib.sha256(
        b"fresh corrected model").hexdigest()


def test_modified_published_bytes_rejected(release_cfg, monkeypatch, tmp_path):
    manifest = {"artifacts": {name: {"sha256": "0" * 64, "bytes": 3}
                              for name in release.ARTIFACTS}}
    def changed(url, path, **kwargs):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"bad")
    monkeypatch.setattr(release, "fetch", changed)
    with pytest.raises(ValueError, match="checksum"):
        release.download_release("https://example.com/v2/model", tmp_path,
                                 manifest, release_cfg, COMMIT)
