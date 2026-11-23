"""Move data and models between this machine and Google Cloud Storage.

    python -m src.data.storage upload     # push data/processed/* to the bucket (needs gcloud auth)
    python -m src.data.storage download   # pull it back (no auth needed if the bucket is public)
    python -m src.data.storage upload-model

Downloads deliberately go through the public HTTPS endpoint rather than the
GCS client, so anyone cloning the repo (or a grader) can run the pipeline
without a Google Cloud account.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import requests

from src.config import load_config, resolve

log = logging.getLogger("storage")


def public_url(cfg: dict, name: str) -> str:
    s = cfg["storage"]
    return f"https://storage.googleapis.com/{s['bucket']}/{s['prefix']}/{name}"


def blob_name(cfg: dict, name: str, *, prefix: str | None = None) -> str:
    base = cfg["storage"]["prefix"] if prefix is None else prefix
    return f"{base}/{name}"


def download_file(url: str, dest: Path, chunk: int = 1 << 20) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            for block in r.iter_content(chunk):
                f.write(block)
        tmp.replace(dest)
    log.info("downloaded %s -> %s (%.1f MB)", url, dest, dest.stat().st_size / 1e6)
    return dest


def upload_file(cfg: dict, local: Path, name: str, *, prefix: str | None = None) -> str:
    from google.cloud import storage  # imported lazily: only uploads need credentials

    client = storage.Client()
    blob = client.bucket(cfg["storage"]["bucket"]).blob(blob_name(cfg, name, prefix=prefix))
    blob.upload_from_filename(str(local))
    uri = f"gs://{cfg['storage']['bucket']}/{blob.name}"
    log.info("uploaded %s -> %s", local, uri)
    return uri


def ensure_processed_data(cfg: dict, force: bool = False) -> tuple[Path, Path]:
    """Return local paths to markets/prices parquet, downloading from GCS if missing."""
    files = cfg["storage"]["files"]
    out_dir = resolve(cfg["ingest"]["processed_dir"])
    paths = []
    for key in ("markets", "prices"):
        path = out_dir / files[key]
        if force or not path.exists():
            download_file(public_url(cfg, files[key]), path)
        paths.append(path)
    return paths[0], paths[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["upload", "download", "upload-model"])
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    cfg = load_config(args.config)
    files = cfg["storage"]["files"]

    if args.action == "download":
        ensure_processed_data(cfg, force=True)
    elif args.action == "upload":
        out_dir = resolve(cfg["ingest"]["processed_dir"])
        for key in ("markets", "prices"):
            upload_file(cfg, out_dir / files[key], files[key])
    elif args.action == "upload-model":
        model_dir = resolve(cfg["output"]["model_dir"])
        # Model versions can advance without relocating the cleaned v1 dataset.
        prefix = cfg["storage"].get("model_prefix", cfg["storage"]["prefix"])
        upload_file(cfg, model_dir / "model.joblib", files["model"], prefix=prefix)
        upload_file(cfg, model_dir / "model_card.json", files["model_card"], prefix=prefix)


if __name__ == "__main__":
    main()
