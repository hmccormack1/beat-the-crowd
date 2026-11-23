"""Exercise the HTTP boundary and real Streamlit interactions without the network."""
from pathlib import Path

import pytest
import requests

from frontend.api_client import APIClient, APIError, normalize_market_input


class Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status
        self.ok = 200 <= status < 300

    def json(self):
        return self.payload


@pytest.mark.parametrize("value", [
    "", "https://example.com/event/foo", "https://polymarket.com.evil.test/event/foo",
    "https://user@polymarket.com/event/foo", "https://polymarket.com/", "foo/bar",
])
def test_rejects_non_market_input_before_network(value, monkeypatch):
    def network_forbidden(*args, **kwargs):
        pytest.fail("Invalid input should not call the API")
    monkeypatch.setattr(requests, "request", network_forbidden)
    with pytest.raises(APIError):
        APIClient("https://api.example.test").predict_market(value)


def test_client_posts_normalized_input_with_timeout(monkeypatch):
    seen = {}
    def request(method, url, **kwargs):
        seen.update(method=method, url=url, **kwargs)
        return Response({"markets": []})
    monkeypatch.setattr(requests, "request", request)
    APIClient("https://api.example.test/").predict_market(
        " https://www.polymarket.com/event/fed-decision/?utm_source=share "
    )
    assert seen == {
        "method": "POST", "url": "https://api.example.test/predict/market",
        "timeout": 60, "json": {"url": "https://polymarket.com/event/fed-decision"},
    }


@pytest.mark.parametrize("status,match", [
    (404, "open Yes/No"), (422, "couldn't be scored"),
    (502, "temporarily unavailable"), (500, "hit a problem"),
])
def test_client_translates_http_errors(status, match, monkeypatch):
    monkeypatch.setattr(requests, "request", lambda *a, **k: Response({}, status))
    with pytest.raises(APIError, match=match):
        APIClient("https://api.example.test").predict_market("example-event")


def test_client_handles_cold_start_timeout(monkeypatch):
    def timeout(*args, **kwargs):
        raise requests.Timeout("internal details should not reach the UI")
    monkeypatch.setattr(requests, "request", timeout)
    with pytest.raises(APIError, match="waking up"):
        APIClient("https://api.example.test").predict_market("example-event")


@pytest.mark.parametrize("payload", [
    [], {"markets": {}}, {"markets": [{"model_probability": float("nan"), "crowd_probability": .5}]},
])
def test_client_rejects_malformed_prediction(payload, monkeypatch):
    monkeypatch.setattr(requests, "request", lambda *a, **k: Response(payload))
    with pytest.raises(APIError):
        APIClient("https://api.example.test").predict_market("example-event")


@pytest.fixture
def app_fixture(monkeypatch):
    # Optional for backend-only installations; CI installs frontend requirements.
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    import streamlit as st
    st.cache_data.clear()
    monkeypatch.setenv("API_URL", "https://api.example.test")
    state = {"fail": False, "posts": []}
    def request(method, url, **kwargs):
        if url.endswith("/markets/trending"):
            return Response([{"title": "Example event", "slug": "example-event",
                              "url": "https://polymarket.com/event/example-event"}])
        if url.endswith("/model"):
            return Response({
                "model_type": "xgboost", "trained_at": "2026-11-23T03:10:49+00:00",
                "test_period": ["2026-10-01", "2026-11-10"],
                "n_markets": 2562, "n_snapshots": 9903,
                "metrics": {
                    "test_model_brier": .0469, "test_crowd_brier": .0495,
                    "test_brier_skill_vs_crowd": .0518,
                    "test_brier_skill_ci_low": -.0379, "test_brier_skill_ci_high": .1644,
                    "test_trade_roi": -.0269,
                },
            })
        assert method == "POST" and url.endswith("/predict/market")
        state["posts"].append(kwargs["json"])
        if state["fail"]:
            return Response({}, 404)
        return Response({
            "event_title": "Example event", "event_slug": "example-event",
            "scored_at": "2026-11-23T12:00:00+00:00",
            "markets": [{
                "question": "Will the example resolve YES?", "slug": "example",
                "end_date": "2026-12-01T00:00:00Z", "volume_usd": 125000,
                "category": "politics", "days_to_end": 8,
                "model_probability": .55, "crowd_probability": .40, "edge": .15,
                "verdict": "YES looks underpriced", "warnings": ["Very little price history so far."],
                "price_history": [{"t": 1795305600, "p": .35}, {"t": 1795392000, "p": .4}],
            }],
        })
    monkeypatch.setattr(requests, "request", request)
    path = Path(__file__).resolve().parents[1] / "frontend" / "app.py"
    return AppTest.from_file(str(path)), state


def test_app_scores_event_and_shows_warning_and_evidence(app_fixture):
    app, state = app_fixture
    app.run(timeout=15)
    assert not app.exception
    app.text_input[0].set_value("example-event")
    app.button[0].click().run(timeout=15)
    assert not app.exception
    assert state["posts"] == [{"url": "example-event"}]
    assert any(metric.value == "40.0%" for metric in app.metric)
    assert any(metric.value == "55.0%" for metric in app.metric)
    assert any("Very little price history" in warning.value for warning in app.warning)
    assert any("includes zero" in warning.value for warning in app.warning)
    assert len(app.get("vega_lite_chart")) == 1


def test_trending_selection_fills_input_and_failure_clears_old_result(app_fixture):
    app, state = app_fixture
    app.run(timeout=15)
    app.button[1].click().run(timeout=15)
    assert app.text_input[0].value == "https://polymarket.com/event/example-event"
    assert state["posts"] == []
    app.button[0].click().run(timeout=15)
    assert any(metric.value == "55.0%" for metric in app.metric)
    state["fail"] = True
    app.button[0].click().run(timeout=15)
    assert not app.exception
    assert any("open Yes/No" in error.value for error in app.error)
    assert not any(metric.value == "55.0%" for metric in app.metric)
