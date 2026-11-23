"""Loads the trained model and scores markets, either from raw inputs or live from Polymarket."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from src.config import resolve
from src.data import polymarket as pm
from src.data.storage import download_file
from src.features.build import ALL_FEATURES, snapshot_features

log = logging.getLogger("predictor")

MAX_MARKETS_PER_EVENT = 12
HISTORY_POINTS_RETURNED = 90


def _ts(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    ts = pd.Timestamp(str(value).replace(" ", "T").replace("+00", "+00:00")
                      .replace("+00:00:00", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.timestamp()


class Predictor:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.threshold = cfg["serving"]["edge_threshold"]
        self.max_horizon = max(cfg["features"]["snapshot_horizons_days"])
        self.p_range = (cfg["features"]["min_crowd_p"], cfg["features"]["max_crowd_p"])
        path = resolve(cfg["serving"]["model_path"])
        if not path.exists():
            log.info("model not found locally, downloading from %s", cfg["serving"]["model_url"])
            download_file(cfg["serving"]["model_url"], path)
        self.model = joblib.load(path)
        card_path = Path(path).with_name("model_card.json")
        self.card = json.loads(card_path.read_text()) if card_path.exists() else {}

    # ------------------------------------------------------------------
    def verdict(self, model_p: float, crowd_p: float) -> str:
        edge = model_p - crowd_p
        if edge > self.threshold:
            return "YES looks underpriced"
        if edge < -self.threshold:
            return "YES looks overpriced"
        return "agrees with the crowd"

    def score_features(self, feats: dict) -> dict:
        row = pd.DataFrame([{k: feats[k] for k in ALL_FEATURES}])
        model_p = float(self.model.predict_proba(row)[:, 1][0])
        crowd_p = float(feats["crowd_p"])
        return {
            "model_probability": round(model_p, 4),
            "crowd_probability": round(crowd_p, 4),
            "edge": round(model_p - crowd_p, 4),
            "verdict": self.verdict(model_p, crowd_p),
            "warnings": self.warnings(feats),
        }

    def warnings(self, feats: dict) -> list[str]:
        """Be upfront when a market looks nothing like what the model was trained on."""
        out = []
        lo, hi = self.p_range
        if not lo <= feats["crowd_p"] <= hi:
            out.append(f"The crowd is already near-certain (outside {lo:.0%}-{hi:.0%}); "
                       "the model was only trained on contested markets.")
        if feats["days_to_end"] > self.max_horizon * 1.5:
            out.append(f"This market ends in {feats['days_to_end']:.0f} days; the model was "
                       f"trained on snapshots at most {self.max_horizon} days before the end.")
        if feats["n_price_points"] < 5:
            out.append("Very little price history so far.")
        return out

    def predict_raw(self, *, question: str, price_history: list[dict], start_date, end_date,
                    tags: list[str], event_n_markets: int, neg_risk: bool,
                    as_of=None) -> dict:
        history = sorted(price_history, key=lambda h: h["t"])
        ts = np.array([float(h["t"]) for h in history])
        p = np.array([float(h["p"]) for h in history])
        as_of_ts = _ts(as_of) if as_of is not None else time.time()
        feats = snapshot_features(ts, p, as_of_ts, _ts(start_date), _ts(end_date), question,
                                  tags, event_n_markets, neg_risk)
        if feats is None:
            raise ValueError("need at least 2 price points at or before as_of")
        out = self.score_features(feats)
        out["features"] = {k: v for k, v in feats.items() if k != "question"}
        return out

    # ------------------------------------------------------------------
    def predict_url(self, url_or_slug: str) -> dict:
        event_slug, market_slug = pm.parse_polymarket_url(url_or_slug)
        event = pm.get_event_by_slug(event_slug) if event_slug else None
        if event is None and (market_slug or event_slug):
            market = pm.get_market_by_slug(market_slug or event_slug)
            if market and market.get("events"):
                event = pm.get_event_by_slug(market["events"][0].get("slug")) or market["events"][0]
                event.setdefault("markets", [market])
                market_slug = market["slug"]
        if event is None:
            raise LookupError(f"couldn't find a Polymarket event or market for '{url_or_slug}'")

        markets = [pm.normalize_market(m, event) for m in event.get("markets") or []]
        markets = [m for m in markets if m and not m["closed"]]
        if market_slug:
            markets = [m for m in markets if m["slug"] == market_slug]
        if not markets:
            raise LookupError("no open Yes/No markets found at that link")
        markets = sorted(markets, key=lambda m: m["volume"], reverse=True)[:MAX_MARKETS_PER_EVENT]

        results = []
        now = time.time()
        for m in markets:
            history = pm.get_price_history(m["yes_token_id"])
            if len(history) < 2:
                continue
            ts = np.array([h["t"] for h in history], dtype=float)
            p = np.array([h["p"] for h in history], dtype=float)
            feats = snapshot_features(ts, p, now, _ts(m["start_date"]), _ts(m["end_date"]),
                                      m["question"], m["tags"], m["event_n_markets"], m["neg_risk"])
            if feats is None:
                continue
            scored = self.score_features(feats)
            results.append({
                "question": m["question"],
                "slug": m["slug"],
                "end_date": m["end_date"],
                "volume_usd": round(m["volume"], 2),
                "category": feats["category"],
                "days_to_end": round(feats["days_to_end"], 2),
                **scored,
                "price_history": history[-HISTORY_POINTS_RETURNED:],
            })

        return {
            "event_title": event.get("title"),
            "event_slug": event.get("slug"),
            "scored_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "markets": results,
        }

    def trending(self, limit: int = 10) -> list[dict]:
        """Busiest open events, skipping ones that end within a few days (mostly
        individual sports games, which look nothing like the training data)."""
        out = []
        soon = time.time() + 3 * 86400
        for e in pm.list_active_events(limit=limit * 5):
            if not e.get("endDate") or _ts(e["endDate"]) < soon:
                continue
            if len(out) == limit:
                break
            out.append({
                "title": e.get("title"),
                "slug": e.get("slug"),
                "url": f"https://polymarket.com/event/{e.get('slug')}",
                "volume_24h": e.get("volume24hr"),
                "end_date": e.get("endDate"),
                "n_markets": len(e.get("markets") or []),
            })
        return out
