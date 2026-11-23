"""Cold-start artifact loading must retain the model's evaluation evidence."""

import json

from src.serving import predictor as module


def test_cold_start_downloads_card_and_model(cfg, tmp_path, monkeypatch):
    path = tmp_path / "model.joblib"
    cfg["serving"]["model_path"] = str(path)
    cfg["serving"]["model_url"] = "https://storage.googleapis.com/example/v1/model/model.joblib"
    card = {"model_type": "xgboost", "metrics": {"test_model_brier": 0.0469}}
    downloads = []

    def download(url, dest):
        downloads.append(url)
        dest.write_text(json.dumps(card) if dest.suffix == ".json" else "test model")

    sentinel = object()
    monkeypatch.setattr(module, "download_file", download)
    monkeypatch.setattr(module.joblib, "load", lambda _: sentinel)
    predictor = module.Predictor(cfg)
    assert predictor.card == card
    assert predictor.model is sentinel
    assert downloads == [
        "https://storage.googleapis.com/example/v1/model/model_card.json",
        cfg["serving"]["model_url"],
    ]
    module.Predictor(cfg)
    assert len(downloads) == 2


def test_local_model_keeps_its_own_metadata(cfg, tmp_path, monkeypatch):
    path = tmp_path / "model.joblib"
    path.write_text("local model")
    card = {"model_type": "logistic_regression", "metrics": {"test_model_brier": 0.12}}
    path.with_name("model_card.json").write_text(json.dumps(card))
    cfg["serving"]["model_path"] = str(path)
    monkeypatch.setattr(module.joblib, "load", lambda _: object())

    def unexpected_download(*args):
        raise AssertionError("a local model must not receive unrelated remote metrics")

    monkeypatch.setattr(module, "download_file", unexpected_download)
    assert module.Predictor(cfg).card == card
