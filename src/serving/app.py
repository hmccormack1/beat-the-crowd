"""FastAPI service.

    uvicorn src.serving.app:app --port 8080

POST /predict          score a market from raw JSON (question + price history + dates)
POST /predict/market   score a live market straight from a polymarket.com link
GET  /markets/trending a few currently-hot events, handy for the front-end
GET  /model            the model card (metrics, training date, git commit)
GET  /health
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.config import load_config
from src.serving.predictor import Predictor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    state["predictor"] = Predictor(load_config())
    yield
    state.clear()


app = FastAPI(
    title="Beat the Crowd",
    description="Does a model trained on resolved Polymarket markets agree with today's prices?",
    version="1.0.0",
    lifespan=lifespan,
)
# The front-end is hosted on a different domain, so allow cross-origin calls.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PricePoint(BaseModel):
    t: int = Field(..., description="unix timestamp (seconds)")
    p: float = Field(..., ge=0, le=1, description="price of YES at time t")


class PredictRequest(BaseModel):
    question: str = Field(..., examples=["Will the Fed cut rates in December?"])
    price_history: list[PricePoint] = Field(..., min_length=2)
    start_date: str = Field(..., examples=["2026-10-01T00:00:00Z"])
    end_date: str = Field(..., examples=["2026-12-10T00:00:00Z"])
    tags: list[str] = Field(default_factory=list, examples=[["Economy", "Fed"]])
    event_n_markets: int = Field(1, ge=1, description="number of markets in the parent event")
    neg_risk: bool = False
    as_of: Optional[str] = Field(None, description="score as of this time (default: now)")


class PredictResponse(BaseModel):
    model_probability: float
    crowd_probability: float
    edge: float
    verdict: str
    warnings: list[str]
    features: dict


class MarketRequest(BaseModel):
    url: str = Field(..., examples=["https://polymarket.com/event/fed-decision-in-december"])


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
def root():
    return {"name": "beat-the-crowd", "docs": "/docs",
            "endpoints": ["/predict", "/predict/market", "/markets/trending", "/model", "/health"]}


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": "predictor" in state}


@app.get("/model")
def model_info():
    return state["predictor"].card


@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest):
    try:
        return state["predictor"].predict_raw(
            question=req.question,
            price_history=[pt.model_dump() for pt in req.price_history],
            start_date=req.start_date, end_date=req.end_date, tags=req.tags,
            event_n_markets=req.event_n_markets, neg_risk=req.neg_risk, as_of=req.as_of)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/predict/market")
def predict_market(req: MarketRequest):
    try:
        return state["predictor"].predict_url(req.url)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"couldn't reach Polymarket: {exc}") from exc


@app.get("/markets/trending")
def trending(limit: int = Query(10, ge=1, le=30)):
    try:
        return state["predictor"].trending(limit)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"couldn't reach Polymarket: {exc}") from exc
