"""Step 1: pull resolved Yes/No markets and their daily price history from Polymarket.

    python -m src.data.ingest [--config config.yaml] [--max-markets N]

Writes raw JSONL to data/raw/. Run `python -m src.data.clean` afterwards.
This is the slow step (one price-history request per market), so the cleaned
output is uploaded to cloud storage and everything downstream reads from there.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from src.config import load_config, resolve
from src.data import polymarket as pm

log = logging.getLogger("ingest")


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.replace(" ", "T").replace("+00", "+00:00").replace("Z", "+00:00")
    value = value.replace("+00:00:00", "+00:00")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def collect_markets(cfg: dict, max_markets: int) -> list[dict]:
    """Page through closed events and keep markets that pass the quality filters."""
    ic = cfg["ingest"]
    kept: list[dict] = []
    seen: set[str] = set()
    cursor, scanned = None, 0
    skipped = {"not_binary": 0, "unresolved": 0, "low_volume": 0, "too_short": 0,
               "out_of_range": 0}
    # The API's date filter is applied per event, so re-check each market's own end date.
    lo = _parse_ts(ic["end_date_min"] + "T00:00:00Z")
    hi = _parse_ts(ic["end_date_max"] + "T23:59:59Z")

    while len(kept) < max_markets:
        events, cursor = pm.list_closed_events(cursor, ic["page_size"], ic["end_date_min"],
                                               ic["end_date_max"], ic["min_volume_usd"],
                                               ic.get("exclude_tag_ids"), ic["gamma_url"])
        scanned += len(events)
        time.sleep(0.2)  # be polite to a free API

        for event in events:
            for market in event.get("markets") or []:
                m = pm.normalize_market(market, event)
                if m is None:
                    skipped["not_binary"] += 1
                    continue
                if m["market_id"] in seen:
                    continue
                if m["resolved_yes"] is None:
                    skipped["unresolved"] += 1
                    continue
                if m["volume"] < ic["min_volume_usd"]:
                    skipped["low_volume"] += 1
                    continue
                start, end = _parse_ts(m["start_date"]), _parse_ts(m["end_date"])
                if not start or not end or not (lo <= end <= hi):
                    skipped["out_of_range"] += 1
                    continue
                if (end - start).days < ic["min_duration_days"]:
                    skipped["too_short"] += 1
                    continue
                seen.add(m["market_id"])
                kept.append(m)

        if scanned % 1000 < ic["page_size"]:
            log.info("scanned %d events, kept %d markets (skipped: %s)", scanned, len(kept), skipped)
        if not events or not cursor:
            break

    return kept[:max_markets]


def fetch_prices(cfg: dict, markets: list[dict]) -> dict[str, list[dict]]:
    ic = cfg["ingest"]
    out: dict[str, list[dict]] = {}

    def job(m):
        return m["market_id"], pm.get_price_history(m["yes_token_id"],
                                                    ic["price_fidelity_minutes"], ic["clob_url"])

    with ThreadPoolExecutor(max_workers=ic["request_workers"]) as pool:
        futures = [pool.submit(job, m) for m in markets]
        for i, fut in enumerate(as_completed(futures), 1):
            try:
                market_id, history = fut.result()
                out[market_id] = history
            except Exception as exc:  # one bad market shouldn't kill a 6k-market pull
                log.warning("price history failed: %s", exc)
            if i % 250 == 0:
                log.info("fetched price history for %d/%d markets", i, len(markets))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None)
    parser.add_argument("--max-markets", type=int, default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")

    cfg = load_config(args.config)
    raw_dir = resolve(cfg["ingest"]["raw_dir"])
    raw_dir.mkdir(parents=True, exist_ok=True)

    markets = collect_markets(cfg, args.max_markets or cfg["ingest"]["max_markets"])
    prices = fetch_prices(cfg, markets)

    with open(raw_dir / "markets.jsonl", "w") as f:
        for m in markets:
            f.write(json.dumps(m) + "\n")
    with open(raw_dir / "prices.jsonl", "w") as f:
        for market_id, history in prices.items():
            f.write(json.dumps({"market_id": market_id, "history": history}) + "\n")

    log.info("wrote %d markets and %d price histories to %s", len(markets), len(prices), raw_dir)


if __name__ == "__main__":
    main()
