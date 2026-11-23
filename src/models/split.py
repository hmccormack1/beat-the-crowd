"""Train / validation / test split.

Two things would make a naive random row split look much better than reality:

1. Several snapshots come from the same market, and markets inside one event
   are tightly linked (if "Will X win?" is YES, "Will Y win?" is NO). So we
   split by *event*: every row from an event lands in the same split.
2. Prediction markets drift over time (new users, new market types). Ordering
   events by end date and putting the latest ones in test asks the honest
   question: trained on the past, how does it do on the future?
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def split_by_event(df: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    sc = cfg["split"]
    events = df.groupby("event_id")["end_date"].max()

    if sc["method"] == "temporal":
        ordered = events.sort_values().index.to_numpy()
    elif sc["method"] == "random":
        rng = np.random.default_rng(cfg["project"]["seed"])
        ordered = rng.permutation(events.index.to_numpy())
    else:
        raise ValueError(f"unknown split method: {sc['method']}")

    n = len(ordered)
    n_train = int(n * sc["train_frac"])
    n_val = int(n * sc["val_frac"])
    train_ids = set(ordered[:n_train])
    val_ids = set(ordered[n_train:n_train + n_val])
    test_ids = set(ordered[n_train + n_val:])

    train = df[df["event_id"].isin(train_ids)].reset_index(drop=True)
    val = df[df["event_id"].isin(val_ids)].reset_index(drop=True)
    test = df[df["event_id"].isin(test_ids)].reset_index(drop=True)
    return train, val, test
