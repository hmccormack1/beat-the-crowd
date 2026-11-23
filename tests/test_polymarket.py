import pytest

from src.data.polymarket import normalize_market, parse_polymarket_url


@pytest.mark.parametrize("text,expected", [
    ("https://polymarket.com/event/fed-decision-in-december", ("fed-decision-in-december", None)),
    ("https://polymarket.com/event/fed-decision/fed-cuts-25bps?tid=123", ("fed-decision", "fed-cuts-25bps")),
    ("https://polymarket.com/market/some-market/", (None, "some-market")),
    ("polymarket.com/event/abc", ("abc", None)),
    ("just-a-slug", ("just-a-slug", None)),
])
def test_parse_polymarket_url(text, expected):
    assert parse_polymarket_url(text) == expected


def _market(**overrides):
    m = {
        "id": "1", "slug": "m", "question": "Will it rain?",
        "outcomes": '["Yes", "No"]', "outcomePrices": '["1", "0"]',
        "clobTokenIds": '["111", "222"]', "closed": True, "volumeNum": 5e4,
        "startDate": "2025-01-01T00:00:00Z", "endDate": "2025-02-01T00:00:00Z",
    }
    m.update(overrides)
    return m


def test_normalize_market_labels_yes():
    m = normalize_market(_market(), {"id": "e1", "markets": [{}, {}], "tags": [{"label": "Weather"}]})
    assert m["resolved_yes"] == 1
    assert m["yes_token_id"] == "111"
    assert m["event_n_markets"] == 2
    assert m["tags"] == ["Weather"]


def test_normalize_market_rejects_non_binary():
    assert normalize_market(_market(outcomes='["Up", "Down"]')) is None


def test_normalize_market_unresolved_has_no_label():
    m = normalize_market(_market(outcomePrices='["0.5", "0.5"]'))
    assert m["resolved_yes"] is None
