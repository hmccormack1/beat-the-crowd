"""Metrics and plots. Everything is reported for the model AND for the crowd
(the market price itself), because "beat the crowd" is the whole question.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score  # noqa: E402

MODEL_COLOR = "#2563eb"
CROWD_COLOR = "#f97316"


def expected_calibration_error(y: np.ndarray, p: np.ndarray, n_bins: int = 10) -> float:
    bins = np.clip((p * n_bins).astype(int), 0, n_bins - 1)
    ece = 0.0
    for b in range(n_bins):
        mask = bins == b
        if mask.any():
            ece += mask.mean() * abs(y[mask].mean() - p[mask].mean())
    return float(ece)


def paper_trading_roi(y: np.ndarray, model_p: np.ndarray, crowd_p: np.ndarray,
                      threshold: float) -> dict:
    """If we put $1 on whichever side the model likes whenever it disagrees with
    the crowd by more than `threshold`, what happens? Ignores fees and slippage,
    so treat it as an upper bound, not a trading strategy."""
    eps = 1e-3
    crowd_p = np.clip(crowd_p, eps, 1 - eps)
    buy_yes = model_p > crowd_p + threshold
    buy_no = model_p < crowd_p - threshold
    pnl = np.where(buy_yes, np.where(y == 1, 1 / crowd_p - 1, -1.0), 0.0)
    pnl += np.where(buy_no, np.where(y == 0, 1 / (1 - crowd_p) - 1, -1.0), 0.0)
    n_bets = int(buy_yes.sum() + buy_no.sum())
    return {
        "n_bets": n_bets,
        "bet_rate": n_bets / max(len(y), 1),
        "roi": float(pnl.sum() / n_bets) if n_bets else 0.0,
    }


def score(y: np.ndarray, p: np.ndarray) -> dict:
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return {
        "brier": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, p, labels=[0, 1])),
        "auc": float(roc_auc_score(y, p)) if len(np.unique(y)) > 1 else float("nan"),
        "ece": expected_calibration_error(y, p),
        "accuracy": float(((p >= 0.5) == y).mean()),
    }


def bootstrap_skill(df: pd.DataFrame, model_p: np.ndarray, n_boot: int = 1000,
                    seed: int = 0) -> tuple[float, float]:
    """95% interval for Brier skill vs. the crowd, resampling whole *events*.

    Markets in one event move together (one candidate wins, the rest lose), so
    resampling rows would make the estimate look far more certain than it is.
    """
    rng = np.random.default_rng(seed)
    tmp = pd.DataFrame({"event": df["event_id"].to_numpy(), "y": df["target"].to_numpy(),
                        "m": model_p, "c": df["crowd_p"].to_numpy()})
    tmp["m_err"] = (tmp["m"] - tmp["y"]) ** 2
    tmp["c_err"] = (tmp["c"] - tmp["y"]) ** 2
    per_event = tmp.groupby("event")[["m_err", "c_err"]].agg(["sum"]).to_numpy()
    skills = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(per_event), len(per_event))
        m_sum, c_sum = per_event[idx].sum(axis=0)
        skills.append(1 - m_sum / c_sum)
    lo, hi = np.percentile(skills, [2.5, 97.5])
    return float(lo), float(hi)


def evaluate(df: pd.DataFrame, model_p: np.ndarray, edge_threshold: float, prefix: str) -> dict:
    y = df["target"].to_numpy()
    crowd = df["crowd_p"].to_numpy()
    m, c = score(y, model_p), score(y, crowd)
    out = {f"{prefix}_model_{k}": v for k, v in m.items()}
    out.update({f"{prefix}_crowd_{k}": v for k, v in c.items()})
    out[f"{prefix}_brier_skill_vs_crowd"] = 1 - m["brier"] / c["brier"]
    lo, hi = bootstrap_skill(df, model_p)
    out[f"{prefix}_brier_skill_ci_low"] = lo
    out[f"{prefix}_brier_skill_ci_high"] = hi
    out.update({f"{prefix}_trade_{k}": v for k, v in
                paper_trading_roi(y, model_p, crowd, edge_threshold).items()})
    out[f"{prefix}_n_rows"] = len(df)
    out[f"{prefix}_base_rate"] = float(y.mean())
    return out


def by_horizon(df: pd.DataFrame, model_p: np.ndarray) -> pd.DataFrame:
    tmp = df[["horizon_days", "target", "crowd_p"]].assign(model_p=model_p)
    rows = []
    for h, g in tmp.groupby("horizon_days"):
        rows.append({
            "horizon_days": h,
            "n": len(g),
            "model_brier": brier_score_loss(g["target"], g["model_p"]),
            "crowd_brier": brier_score_loss(g["target"], g["crowd_p"]),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------

def _reliability(y, p, n_bins=10):
    bins = np.clip((p * n_bins).astype(int), 0, n_bins - 1)
    xs, ys, ns = [], [], []
    for b in range(n_bins):
        mask = bins == b
        if mask.sum() >= 10:
            xs.append(p[mask].mean())
            ys.append(y[mask].mean())
            ns.append(mask.sum())
    return np.array(xs), np.array(ys), np.array(ns)


def plot_calibration(df: pd.DataFrame, model_p: np.ndarray, path: Path) -> Path:
    y = df["target"].to_numpy()
    fig, ax = plt.subplots(figsize=(5.5, 5.5))
    ax.plot([0, 1], [0, 1], ls="--", c="#9ca3af", lw=1, label="perfectly calibrated")
    for p, label, color in [(df["crowd_p"].to_numpy(), "crowd (market price)", CROWD_COLOR),
                            (model_p, "model", MODEL_COLOR)]:
        xs, ys, _ = _reliability(y, p)
        ax.plot(xs, ys, marker="o", c=color, lw=2, label=label)
    ax.set_xlabel("predicted probability of YES")
    ax.set_ylabel("fraction that actually resolved YES")
    ax.set_title("Calibration on the test set")
    ax.legend(frameon=False, loc="upper left")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_longshot_bias(df: pd.DataFrame, path: Path) -> Path:
    """How often do markets priced at X% actually happen? (crowd only, all data)."""
    y, p = df["target"].to_numpy(), df["crowd_p"].to_numpy()
    edges = np.array([0, .02, .05, .1, .2, .35, .5, .65, .8, .9, .95, .98, 1.0])
    idx = np.clip(np.digitize(p, edges) - 1, 0, len(edges) - 2)
    xs, ys, ns = [], [], []
    for b in range(len(edges) - 1):
        mask = idx == b
        if mask.sum() >= 20:
            xs.append(p[mask].mean())
            ys.append(y[mask].mean())
            ns.append(mask.sum())
    fig, ax = plt.subplots(figsize=(6, 4.5))
    ax.plot([0, 1], [0, 1], ls="--", c="#9ca3af", lw=1)
    ax.scatter(xs, ys, s=np.sqrt(ns) * 4, c=CROWD_COLOR, alpha=0.85, zorder=3)
    ax.plot(xs, ys, c=CROWD_COLOR, lw=1.5)
    ax.set_xlabel("market price (crowd's implied probability)")
    ax.set_ylabel("realized YES rate")
    ax.set_title("Is the crowd calibrated? (dot size = # snapshots)")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_feature_importance(names: list[str], importances: np.ndarray, path: Path,
                            top: int = 20) -> Path:
    order = np.argsort(importances)[::-1][:top][::-1]
    labels = [names[i].split("__", 1)[-1] for i in order]
    fig, ax = plt.subplots(figsize=(6, 0.3 * len(order) + 1))
    ax.barh(labels, importances[order], color=MODEL_COLOR)
    ax.set_title(f"Top {len(order)} features (gain)")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_brier_by_horizon(table: pd.DataFrame, path: Path) -> Path:
    x = np.arange(len(table))
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(x - 0.2, table["crowd_brier"], 0.4, label="crowd", color=CROWD_COLOR)
    ax.bar(x + 0.2, table["model_brier"], 0.4, label="model", color=MODEL_COLOR)
    ax.set_xticks(x, [f"{h}d" for h in table["horizon_days"]])
    ax.set_xlabel("days before scheduled end")
    ax.set_ylabel("Brier score (lower is better)")
    ax.set_title("Test error by forecast horizon")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path
