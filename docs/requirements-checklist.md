# Submission requirement evidence

This checklist maps the supplied assignment to reviewable files and external evidence. Source files demonstrate implementation; deployment and collaboration rows also need live or GitHub evidence. This document does not assert a grade.

| Requirement | Implementation or evidence | Verification status |
|---|---|---|
| Public dataset, supervised task, target, metric | README Data/Model; [Polymarket API docs](https://docs.polymarket.com/); binary `resolved_yes`, primary Brier score | Documented |
| Clean/preprocess data and host it in cloud storage | `src/data/clean.py`; public `gs://beat-the-crowd/v1/` Parquet files | Public data downloaded in the successful full training run |
| Programmatically download cloud data | `src/data/storage.py`; `python -m src.data.storage download` | Verified by training from a clean data directory |
| Ingestion, feature engineering, train/validation/test, training and evaluation | `src/data/`, `src/features/build.py`, `src/models/` | Full XGBoost run reproduced all published test metrics; [training evidence](training-verification.json) |
| Parameterized configuration | `config.yaml`, `src/config.py` | Present |
| Dependencies and reproducible environment | Root `requirements.txt`, Python 3.12 Dockerfile, lightweight `frontend/requirements.txt` | Present; install/build checks recorded in CI |
| Experiment run, parameters, metrics, artifacts | `src/models/train.py`; README MLflow screenshot; model card run ID | Verified FINISHED run with config/model/reports artifacts; actual runtime config verified |
| Docker entry points for training and serving | `Dockerfile`, `src/cli.py`; README Docker commands | Both builds, backend container tests, real-model prediction, and frontend health passed in [implementation CI at `70595a6`](https://github.com/hmccormack1/beat-the-crowd/actions/runs/45265056619) |
| JSON `/predict` API and local test | `src/serving/app.py`, `tests/test_api.py`; README curl | 90 automated tests pass; [real local HTTP checks](local-verification.json) |
| Public deployed model API | `scripts/deploy_cloud_run.sh`; README API link | Public unauthenticated API checks passed; [HTTP report](deployment-verification.json) |
| Confirm deployed endpoint with HTTP test input | `scripts/smoke_test.py`; [public HTTP report](deployment-verification.json) | Raw JSON prediction and live event with five scored markets passed on November 23, 2026 |
| Interactive frontend calls deployed API | `frontend/app.py` and HTTP client; no local model loading | HTTP-only client and interaction tests; live deployed API returns five markets. Hosted interaction inspection is recorded separately in [browser evidence](browser-verification.json) |
| Public frontend linked in README | README public app link; [hosted screenshot](images/app-live.jpg) | Public HTML and Streamlit health checks passed; [mobile capture](images/app-live-mobile.jpg) |
| Setup, train, local API, container and cloud instructions | README; `docs/deployment.md` | Documented |
| Dataset description/link, model/evaluation, cloud services | README Data, Model, What we found, Cloud services | Documented |
| Ethical implications and limitations | README Limitations and ethics; app disclaimer/warnings | Documented |
| Branches, PRs from both teammates, clear commits | Hadley's [PR #1](https://github.com/hmccormack1/beat-the-crowd/pull/1), [#2](https://github.com/hmccormack1/beat-the-crowd/pull/2), [#3](https://github.com/hmccormack1/beat-the-crowd/pull/3), [#4](https://github.com/hmccormack1/beat-the-crowd/pull/4); Konur's [PR #5](https://github.com/hmccormack1/beat-the-crowd/pull/5) and focused commits | PR #5 author verified as `konurnordberg`; implementation CI passed, with subsequent documentation checks tracked on the PR |
| No notebooks or committed private/runtime artifacts | `.gitignore`; source-tree review | Tracked file list reviewed: no notebooks, datasets, model binaries, credentials, or local databases |

## Evidence summary

- **Public services:** both URLs are linked in the README. [Unauthenticated HTTP checks](deployment-verification.json) passed on November 23, 2026, including raw and live-market predictions.
- **Hosted interface:** [browser inspection](browser-verification.json), [desktop screenshot](images/app-live.jpg), and [mobile screenshot](images/app-live-mobile.jpg). HTTP reachability alone is not a browser interaction test.
- **Reproducibility:** [full training evidence](training-verification.json), [earlier local HTTP checks](local-verification.json), and 90 passing local automated tests.
- **Containers and collaboration:** [implementation CI at `70595a6`](https://github.com/hmccormack1/beat-the-crowd/actions/runs/45265056619) passed both image builds and container smoke tests. Konur's [PR #5](https://github.com/hmccormack1/beat-the-crowd/pull/5) tracks subsequent documentation-only checks.

Verification describes the observed deployment at the recorded time. Live Polymarket availability can change; never present a fixture or an earlier check as a current prediction.
