"""API tests against a tiny model trained on synthetic data (no network, no GCS)."""

import joblib
import pytest
from fastapi.testclient import TestClient

from src.features.build import build_training_set
from src.models.model import fit_model
from src.models.split import split_by_event
from src.serving import app as app_module
from src.serving.predictor import Predictor

DAY = 86400


@pytest.fixture
def client(cfg, synthetic_markets, tmp_path, monkeypatch):
    df = build_training_set(*synthetic_markets, cfg)
    train, val, _ = split_by_event(df, cfg)
    model_path = tmp_path / "model.joblib"
    joblib.dump(fit_model(cfg, train, val), model_path)
    cfg["serving"]["model_path"] = str(model_path)

    monkeypatch.setattr(app_module, "load_config", lambda: cfg)
    with TestClient(app_module.app) as c:
        yield c


def _payload(**overrides):
    body = {
        "question": "Will bitcoin be above $150k by December 31?",
        "price_history": [{"t": 1_760_000_000 + i * DAY, "p": 0.3 + 0.01 * i} for i in range(20)],
        "start_date": "2025-10-09T00:00:00Z",
        "end_date": "2025-12-31T00:00:00Z",
        "tags": ["Crypto"],
        "event_n_markets": 1,
        "neg_risk": False,
        "as_of": "2025-10-28T12:00:00Z",
    }
    body.update(overrides)
    return body


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "model_loaded": True}


def test_predict_returns_probability(client):
    r = client.post("/predict", json=_payload())
    assert r.status_code == 200
    body = r.json()
    assert 0 <= body["model_probability"] <= 1
    assert body["crowd_probability"] == pytest.approx(0.49)
    assert body["edge"] == pytest.approx(body["model_probability"] - body["crowd_probability"], abs=1e-3)
    assert body["verdict"] in {"YES looks underpriced", "YES looks overpriced", "agrees with the crowd"}


def test_predict_rejects_bad_prices(client):
    bad = _payload(price_history=[{"t": 1, "p": 1.7}, {"t": 2, "p": 0.5}])
    assert client.post("/predict", json=bad).status_code == 422


def test_predict_needs_history_before_as_of(client):
    r = client.post("/predict", json=_payload(as_of="2020-01-01T00:00:00Z"))
    assert r.status_code == 422


def test_verdict_thresholds(cfg, tmp_path):
    p = Predictor.__new__(Predictor)
    p.threshold = 0.05
    assert p.verdict(0.60, 0.50) == "YES looks underpriced"
    assert p.verdict(0.40, 0.50) == "YES looks overpriced"
    assert p.verdict(0.52, 0.50) == "agrees with the crowd"


def test_polymarket_outage_returns_502(client, monkeypatch):
    import requests

    from src.serving import predictor as predictor_module

    def boom(*args, **kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(predictor_module.pm, "get_event_by_slug", boom)
    r = client.post("/predict/market", json={"url": "https://polymarket.com/event/anything"})
    assert r.status_code == 502
