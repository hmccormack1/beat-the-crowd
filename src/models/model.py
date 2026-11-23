"""Model definition: a preprocessing ColumnTransformer + a classifier.

The model gets the crowd's own price as a feature, so in effect it learns
*when and how* to disagree with the market (e.g. longshots that are
systematically overpriced), rather than predicting from scratch.
"""

from __future__ import annotations

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from xgboost import XGBClassifier

from src.features.build import CATEGORICAL_FEATURES, NUMERIC_FEATURES, TEXT_FEATURE

# Dates in questions ("by June 30, 2026?") let a tree memorise which deadlines
# happened to fall in the training period. Keep words, drop numbers and months.
WORDS_ONLY = r"(?u)\b[a-zA-Z][a-zA-Z]+\b"
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december", "jan", "feb", "mar", "apr",
          "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec"]
STOP_WORDS = sorted(ENGLISH_STOP_WORDS.union(MONTHS))


def build_preprocessor(cfg: dict) -> ColumnTransformer:
    fc = cfg["features"]
    return ColumnTransformer(
        transformers=[
            ("num", StandardScaler(), NUMERIC_FEATURES),
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
            ("txt", TfidfVectorizer(max_features=fc["text_max_features"],
                                    ngram_range=tuple(fc["text_ngram_range"]),
                                    min_df=5, stop_words=STOP_WORDS, token_pattern=WORDS_ONLY,
                                    sublinear_tf=True),
             TEXT_FEATURE),
        ],
        sparse_threshold=1.0,
    )


def build_classifier(cfg: dict):
    mc = cfg["model"]
    seed = cfg["project"]["seed"]
    if mc["type"] == "xgboost":
        params = dict(mc["xgboost"])
        return XGBClassifier(
            objective="binary:logistic",
            eval_metric="logloss",
            random_state=seed,
            n_jobs=-1,
            tree_method="hist",
            **params,
        )
    if mc["type"] == "logistic_regression":
        return LogisticRegression(random_state=seed, **mc["logistic_regression"])
    raise ValueError(f"unknown model type: {mc['type']}")


def fit_model(cfg: dict, train: pd.DataFrame, val: pd.DataFrame) -> Pipeline:
    """Fit preprocessing on train only, then the classifier (with early stopping on val for XGB)."""
    pre = build_preprocessor(cfg)
    clf = build_classifier(cfg)

    X_train = pre.fit_transform(train)
    y_train = train["target"].to_numpy()

    if isinstance(clf, XGBClassifier):
        X_val = pre.transform(val)
        clf.fit(X_train, y_train, eval_set=[(X_val, val["target"].to_numpy())], verbose=False)
    else:
        clf.fit(X_train, y_train)

    return Pipeline([("pre", pre), ("clf", clf)])


def feature_names(model: Pipeline) -> list[str]:
    return list(model.named_steps["pre"].get_feature_names_out())
