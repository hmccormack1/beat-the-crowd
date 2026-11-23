"""Thin client for Polymarket's public, key-less APIs.

Two services matter here:
  * Gamma  (gamma-api.polymarket.com): market + event metadata, resolution outcome
  * CLOB   (clob.polymarket.com):       price history for an outcome token

The same functions are used for building the training set (closed markets) and
for scoring a live market in the API, which keeps training and serving consistent.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import requests

GAMMA_URL = "https://gamma-api.polymarket.com"
CLOB_URL = "https://clob.polymarket.com"

_session = requests.Session()
_session.headers.update({"User-Agent": "beat-the-crowd/0.1 (course project)"})


def _get(url: str, params: dict | None = None, retries: int = 6, timeout: int = 30) -> Any:
    """GET with retries. Backs off on rate limits (429) and server errors."""
    for attempt in range(retries):
        wait = 2 * 2**attempt
        try:
            r = _session.get(url, params=params, timeout=timeout)
            if r.status_code == 429 or r.status_code >= 500:
                wait = max(wait, float(r.headers.get("Retry-After", 0) or 0))
                raise requests.HTTPError(f"{r.status_code} from {url}")
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError):
            if attempt == retries - 1:
                raise
            time.sleep(wait)


def _loads(value: Any) -> Any:
    """Gamma returns some list fields as JSON-encoded strings."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

def list_closed_events(cursor: str | None, limit: int, end_date_min: str, end_date_max: str,
                       min_volume: float = 0, exclude_tag_ids: list[str] | None = None,
                       base_url: str = GAMMA_URL) -> tuple[list[dict], str | None]:
    """One page of closed events, plus the cursor for the next page (None when done).

    Gamma caps plain offset pagination at ~2,000 rows, so we use the keyset
    endpoint. Events come newest-first by end date, so a market cap keeps the
    most recent markets rather than the oldest.
    """
    params = {
        "closed": "true",
        "limit": limit,
        "order": "endDate",
        "ascending": "false",
        "end_date_min": end_date_min,
        "end_date_max": end_date_max,
    }
    if cursor:
        params["after_cursor"] = cursor
    # requests encodes a list value as a repeated query param (?exclude_tag_id=a&exclude_tag_id=b)
    if exclude_tag_ids:
        params["exclude_tag_id"] = list(exclude_tag_ids)
    res = _get(f"{base_url}/events/keyset", params=params)
    return res.get("events", []), res.get("next_cursor")


def list_active_events(limit: int = 20, base_url: str = GAMMA_URL) -> list[dict]:
    params = {"closed": "false", "active": "true", "limit": limit,
              "order": "volume24hr", "ascending": "false"}
    return _get(f"{base_url}/events", params=params)


def get_event_by_slug(slug: str, base_url: str = GAMMA_URL) -> dict | None:
    res = _get(f"{base_url}/events", params={"slug": slug})
    return res[0] if res else None


def get_market_by_slug(slug: str, base_url: str = GAMMA_URL) -> dict | None:
    res = _get(f"{base_url}/markets", params={"slug": slug})
    return res[0] if res else None


def parse_polymarket_url(text: str) -> tuple[str | None, str | None]:
    """Return (event_slug, market_slug) from a polymarket.com URL or a bare slug.

    https://polymarket.com/event/<event-slug>               -> (event, None)
    https://polymarket.com/event/<event-slug>/<market-slug> -> (event, market)
    https://polymarket.com/market/<market-slug>             -> (None, market)
    <slug>                                                  -> (slug, None)
    """
    text = text.strip().split("?")[0].split("#")[0].rstrip("/")
    m = re.search(r"polymarket\.com/(?:[a-z]{2}/)?(event|market)/([^/]+)(?:/([^/]+))?", text)
    if not m:
        return (text or None), None
    kind, first, second = m.groups()
    if kind == "market":
        return None, first
    return first, second


# ---------------------------------------------------------------------------
# Market normalisation
# ---------------------------------------------------------------------------

def normalize_market(market: dict, event: dict | None = None) -> dict | None:
    """Flatten a Gamma market into the fields we care about.

    Returns None for anything that isn't a plain Yes/No market.
    """
    outcomes = _loads(market.get("outcomes"))
    tokens = _loads(market.get("clobTokenIds"))
    if outcomes != ["Yes", "No"] or not isinstance(tokens, list) or len(tokens) != 2:
        return None

    event = event or (market.get("events") or [{}])[0]
    prices = _loads(market.get("outcomePrices"))
    resolved_yes = None
    if prices in (["1", "0"], ["0", "1"]) and market.get("closed"):
        resolved_yes = int(prices[0] == "1")

    tags = [t.get("label") for t in (event.get("tags") or []) if t.get("label")]
    n_markets = len(event.get("markets") or []) or 1

    return {
        "market_id": str(market.get("id")),
        "slug": market.get("slug"),
        "question": (market.get("question") or "").strip(),
        "event_id": str(event.get("id", "")),
        "event_slug": event.get("slug"),
        "event_title": event.get("title"),
        "event_n_markets": n_markets,
        "tags": tags,
        "neg_risk": bool(market.get("negRisk", False)),
        "start_date": market.get("startDate") or market.get("createdAt"),
        "end_date": market.get("endDate"),
        "closed_time": market.get("closedTime"),
        "volume": float(market.get("volumeNum") or market.get("volume") or 0.0),
        "yes_token_id": tokens[0],
        "resolved_yes": resolved_yes,
        "closed": bool(market.get("closed")),
        "last_trade_price": market.get("lastTradePrice"),
    }


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------

def get_price_history(token_id: str, fidelity_minutes: int = 1440,
                      base_url: str = CLOB_URL) -> list[dict]:
    """Daily (by default) YES-price history: [{"t": unix_seconds, "p": price}, ...]."""
    res = _get(f"{base_url}/prices-history",
               params={"market": token_id, "interval": "max", "fidelity": fidelity_minutes})
    return res.get("history", []) if isinstance(res, dict) else []
