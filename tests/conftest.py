"""Shared fixtures: a small synthetic market dataset so tests never hit the network."""

from __future__ import annotations

import copy

import numpy as np
import pandas as pd
import pytest

from src.config import load_config

DAY = 86400


@pytest.fixture
def cfg():
    c = copy.deepcopy(load_config())
    c["features"]["text_max_features"] = 20
    c["model"]["xgboost"]["n_estimators"] = 20
    return c


@pytest.fixture
def synthetic_markets():
    """60 events x 2 markets. YES markets drift up toward 1, NO markets drift down."""
    rng = np.random.default_rng(0)
    base = pd.Timestamp("2025-01-01", tz="UTC")
    markets, prices = [], []
    words = ["bitcoin above", "election winner", "fed cut rates", "team wins final"]
    for e in range(60):
        start = base + pd.Timedelta(days=int(e * 3))
        end = start + pd.Timedelta(days=45)
        for k in range(2):
            mid = f"m{e}_{k}"
            yes = int(rng.random() < 0.3)
            markets.append({
                "market_id": mid, "slug": mid,
                "question": f"Will {words[(e + k) % 4]} happen by March {e}?",
                "event_id": f"e{e}", "event_slug": f"e{e}", "event_title": f"Event {e}",
                "event_n_markets": 2, "tags": ["Crypto"] if e % 2 else ["Politics"],
                "neg_risk": bool(k), "start_date": start, "end_date": end,
                "closed_time": end + pd.Timedelta(hours=6), "volume": 1e5,
                "resolved_yes": yes,
            })
            p0 = rng.uniform(0.2, 0.6)
            target = 0.9 if yes else 0.1
            for d in range(46):
                frac = d / 45
                p = np.clip(p0 + (target - p0) * frac + rng.normal(0, 0.03), 0.01, 0.99)
                prices.append({"market_id": mid, "ts": start + pd.Timedelta(days=d),
                               "price": float(p)})
    return pd.DataFrame(markets), pd.DataFrame(prices)
