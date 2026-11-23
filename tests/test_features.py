import numpy as np
import pandas as pd
import pytest

from src.features.build import ALL_FEATURES, build_training_set, categorize, snapshot_features

DAY = 86400.0


def _series():
    ts = np.arange(0, 20) * DAY
    p = np.linspace(0.2, 0.8, 20)
    return ts, p


def test_snapshot_ignores_future_prices():
    """The most important property: nothing after as_of can leak into features."""
    ts, p = _series()
    as_of = ts[9]
    a = snapshot_features(ts, p, as_of, 0, 30 * DAY, "Will X happen?", [], 1, False)
    p_tampered = p.copy()
    p_tampered[10:] = 0.99  # change the future
    b = snapshot_features(ts, p_tampered, as_of, 0, 30 * DAY, "Will X happen?", [], 1, False)
    assert a == b
    assert a["crowd_p"] == p[9]


def test_snapshot_needs_history():
    ts, p = _series()
    assert snapshot_features(ts, p, ts[0], 0, 30 * DAY, "q", [], 1, False) is None


def test_snapshot_has_every_model_feature():
    ts, p = _series()
    feats = snapshot_features(ts, p, ts[-1], 0, 30 * DAY, "Will BTC hit $100k by June?",
                              ["Crypto"], 3, True)
    assert set(ALL_FEATURES) <= set(feats)
    assert feats["q_has_threshold"] == 1.0 and feats["q_has_deadline"] == 1.0
    assert feats["category"] == "crypto"
    assert 0 <= feats["frac_life_elapsed"] <= 1


def test_categorize():
    assert categorize(["NBA", "Sports"]) == "sports"
    assert categorize(["Bitcoin"]) == "crypto"
    assert categorize(["something odd"]) == "other"
    assert categorize(None) == "other"


def test_training_set_skips_snapshots_after_resolution(cfg, synthetic_markets):
    markets, prices = synthetic_markets
    # Resolve one market early: only horizons that are still before close should survive.
    markets.loc[0, "closed_time"] = markets.loc[0, "end_date"] - np.timedelta64(5, "D")
    df = build_training_set(markets, prices, cfg)
    first = df[df["market_id"] == markets.loc[0, "market_id"]]
    assert set(first["horizon_days"]) == {7, 14, 30}
    assert df["target"].isin([0, 1]).all()


@pytest.mark.parametrize("unit", ["s", "ms", "us", "ns"])
def test_training_snapshots_preserve_time_units_and_match_serving(cfg, unit):
    """Cloud Parquet timestamps must exclude the future just like live inputs."""
    cfg["features"]["snapshot_horizons_days"] = [7]
    start = pd.Timestamp("2026-01-01", tz="UTC")
    end = pd.Timestamp("2026-01-12", tz="UTC")
    as_of = end - pd.Timedelta(days=7)
    dates = pd.to_datetime([
        "2026-01-01", "2026-01-02", "2026-01-05",
        "2026-01-06", "2026-01-12",
    ], utc=True)
    prices = pd.DataFrame({
        "market_id": ["example"] * len(dates),
        "ts": pd.Series(dates).dt.as_unit(unit),
        "price": [.2, .3, .4, .9, .999],
    })
    markets = pd.DataFrame([{
        "market_id": "example", "event_id": "event",
        "question": "Will the Fed cut rates by January 12?",
        "start_date": start, "end_date": end, "closed_time": end,
        "tags": ["Fed"], "event_n_markets": 1, "neg_risk": False,
        "resolved_yes": 1,
    }])

    row = build_training_set(markets, prices, cfg).iloc[0]
    assert row["crowd_p"] == .4
    assert row["n_price_points"] == 3

    # Serving receives true Unix seconds directly, without a pandas dtype.
    live_features = snapshot_features(
        np.array([date.timestamp() for date in dates]),
        prices["price"].to_numpy(), as_of.timestamp(), start.timestamp(),
        end.timestamp(), markets.iloc[0]["question"], ["Fed"], 1, False,
    )
    assert row[ALL_FEATURES].to_dict() == live_features

    # Changing resolved/future prices cannot change any historical feature.
    tampered = prices.copy()
    tampered.loc[tampered["ts"] > as_of, "price"] = .01
    rebuilt = build_training_set(markets, tampered, cfg).iloc[0]
    assert row[ALL_FEATURES].to_dict() == rebuilt[ALL_FEATURES].to_dict()
