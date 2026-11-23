"""Turn a market (metadata + price history) into a feature row.

The key idea is the *snapshot*: we freeze a market at time `as_of` and only
use information that existed at that moment. In training, `as_of` is N days
before the market's scheduled end date. In the live API, `as_of` is "now".
Both paths go through `snapshot_features`, so the model never sees features
computed differently at serving time than at training time.
"""

from __future__ import annotations

import math
import re

import numpy as np
import pandas as pd

NUMERIC_FEATURES = [
    "crowd_p", "crowd_logit",
    "p_change_1d", "p_change_7d", "p_change_30d",
    "p_max_to_date", "p_min_to_date", "p_range_7d",
    "volatility_7d", "volatility_all",
    "days_to_end", "log_days_to_end", "market_age_days", "frac_life_elapsed",
    "n_price_points", "event_n_markets", "log_event_n_markets", "neg_risk",
    "q_len_words", "q_has_deadline", "q_has_threshold", "q_has_vs", "q_has_number",
]
CATEGORICAL_FEATURES = ["category"]
TEXT_FEATURE = "question"
ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES + [TEXT_FEATURE]

# Polymarket tags are free-form and plentiful; collapse them into a few buckets.
# Order matters: the first bucket with a matching tag wins.
CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("crypto", ("crypto", "bitcoin", "ethereum", "solana", "xrp", "memecoin", "airdrop")),
    ("sports", ("sports", "nba", "nfl", "mlb", "nhl", "soccer", "football", "tennis", "ufc",
                "f1", "formula 1", "golf", "cricket", "esports", "boxing", "ncaa", "olympics")),
    ("elections", ("elections", "election", "primaries", "polls", "midterms")),
    ("politics", ("politics", "trump", "congress", "senate", "us government", "courts",
                  "supreme court", "cabinet", "biden", "gov shutdown")),
    ("geopolitics", ("geopolitics", "world", "ukraine", "russia", "israel", "middle east",
                     "china", "iran", "gaza", "war", "foreign policy")),
    ("finance", ("finance", "economy", "fed", "stocks", "commodities", "inflation",
                 "interest rates", "business", "earnings", "ipo")),
    ("tech", ("tech", "ai", "openai", "science", "space", "elon musk")),
    ("culture", ("culture", "pop culture", "movies", "music", "awards", "celebrities",
                 "tv", "video games", "youtube", "twitter", "mentions")),
]

_DEADLINE_RE = re.compile(r"\b(by|before|until|end of)\b", re.I)
_THRESHOLD_RE = re.compile(r"(\$|\babove\b|\bbelow\b|\bhit\b|\breach\b|\bover\b|\bunder\b|%)", re.I)
_VS_RE = re.compile(r"\b(vs\.?|versus|beat)\b", re.I)
_NUMBER_RE = re.compile(r"\d")

DAY = 86400.0


def categorize(tags: list[str] | None) -> str:
    lowered = {t.lower() for t in (tags or [])}
    for name, keys in CATEGORY_RULES:
        if lowered & set(keys):
            return name
    return "other"


def _logit(p: float, eps: float = 1e-3) -> float:
    p = min(max(p, eps), 1 - eps)
    return math.log(p / (1 - p))


def _price_at(ts: np.ndarray, p: np.ndarray, t: float) -> float:
    """Last observed price at or before time t (falls back to the first price)."""
    idx = np.searchsorted(ts, t, side="right") - 1
    return float(p[max(idx, 0)])


def snapshot_features(
    ts: np.ndarray,
    prices: np.ndarray,
    as_of: float,
    start: float,
    end: float,
    question: str,
    tags: list[str] | None,
    event_n_markets: int,
    neg_risk: bool,
) -> dict | None:
    """Features for one market frozen at `as_of` (all times in unix seconds).

    `ts`/`prices` must be sorted by time. Anything after `as_of` is ignored.
    Returns None if there's not enough history to say anything.
    """
    mask = ts <= as_of
    ts, prices = ts[mask], prices[mask]
    if len(prices) < 2:
        return None

    p_now = float(prices[-1])
    diffs = np.diff(prices)
    last_week = prices[ts >= as_of - 7 * DAY]
    week_diffs = np.diff(last_week) if len(last_week) > 1 else np.array([0.0])

    life = max(end - start, DAY)
    days_to_end = max((end - as_of) / DAY, 0.0)
    q = question or ""

    return {
        "crowd_p": p_now,
        "crowd_logit": _logit(p_now),
        "p_change_1d": p_now - _price_at(ts, prices, as_of - 1 * DAY),
        "p_change_7d": p_now - _price_at(ts, prices, as_of - 7 * DAY),
        "p_change_30d": p_now - _price_at(ts, prices, as_of - 30 * DAY),
        "p_max_to_date": float(prices.max()),
        "p_min_to_date": float(prices.min()),
        "p_range_7d": float(last_week.max() - last_week.min()) if len(last_week) else 0.0,
        "volatility_7d": float(np.std(week_diffs)),
        "volatility_all": float(np.std(diffs)),
        "days_to_end": days_to_end,
        "log_days_to_end": math.log1p(days_to_end),
        "market_age_days": max((as_of - start) / DAY, 0.0),
        "frac_life_elapsed": float(np.clip((as_of - start) / life, 0, 1)),
        "n_price_points": float(len(prices)),
        "event_n_markets": float(event_n_markets or 1),
        "log_event_n_markets": math.log(max(event_n_markets or 1, 1)),
        "neg_risk": float(bool(neg_risk)),
        "q_len_words": float(len(q.split())),
        "q_has_deadline": float(bool(_DEADLINE_RE.search(q))),
        "q_has_threshold": float(bool(_THRESHOLD_RE.search(q))),
        "q_has_vs": float(bool(_VS_RE.search(q))),
        "q_has_number": float(bool(_NUMBER_RE.search(q))),
        "category": categorize(tags),
        "question": q,
    }


def build_training_set(markets: pd.DataFrame, prices: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """One row per (market, horizon) snapshot that was still open at snapshot time."""
    fc = cfg["features"]
    horizons = fc["snapshot_horizons_days"]
    min_hist = fc["min_history_days"] * DAY

    grouped = {mid: g for mid, g in prices.groupby("market_id", sort=False)}
    rows = []
    for m in markets.itertuples(index=False):
        g = grouped.get(m.market_id)
        if g is None:
            continue
        ts = g["ts"].astype("int64").to_numpy() / 1e9
        p = g["price"].to_numpy(dtype=float)
        start, end = m.start_date.timestamp(), m.end_date.timestamp()
        closed = m.closed_time.timestamp() if pd.notna(m.closed_time) else math.inf

        for h in horizons:
            as_of = end - h * DAY
            # The market has to exist, have some history, and NOT be resolved yet,
            # otherwise the snapshot would leak the answer.
            if as_of < start + min_hist or as_of >= closed or as_of < ts[0]:
                continue
            feats = snapshot_features(ts, p, as_of, start, end, m.question, list(m.tags),
                                      m.event_n_markets, m.neg_risk)
            if feats is None:
                continue
            feats.update({
                "market_id": m.market_id,
                "event_id": m.event_id,
                "end_date": m.end_date,
                "horizon_days": h,
                "target": int(m.resolved_yes),
            })
            rows.append(feats)

    return pd.DataFrame(rows)
