r"""Verify a deployed API through public HTTP, optionally including its front-end.

    python scripts/smoke_test.py --api-url https://YOUR-API.run.app
    python scripts/smoke_test.py --api-url "$API_URL" --frontend-url "$APP_URL" \
        --market-url https://polymarket.com/event/fed-decision-in-december \
        --output docs/deployment-verification.json

Only requests is needed. No model or cloud credentials are loaded. A complete
JSON report is written only when every requested check passes.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests


def base_url(value: str) -> str:
    parsed = urlparse(value)
    if (parsed.scheme not in {"http", "https"} or not parsed.netloc
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise argparse.ArgumentTypeError("Use an HTTP(S) base URL without credentials or query.")
    return value.rstrip("/")


def sample_payload() -> dict:
    # Frozen times make this check repeatable, independent of today's date and
    # live Polymarket availability. Values are inputs, not a fabricated result.
    return {
        "question": "Will the Fed cut rates in December?",
        "price_history": [
            {"t": 1762000000, "p": 0.42},
            {"t": 1762086400, "p": 0.47},
            {"t": 1762172800, "p": 0.51},
        ],
        "start_date": "2025-10-01T00:00:00Z",
        "end_date": "2025-12-10T00:00:00Z",
        "tags": ["Economy", "Fed"],
        "as_of": "2025-11-03T13:00:00Z",
    }


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def finite_number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def validate_prediction(body: dict) -> None:
    require(isinstance(body, dict), "Prediction must be a JSON object.")
    for key in ("model_probability", "crowd_probability"):
        value = body.get(key)
        require(finite_number(value) and 0 <= value <= 1, f"{key} must be a finite probability.")
    expected = body["model_probability"] - body["crowd_probability"]
    edge = body.get("edge")
    require(finite_number(edge) and abs(edge - expected) < 0.001, "Edge must equal model minus crowd.")
    require(body.get("verdict") in {
        "YES looks underpriced", "YES looks overpriced", "agrees with the crowd"
    }, "Unrecognized prediction verdict.")
    require(isinstance(body.get("warnings"), list), "Prediction warnings must be a list.")


def run_checks(api_url: str, *, market_url: str | None = None,
               frontend_url: str | None = None, timeout: float = 60) -> dict:
    report = {
        "verified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "api_url": api_url,
        "checks": [],
    }

    def get_json(path: str) -> dict:
        response = requests.get(api_url + path, timeout=timeout)
        response.raise_for_status()
        return response.json()

    health = get_json("/health")
    require(isinstance(health, dict) and health.get("status") == "ok"
            and health.get("model_loaded") is True,
            "API is reachable but its trained model is not ready.")
    report["checks"].append({"endpoint": "GET /health", "response": health})

    card = get_json("/model")
    require(isinstance(card, dict) and bool(card.get("model_type")),
            "Model card is missing; check that model_card.json was downloaded.")
    require(bool(card.get("trained_at")) and len(card.get("test_period", [])) == 2,
            "Model card lacks its training date or test period.")
    metrics = card.get("metrics", {})
    require(isinstance(metrics, dict), "Model metrics must be a JSON object.")
    for key in ("test_model_brier", "test_crowd_brier",
                "test_brier_skill_vs_crowd", "test_brier_skill_ci_low",
                "test_brier_skill_ci_high"):
        require(finite_number(metrics.get(key)), f"Model card lacks {key}.")
    report["checks"].append({"endpoint": "GET /model", "response": card})

    response = requests.post(api_url + "/predict", json=sample_payload(), timeout=timeout)
    response.raise_for_status()
    prediction = response.json()
    validate_prediction(prediction)
    require(abs(prediction["crowd_probability"] - 0.51) < 0.0001,
            "The fixed /predict sample should return a crowd probability of 0.51.")
    report["checks"].append({"endpoint": "POST /predict", "request": sample_payload(),
                             "response": prediction})

    if market_url:
        response = requests.post(api_url + "/predict/market",
                                 json={"url": market_url}, timeout=timeout)
        response.raise_for_status()
        body = response.json()
        require(isinstance(body, dict) and isinstance(body.get("markets"), list)
                and bool(body["markets"]), "Live event returned no scoreable markets.")
        for market in body["markets"]:
            validate_prediction(market)
        report["checks"].append({
            "endpoint": "POST /predict/market", "request": {"url": market_url},
            "event_title": body.get("event_title"), "scored_at": body.get("scored_at"),
            "market_count": len(body["markets"]),
            "predictions": [{k: m[k] for k in (
                "question", "crowd_probability", "model_probability", "edge", "verdict", "warnings"
            )} for m in body["markets"]],
        })

    if frontend_url:
        response = requests.get(frontend_url, timeout=timeout)
        response.raise_for_status()
        require("text/html" in response.headers.get("Content-Type", ""),
                "Front-end must serve an HTML page.")
        health_response = requests.get(frontend_url + "/_stcore/health", timeout=timeout)
        health_response.raise_for_status()
        require(health_response.text.strip() == "ok", "Streamlit health check did not return ok.")
        report["frontend_url"] = frontend_url
        report["checks"].append({
            "endpoint": "GET front-end / and /_stcore/health", "status": "ok",
            "scope": "HTTP reachability only; browser interaction is verified separately.",
        })

    report["status"] = "passed"
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api-url", required=True, type=base_url)
    parser.add_argument("--market-url", help="Optional open Polymarket event URL or slug.")
    parser.add_argument("--frontend-url", type=base_url, help="Optional Streamlit base URL.")
    parser.add_argument("--timeout", type=float, default=60, help="Seconds per HTTP request (default: 60).")
    parser.add_argument("--output", type=Path, help="Save successful HTTP verification as JSON.")
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be a finite positive number.")
    try:
        report = run_checks(args.api_url, market_url=args.market_url,
                            frontend_url=args.frontend_url, timeout=args.timeout)
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"Smoke check FAILED: {exc}\n")
    content = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    print(content, end="")


if __name__ == "__main__":
    main()
