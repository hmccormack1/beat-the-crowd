"""Small, testable HTTP boundary; the frontend never loads a model."""
from __future__ import annotations

import math
import re
from urllib.parse import urlparse

import requests

TIMEOUT_SECONDS = 60


class APIError(Exception):
    """An error safe to explain to someone using the app."""


def normalize_market_input(value: str) -> str:
    """Accept a Polymarket event/market URL or a bare slug, without other hosts."""
    value = value.strip()
    if not value:
        raise APIError("Paste a Polymarket link or event slug to get started.")
    if len(value) > 2048:
        raise APIError("That link is too long. Copy the event link from Polymarket.")
    if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
        return value
    parsed = urlparse(value)
    if (parsed.scheme not in {"https", "http"}
            or parsed.netloc.lower() not in {"polymarket.com", "www.polymarket.com"}):
        raise APIError("Use a polymarket.com event or market link, or paste its event slug.")
    parts = parsed.path.strip("/").split("/")
    if (len(parts) not in {2, 3} or parts[0] not in {"event", "market"}
            or not all(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", part) for part in parts[1:])):
        raise APIError("Open an event on Polymarket and copy its full event or market link.")
    return "https://polymarket.com/" + "/".join(parts)


class APIClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.strip().rstrip("/")
        try:
            parsed = urlparse(self.base_url)
            valid = (
                parsed.scheme in {"http", "https"} and bool(parsed.hostname)
                and not parsed.username and not parsed.password
                and not parsed.query and not parsed.fragment
            )
            parsed.port  # Validate a supplied port before making a request.
        except ValueError:
            valid = False
        if not valid:
            raise APIError("The app's API address is not configured correctly.")

    def _request(self, method: str, path: str, **kwargs):
        try:
            response = requests.request(
                method, self.base_url + path, timeout=TIMEOUT_SECONDS, **kwargs
            )
        except requests.Timeout as exc:
            raise APIError(
                "The API took longer than a minute. It may be waking up; please try again."
            ) from exc
        except requests.RequestException as exc:
            raise APIError(
                "We couldn't connect to the prediction API. Please try again in a moment."
            ) from exc
        if response.status_code == 404:
            raise APIError(
                "We couldn't find open Yes/No markets at that link. "
                "Check the URL or choose another event."
            )
        if response.status_code == 422:
            raise APIError("That market input couldn't be scored. Check the link and try again.")
        if response.status_code in {429, 502, 503, 504}:
            raise APIError(
                "Live market data is temporarily unavailable. Please try again in a moment."
            )
        if not response.ok:
            raise APIError("The prediction service hit a problem. Please try again shortly.")
        try:
            return response.json()
        except ValueError as exc:
            raise APIError("The API returned an unreadable response. Please try again.") from exc

    def predict_market(self, value: str) -> dict:
        payload = self._request(
            "POST", "/predict/market", json={"url": normalize_market_input(value)}
        )
        if (not isinstance(payload, dict) or not isinstance(payload.get("markets"), list)
                or not all(isinstance(m, dict) for m in payload["markets"])):
            raise APIError("The API returned an incomplete prediction. Please try again.")
        for market in payload["markets"]:
            for key in ("model_probability", "crowd_probability"):
                value = market.get(key)
                if not isinstance(value, (int, float)) or not 0 <= value <= 1:
                    raise APIError("The API returned an invalid probability. Please try again.")
        return payload

    def trending(self, limit: int = 6) -> list[dict]:
        payload = self._request("GET", "/markets/trending", params={"limit": limit})
        if not isinstance(payload, list) or not all(isinstance(e, dict) for e in payload):
            raise APIError("Trending events are unavailable right now.")
        return payload

    def model_info(self) -> dict:
        payload = self._request("GET", "/model")
        if not isinstance(payload, dict):
            raise APIError("Model details are unavailable right now.")
        metrics = payload.get("metrics", {})
        if not isinstance(metrics, dict):
            raise APIError("Model evaluation details are unavailable right now.")
        shown_metrics = (
            "test_model_brier", "test_crowd_brier", "test_brier_skill_vs_crowd",
            "test_brier_skill_ci_low", "test_brier_skill_ci_high", "test_trade_roi",
        )
        for key in shown_metrics:
            if key in metrics:
                value = metrics[key]
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not math.isfinite(value)):
                    raise APIError("Model evaluation details are unavailable right now.")
        return payload
