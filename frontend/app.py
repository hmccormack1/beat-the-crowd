"""Run from the repository root: streamlit run frontend/app.py."""
from __future__ import annotations

import html
import os
from datetime import datetime

import streamlit as st

from api_client import APIClient, APIError
from charts import probability_history

st.set_page_config(
    page_title="Beat the Crowd | A second opinion on the odds",
    page_icon="◒",
    layout="wide",
    initial_sidebar_state="collapsed",
)

STYLE = """
<style>
.stApp {background:#f7f9fc;color:#13213a}
.block-container {max-width:1120px;padding-top:2.4rem;padding-bottom:2rem}
header[data-testid="stHeader"] {background:transparent}
h1,h2,h3 {color:#13213a;letter-spacing:-.035em}
h1 {font-size:clamp(2.8rem,6vw,4.4rem)!important;line-height:1.06!important;font-weight:750!important}
h2 {font-size:1.8rem!important}
h3 {font-size:1.25rem!important;line-height:1.4!important}
p,li {line-height:1.6}
.eyebrow {font-size:.78rem;font-weight:700;letter-spacing:.14em;color:#2458d3;margin:0 0 .8rem}
.hero-copy {font-size:1.15rem;color:#536078;max-width:730px;margin:0 0 1.3rem}
.hero-rule {height:4px;width:70px;background:#2458d3;border-radius:9px;margin:1.5rem 0}
.kicker {font-size:.82rem;font-weight:650;letter-spacing:.08em;color:#536078;text-transform:uppercase}
div[data-testid="stVerticalBlockBorderWrapper"]>div {border-radius:16px!important}
div[data-testid="stMetric"] {padding:.7rem 0}
div[data-testid="stMetricValue"] {font-weight:700;letter-spacing:-.04em}
div[data-testid="stMetricLabel"] {color:#536078}
div[data-testid="stButton"] button {border-radius:9px;min-height:2.75rem}
div[data-testid="stForm"] {background:#fff;border-radius:16px;padding:1.35rem}
.badge {display:inline-block;padding:.35rem .7rem;border-radius:7px;font-size:.88rem;
        font-weight:650;margin:.3rem 0 .7rem}
.badge-up {background:#e0f1e9;color:#146445}
.badge-down {background:#fbe9e7;color:#a23432}
.badge-neutral {background:#edf0f5;color:#4a576d}
.footer {border-top:1px solid #dce3ee;padding-top:1.25rem;color:#536078;font-size:.9rem}
@media(max-width:600px){.block-container{padding-top:1.5rem}.hero-copy{font-size:1rem}}
</style>
"""
st.markdown(STYLE, unsafe_allow_html=True)


def api_url() -> str:
    """Streamlit secrets take precedence over the environment; local by default."""
    try:
        configured = st.secrets["API_URL"]
    except (KeyError, FileNotFoundError):
        configured = None
    return str(configured or os.getenv("API_URL") or "http://localhost:8080")


@st.cache_data(ttl=300, show_spinner=False)
def load_trending(base_url: str):
    return APIClient(base_url).trending()


@st.cache_data(ttl=300, show_spinner=False)
def load_model(base_url: str):
    return APIClient(base_url).model_info()


def choose_event(url: str):
    st.session_state["market_url"] = url
    st.session_state.pop("result", None)
    st.session_state.pop("result_url", None)


def date_label(value: str | None) -> str:
    if not value:
        return "Not reported"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%b %d, %Y")
    except ValueError:
        return str(value)


def render_market(market: dict, index: int):
    with st.container(border=True):
        st.subheader(market.get("question") or f"Market {index + 1}")
        crowd = market["crowd_probability"]
        model = market["model_probability"]
        edge = model - crowd
        left, right = st.columns(2)
        left.metric("CROWD · YES probability", f"{crowd:.1%}")
        right.metric(
            "MODEL · YES probability", f"{model:.1%}",
            delta=f"{edge * 100:+.1f} pp vs. crowd", delta_color="off",
            help="The model-minus-crowd probability difference, in percentage points. "
                 "This is not an expected return or a confidence interval.",
        )
        verdict = market.get("verdict", "No verdict available")
        style = ("up" if verdict == "YES looks underpriced" else
                 "down" if verdict == "YES looks overpriced" else "neutral")
        st.markdown(
            f'<span class="badge badge-{style}">{html.escape(verdict)}</span>',
            unsafe_allow_html=True,
        )
        for warning in market.get("warnings") or []:
            st.warning(warning)
        history = market.get("price_history") or []
        if len(history) >= 2:
            st.altair_chart(probability_history(history, model), width="stretch")
            st.caption("Blue: daily crowd price · Dashed amber: model estimate now "
                       "(not a historical model forecast).")
        else:
            st.caption("Not enough price history to draw a chart.")
        days = market.get("days_to_end")
        horizon = f"{days:,.0f} days to end" if isinstance(days, (int, float)) and days >= 0 else "End date passed"
        volume = market.get("volume_usd")
        volume_label = f"${volume:,.0f} total volume" if isinstance(volume, (int, float)) else "Volume not reported"
        category = str(market.get("category") or "Uncategorized").replace("_", " ").title()
        st.caption(f"{horizon} · {volume_label} · {category} · Ends {date_label(market.get('end_date'))}")


def render_model(base_url: str):
    with st.expander("How good is this model?", expanded=False):
        st.write(
            "Compare the selected model with the crowd on held-out events. "
            "Model selection uses validation performance; the test metrics below "
            "are reported separately. A lower Brier score means better probability estimates."
        )
        try:
            card = load_model(base_url)
        except APIError as exc:
            st.info(str(exc))
            return
        metrics = card.get("metrics") or {}
        required = ("test_model_brier", "test_crowd_brier", "test_brier_skill_vs_crowd")
        if not all(isinstance(metrics.get(k), (int, float)) for k in required):
            st.info("The API has not published its model evaluation yet.")
            return
        col1, col2, col3 = st.columns(3)
        col1.metric("Model Brier · test", f"{metrics['test_model_brier']:.4f}")
        col2.metric("Crowd Brier · test", f"{metrics['test_crowd_brier']:.4f}")
        col3.metric("Relative Brier improvement", f"{metrics['test_brier_skill_vs_crowd']:+.1%}")
        low, high = metrics.get("test_brier_skill_ci_low"), metrics.get("test_brier_skill_ci_high")
        if isinstance(low, (int, float)) and isinstance(high, (int, float)):
            st.write(f"**95% confidence interval: {low:+.1%} to {high:+.1%}.** "
                     "This interval resamples entire events to account for related markets.")
            if low <= 0 <= high:
                st.warning("The interval includes zero. This test does not establish "
                           "that the model consistently beats the crowd.")
            elif high < 0:
                st.warning("The interval is below zero: the model performed worse than "
                           "the crowd on this test set. A disagreement is not evidence of an advantage.")
        roi = metrics.get("test_trade_roi")
        if isinstance(roi, (int, float)):
            st.write(f"Paper-trading return on the test set: **{roi:+.1%}**, before fees "
                     "and slippage. Better probabilities do not guarantee profit.")
        period = card.get("test_period") or []
        if len(period) == 2:
            st.caption(f"Test period: {period[0]} to {period[1]} · "
                       f"Trained {date_label(card.get('trained_at'))} · "
                       f"Model: {card.get('model_type', 'Not reported')}")
        if card.get("n_markets") and card.get("n_snapshots"):
            st.caption(f"After filtering: {card['n_markets']:,} markets and "
                       f"{card['n_snapshots']:,} snapshots across all splits. "
                       "The source dataset contains about 12,000 resolved markets.")
        st.write(
            "Training covers contested Yes/No markets with at least $25,000 in volume, "
            "using snapshots 1–90 days before their deadline. "
            "Markets outside that range can be unreliable; check every warning above."
        )
        st.link_button("Explore the methodology", "https://github.com/hmccormack1/beat-the-crowd#how-it-works")


st.markdown('<p class="eyebrow">PREDICTION MARKETS, WITH PERSPECTIVE</p>', unsafe_allow_html=True)
st.title("Beat the Crowd")
st.markdown(
    '<p class="hero-copy">Paste a Polymarket link. See what the crowd thinks, '
    'and what a model built from about 12,000 resolved markets thinks.</p>',
    unsafe_allow_html=True,
)
st.markdown('<div class="hero-rule"></div>', unsafe_allow_html=True)

base_url = api_url()
try:
    client = APIClient(base_url)
except APIError as exc:
    st.error(str(exc))
    st.stop()

with st.form("score_market"):
    st.text_input(
        "Polymarket event or market", key="market_url",
        placeholder="https://polymarket.com/event/...",
        help="Paste an open event link, a market link, or an event slug.",
    )
    submitted = st.form_submit_button("Score it", type="primary", width="stretch")
    st.caption("An independent probability estimate. No trades, no account, no guarantees.")

if submitted:
    st.session_state.pop("result", None)
    st.session_state.pop("result_url", None)
    try:
        with st.spinner("Reading the market and scoring it. A cold start can take up to a minute…"):
            result = client.predict_market(st.session_state.get("market_url", ""))
        st.session_state["result"] = result
        st.session_state["result_url"] = st.session_state["market_url"].strip()
    except APIError as exc:
        st.error(str(exc))

st.markdown('<p class="kicker">Or start with a trending event</p>', unsafe_allow_html=True)
try:
    events = load_trending(base_url)
except APIError:
    st.caption("Trending events are unavailable right now. You can still paste a link above.")
else:
    if not events:
        st.caption("No trending events to show right now. Paste an open market link above.")
    for offset in range(0, len(events), 3):
        columns = st.columns(3)
        for col, event in zip(columns, events[offset:offset + 3]):
            url, title = event.get("url"), event.get("title")
            if not url or not title:
                continue
            col.button(
                title, key=f"trending_{offset}_{event.get('slug', title)}",
                on_click=choose_event, args=(url,), width="stretch",
                help="Fill the input with this event, then choose Score it.",
            )

result = st.session_state.get("result")
if result is not None:
    st.divider()
    st.markdown('<p class="kicker">Your second opinion</p>', unsafe_allow_html=True)
    st.header(result.get("event_title") or "Market results")
    scored_at = result.get("scored_at", "")
    st.caption(f"Scored at {scored_at.replace('T', ' ').replace('+00:00', ' UTC')} · "
               "Prices change. Submit again to refresh.")
    markets = result.get("markets") or []
    if not markets:
        st.info("This event has no open Yes/No markets with enough price history to score. "
                "Try another event.")
    else:
        st.caption(f"Showing {len(markets)} scored market{'s' if len(markets) != 1 else ''}. "
                   "Events are limited to the 12 highest-volume eligible markets.")
        for index, market in enumerate(markets):
            render_market(market, index)
else:
    st.divider()
    left, middle, right = st.columns(3)
    left.markdown("**Read the crowd**\n\nA 40¢ YES price implies roughly a 40% chance.")
    middle.markdown("**Get a second opinion**\n\nThe model adds price history, timing, and question context.")
    right.markdown("**Keep the uncertainty**\n\nA disagreement is a signal to examine, not a promise.")

render_model(base_url)
st.markdown(
    '<div class="footer"><strong>Research, not a betting strategy.</strong><br>'
    'Not financial or betting advice. Model estimates can be wrong; review the held-out '
    'results and uncertainty before interpreting a disagreement. This app reads public data and places no trades. '
    'Market access varies by location.</div>',
    unsafe_allow_html=True,
)
