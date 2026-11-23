from src.features.build import build_training_set
from src.models.split import split_by_event


def test_events_never_shared_between_splits(cfg, synthetic_markets):
    df = build_training_set(*synthetic_markets, cfg)
    train, val, test = split_by_event(df, cfg)
    tr, va, te = set(train.event_id), set(val.event_id), set(test.event_id)
    assert not (tr & va) and not (tr & te) and not (va & te)
    assert len(train) + len(val) + len(test) == len(df)


def test_temporal_split_puts_future_in_test(cfg, synthetic_markets):
    df = build_training_set(*synthetic_markets, cfg)
    train, _, test = split_by_event(df, cfg)
    assert train["end_date"].max() <= test["end_date"].min()


def test_bootstrap_interval_contains_point_estimate(cfg, synthetic_markets):
    import numpy as np

    from src.models.evaluate import bootstrap_skill

    df = build_training_set(*synthetic_markets, cfg)
    model_p = np.clip(df["crowd_p"].to_numpy() + 0.05, 0, 1)
    lo, hi = bootstrap_skill(df, model_p, n_boot=200)
    point = 1 - ((model_p - df.target) ** 2).sum() / ((df.crowd_p - df.target) ** 2).sum()
    assert lo <= point <= hi
