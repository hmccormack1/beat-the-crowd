"""Load config.yaml into a plain dict (with a couple of convenience helpers)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config.yaml"


def load_config(path: str | os.PathLike | None = None) -> dict[str, Any]:
    path = Path(path or os.environ.get("BTC_CONFIG", DEFAULT_CONFIG))
    with open(path) as f:
        cfg = yaml.safe_load(f)

    # Allow the bucket to be overridden without editing the file (handy in CI / Cloud Run).
    if bucket := os.environ.get("BTC_BUCKET"):
        cfg["storage"]["bucket"] = bucket
    return cfg


def resolve(path: str | os.PathLike) -> Path:
    """Paths in the config are relative to the repo root."""
    p = Path(path)
    return p if p.is_absolute() else ROOT / p
