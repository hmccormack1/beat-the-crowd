"""Step 2: turn raw JSONL into two tidy Parquet tables.

    python -m src.data.clean [--config config.yaml]

data/processed/markets.parquet  one row per market (metadata + label)
data/processed/prices.parquet   one row per (market, day) YES price
"""

from __future__ import annotations

import argparse
import json
import logging

import pandas as pd

from src.config import load_config, resolve

log = logging.getLogger("clean")


def _to_utc(series: pd.Series) -> pd.Series:
    cleaned = (series.astype("string")
               .str.replace(" ", "T", regex=False)
               .str.replace(r"\+00$", "+00:00", regex=True))
    return pd.to_datetime(cleaned, utc=True, errors="coerce", format="ISO8601")


def clean_markets(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    for col in ("start_date", "end_date", "closed_time"):
        df[col] = _to_utc(df[col])

    before = len(df)
    df = df.dropna(subset=["start_date", "end_date", "resolved_yes", "question"])
    df = df[df["question"].str.len() > 0]
    df = df.drop_duplicates(subset="market_id")
    df["resolved_yes"] = df["resolved_yes"].astype(int)
    df["event_n_markets"] = df["event_n_markets"].fillna(1).astype(int)
    df["tags"] = df["tags"].apply(lambda t: list(t) if isinstance(t, (list, tuple)) else [])
    log.info("markets: %d -> %d after cleaning", before, len(df))

    keep = ["market_id", "slug", "question", "event_id", "event_slug", "event_title",
            "event_n_markets", "tags", "neg_risk", "start_date", "end_date", "closed_time",
            "volume", "resolved_yes"]
    return df[keep].reset_index(drop=True)


def clean_prices(raw_rows: list[dict], valid_ids: set[str]) -> pd.DataFrame:
    frames = []
    for row in raw_rows:
        if row["market_id"] not in valid_ids or not row["history"]:
            continue
        h = pd.DataFrame(row["history"])
        h["market_id"] = row["market_id"]
        frames.append(h)
    prices = pd.concat(frames, ignore_index=True).rename(columns={"t": "ts", "p": "price"})
    prices["ts"] = pd.to_datetime(prices["ts"], unit="s", utc=True)
    prices = prices[(prices["price"] >= 0) & (prices["price"] <= 1)]
    prices = (prices.sort_values(["market_id", "ts"])
                    .drop_duplicates(subset=["market_id", "ts"])
                    .reset_index(drop=True))
    return prices[["market_id", "ts", "price"]]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")

    cfg = load_config(args.config)
    raw_dir = resolve(cfg["ingest"]["raw_dir"])
    out_dir = resolve(cfg["ingest"]["processed_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    markets = clean_markets(pd.read_json(raw_dir / "markets.jsonl", lines=True,
                                         dtype={"market_id": str, "event_id": str}))
    with open(raw_dir / "prices.jsonl") as f:
        raw_prices = [json.loads(line) for line in f]
    prices = clean_prices(raw_prices, set(markets["market_id"]))

    # A market with no price history can't be featurised: drop it here, not silently later.
    has_prices = set(prices["market_id"])
    dropped = (~markets["market_id"].isin(has_prices)).sum()
    markets = markets[markets["market_id"].isin(has_prices)].reset_index(drop=True)
    log.info("dropped %d markets with no price history", dropped)

    files = cfg["storage"]["files"]
    markets.to_parquet(out_dir / files["markets"], index=False)
    prices.to_parquet(out_dir / files["prices"], index=False)
    log.info("wrote %d markets (%.1f%% resolved YES) and %d price points to %s",
             len(markets), 100 * markets["resolved_yes"].mean(), len(prices), out_dir)


if __name__ == "__main__":
    main()
