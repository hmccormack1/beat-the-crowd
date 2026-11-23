"""End-to-end training run, tracked in MLflow.

    python -m src.models.train [--config config.yaml] [--model-type xgboost|logistic_regression]

1. pull cleaned data from cloud storage (skipped if already on disk)
2. build snapshot features
3. split by event, in time order
4. fit, evaluate against the crowd baseline, make plots
5. log params / metrics / plots / model to MLflow and save models/model.joblib
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import subprocess
from datetime import datetime, timezone

import joblib
import mlflow
import numpy as np
import pandas as pd

from src.config import load_config, resolve
from src.data.storage import ensure_processed_data
from src.features.build import ALL_FEATURES, build_training_set
from src.models import evaluate as ev
from src.models.model import feature_names, fit_model
from src.models.split import split_by_event

log = logging.getLogger("train")


def _flatten(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, f"{key}."))
        else:
            out[key] = v
    return out


def _git_commit() -> str:
    # Container training has no .git directory; deployment supplies the exact
    # checked-out revision explicitly so the published card retains provenance.
    if commit := os.environ.get("BTC_SOURCE_COMMIT"):
        return commit
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                       stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def contested(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Keep snapshots where the crowd is genuinely unsure.

    Most snapshots are long-shot candidates priced at 0.1% (or done deals at
    99.9%). Including them makes every metric look near-perfect for the model
    AND the crowd, and says nothing about the interesting cases.
    """
    lo, hi = cfg["features"]["min_crowd_p"], cfg["features"]["max_crowd_p"]
    return df[(df["crowd_p"] >= lo) & (df["crowd_p"] <= hi)].reset_index(drop=True)


def run(cfg: dict) -> dict:
    np.random.seed(cfg["project"]["seed"])
    reports = resolve(cfg["output"]["reports_dir"])
    model_dir = resolve(cfg["output"]["model_dir"])
    reports.mkdir(parents=True, exist_ok=True)
    model_dir.mkdir(parents=True, exist_ok=True)

    # 1. data
    markets_path, prices_path = ensure_processed_data(cfg)
    markets = pd.read_parquet(markets_path)
    prices = pd.read_parquet(prices_path)
    log.info("loaded %d markets, %d price points", len(markets), len(prices))

    # 2. features
    all_snapshots = build_training_set(markets, prices, cfg)
    data = contested(all_snapshots, cfg)
    log.info("built %d snapshots; %d (%.0f%%) are contested and used for modelling",
             len(all_snapshots), len(data), 100 * len(data) / max(len(all_snapshots), 1))

    # 3. split
    train, val, test = split_by_event(data, cfg)
    log.info("split sizes  train=%d  val=%d  test=%d", len(train), len(val), len(test))

    mlflow.set_tracking_uri(cfg["mlflow"]["tracking_uri"])
    mlflow.set_experiment(cfg["mlflow"]["experiment_name"])
    run_name = cfg["mlflow"]["run_name"] or (
        f"{cfg['model']['type']}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}")

    with mlflow.start_run(run_name=run_name) as active:
        config_hash = hashlib.sha1(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:10]
        mlflow.log_params({k: str(v)[:250] for k, v in _flatten(
            {k: cfg[k] for k in ("features", "split", "model", "ingest")}).items()})
        mlflow.set_tags({"git_commit": _git_commit(), "config_hash": config_hash})
        mlflow.log_metrics({"data_n_markets": data["market_id"].nunique(),
                            "data_n_snapshots_all": len(all_snapshots),
                            "data_n_snapshots": len(data),
                            "data_n_train": len(train), "data_n_val": len(val),
                            "data_n_test": len(test)})

        # 4. fit + evaluate
        model = fit_model(cfg, train, val)
        threshold = cfg["serving"]["edge_threshold"]
        metrics = {}
        for name, df in (("train", train), ("val", val), ("test", test)):
            p = model.predict_proba(df[ALL_FEATURES])[:, 1]
            metrics.update(ev.evaluate(df, p, threshold, name))
        mlflow.log_metrics(metrics)

        test_p = model.predict_proba(test[ALL_FEATURES])[:, 1]
        horizon = ev.by_horizon(test, test_p)
        horizon.to_csv(reports / "test_by_horizon.csv", index=False)

        plots = [
            ev.plot_calibration(test, test_p, reports / "calibration.png"),
            ev.plot_longshot_bias(all_snapshots, reports / "longshot_bias.png"),
            ev.plot_brier_by_horizon(horizon, reports / "brier_by_horizon.png"),
        ]
        clf = model.named_steps["clf"]
        if hasattr(clf, "feature_importances_"):
            plots.append(ev.plot_feature_importance(
                feature_names(model), clf.feature_importances_, reports / "feature_importance.png"))
        for path in plots + [reports / "test_by_horizon.csv"]:
            mlflow.log_artifact(str(path), artifact_path="reports")
        # Persist the effective config, including custom files and CLI overrides.
        mlflow.log_dict(cfg, "config/config.yaml")

        # 5. persist
        card = {
            "model_type": cfg["model"]["type"],
            "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "git_commit": _git_commit(),
            "config_hash": config_hash,
            "mlflow_run_id": active.info.run_id,
            "features": ALL_FEATURES,
            "n_markets": int(data["market_id"].nunique()),
            "n_snapshots": int(len(data)),
            "test_period": [str(test["end_date"].min().date()), str(test["end_date"].max().date())],
            "metrics": {k: round(v, 4) for k, v in metrics.items() if k.startswith("test_")},
        }
        joblib.dump(model, model_dir / "model.joblib")
        (model_dir / "model_card.json").write_text(json.dumps(card, indent=2))
        mlflow.log_artifact(str(model_dir / "model_card.json"), artifact_path="model")
        mlflow.sklearn.log_model(
            model, name="model", input_example=test[ALL_FEATURES].head(3),
            skops_trusted_types=["xgboost.core.Booster", "xgboost.sklearn.XGBClassifier"])

    for split in ("val", "test"):
        log.info("%-4s model brier=%.4f  crowd brier=%.4f  skill=%+.3f (95%% CI %+.3f to %+.3f)",
                 split, metrics[f"{split}_model_brier"], metrics[f"{split}_crowd_brier"],
                 metrics[f"{split}_brier_skill_vs_crowd"], metrics[f"{split}_brier_skill_ci_low"],
                 metrics[f"{split}_brier_skill_ci_high"])
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None)
    parser.add_argument("--model-type", choices=["xgboost", "logistic_regression"], default=None,
                        help="override model.type from the config")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")

    cfg = load_config(args.config)
    if args.model_type:
        cfg["model"]["type"] = args.model_type
    run(cfg)


if __name__ == "__main__":
    main()
