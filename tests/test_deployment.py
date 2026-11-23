"""Public deployment checks must fail on unavailable or misleading responses."""

import sys
from datetime import datetime
from unittest.mock import Mock

import pytest
import requests

from scripts import smoke_test as smoke


@pytest.fixture
def prediction():
    return {
        "model_probability": 0.56,
        "crowd_probability": 0.51,
        "edge": 0.05,
        "verdict": "agrees with the crowd",
        "warnings": [],
    }


@pytest.fixture
def model_card():
    return {
        "model_type": "xgboost",
        "trained_at": "2026-11-23T03:10:49+00:00",
        "test_period": ["2026-10-01", "2026-11-10"],
        "metrics": {
            "test_model_brier": 0.0469,
            "test_crowd_brier": 0.0495,
            "test_brier_skill_vs_crowd": 0.0518,
            "test_brier_skill_ci_low": -0.0379,
            "test_brier_skill_ci_high": 0.1644,
        },
    }


def response(body=None, *, text="", content_type="application/json"):
    result = Mock(spec=requests.Response)
    result.json.return_value = body
    result.text = text
    result.headers = {"Content-Type": content_type}
    return result


def mock_api(monkeypatch, model_card, prediction, *, health=None, extra_get=()):
    get = Mock(side_effect=[
        response(health if health is not None else {"status": "ok", "model_loaded": True}),
        response(model_card),
        *extra_get,
    ])
    post = Mock(return_value=response(prediction))
    monkeypatch.setattr(smoke.requests, "get", get)
    monkeypatch.setattr(smoke.requests, "post", post)
    return get, post


def test_success_uses_http_and_frozen_payload(monkeypatch, model_card, prediction):
    get, post = mock_api(monkeypatch, model_card, prediction)
    report = smoke.run_checks("https://api.example.com")
    assert report["status"] == "passed"
    assert len(report["checks"]) == 3
    assert get.call_args_list[0].args == ("https://api.example.com/health",)
    assert post.call_args.args == ("https://api.example.com/predict",)
    assert post.call_args.kwargs == {"json": smoke.sample_payload(), "timeout": 60}
    # Regression: the original README cutoff was 26 minutes before the final point.
    payload = smoke.sample_payload()
    cutoff = datetime.fromisoformat(payload["as_of"]).timestamp()
    assert all(point["t"] <= cutoff for point in payload["price_history"])


@pytest.mark.parametrize("health", [
    {"status": "ok", "model_loaded": False},
    {"status": "error", "model_loaded": True},
    {"status": "ok", "model_loaded": "true"},
    [],
])
def test_unready_or_malformed_health_fails(monkeypatch, model_card, prediction, health):
    _, post = mock_api(monkeypatch, model_card, prediction, health=health)
    with pytest.raises(ValueError, match="not ready"):
        smoke.run_checks("https://api.example.com")
    post.assert_not_called()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.1, 1.1, "0.5", True, None])
def test_invalid_probabilities_fail(prediction, value):
    prediction["model_probability"] = value
    with pytest.raises(ValueError, match="finite probability"):
        smoke.validate_prediction(prediction)


def test_inconsistent_edge_fails(prediction):
    prediction["edge"] = -0.05
    with pytest.raises(ValueError, match="Edge"):
        smoke.validate_prediction(prediction)


def test_missing_model_card_fails(monkeypatch, prediction):
    mock_api(monkeypatch, {}, prediction)
    with pytest.raises(ValueError, match="Model card is missing"):
        smoke.run_checks("https://api.example.com")


@pytest.mark.parametrize("value", [None, "0.2", [], True, float("nan"), float("inf")])
def test_invalid_confidence_interval_fails(monkeypatch, model_card, prediction, value):
    model_card["metrics"]["test_brier_skill_ci_low"] = value
    mock_api(monkeypatch, model_card, prediction)
    with pytest.raises(ValueError, match="test_brier_skill_ci_low"):
        smoke.run_checks("https://api.example.com")


def test_public_frontend_health_is_checked(monkeypatch, model_card, prediction):
    get, _ = mock_api(monkeypatch, model_card, prediction, extra_get=[
        response(text="<html>Streamlit</html>", content_type="text/html; charset=utf-8"),
        response(text="ok"),
    ])
    report = smoke.run_checks("https://api.example.com", frontend_url="https://app.example.com")
    assert get.call_args_list[-1].args == ("https://app.example.com/_stcore/health",)
    assert report["frontend_url"] == "https://app.example.com"
    assert "browser interaction is verified separately" in report["checks"][-1]["scope"]


def test_frontend_unhealthy_fails(monkeypatch, model_card, prediction):
    mock_api(monkeypatch, model_card, prediction, extra_get=[
        response(text="<html></html>", content_type="text/html"),
        response(text="starting"),
    ])
    with pytest.raises(ValueError, match="Streamlit health"):
        smoke.run_checks("https://api.example.com", frontend_url="https://app.example.com")


def test_empty_live_event_fails(monkeypatch, model_card, prediction):
    _, post = mock_api(monkeypatch, model_card, prediction)
    post.side_effect = [response(prediction), response({"markets": []})]
    with pytest.raises(ValueError, match="no scoreable markets"):
        smoke.run_checks("https://api.example.com", market_url="empty-event")


def test_cli_rejects_credentials_without_echoing_them(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [
        "smoke_test.py", "--api-url", "https://user:private-password@example.com",
    ])
    with pytest.raises(SystemExit) as exc:
        smoke.main()
    assert exc.value.code == 2
    stderr = capsys.readouterr().err
    assert "without credentials" in stderr
    assert "private-password" not in stderr


def test_failed_check_does_not_write_success_report(monkeypatch, tmp_path, capsys):
    output = tmp_path / "evidence.json"
    monkeypatch.setattr(sys, "argv", [
        "smoke_test.py", "--api-url", "https://api.example.com", "--output", str(output),
    ])
    monkeypatch.setattr(smoke.requests, "get", Mock(side_effect=requests.Timeout("timed out")))
    with pytest.raises(SystemExit) as exc:
        smoke.main()
    assert exc.value.code == 1
    assert not output.exists()
    assert "FAILED" in capsys.readouterr().err
