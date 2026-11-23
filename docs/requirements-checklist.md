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
| Docker entry points for training and serving | `Dockerfile`, `src/cli.py`; README Docker commands | Build/runtime evidence required from CI or local Docker |
| JSON `/predict` API and local test | `src/serving/app.py`, `tests/test_api.py`; README curl | 83 automated tests pass; [real local HTTP checks](local-verification.json) |
| Public deployed model API | `scripts/deploy_cloud_run.sh`; README API link | Pending public deployment verification |
| Confirm deployed endpoint with HTTP test input | `scripts/smoke_test.py`; `docs/deployment-verification.json` after success | Pending successful public smoke check |
| Interactive frontend calls deployed API | `frontend/app.py` and HTTP client; no local model loading | Live local API/AppTest passed: 5 cards/charts, 13 metrics, 3 warnings. Public API wiring and browser review pending |
| Public frontend linked in README | README Live app link; screenshot at `docs/images/app.png` after capture | Pending public deployment and screenshot |
| Setup, train, local API, container and cloud instructions | README; `docs/deployment.md` | Documented |
| Dataset description/link, model/evaluation, cloud services | README Data, Model, What we found, Cloud services | Documented |
| Ethical implications and limitations | README Limitations and ethics; app disclaimer/warnings | Documented |
| Branches, PRs from both teammates, clear commits | Hadley's [PR #1](https://github.com/hmccormack1/beat-the-crowd/pull/1), [#2](https://github.com/hmccormack1/beat-the-crowd/pull/2), [#3](https://github.com/hmccormack1/beat-the-crowd/pull/3), [#4](https://github.com/hmccormack1/beat-the-crowd/pull/4); Konur's [PR #5](https://github.com/hmccormack1/beat-the-crowd/pull/5) and focused commits | PR #5 author verified as `konurnordberg`; final CI recorded in GitHub |
| No notebooks or committed private/runtime artifacts | `.gitignore`; source-tree review | Tracked file list reviewed: no notebooks, datasets, model binaries, credentials, or local databases |

## Final evidence to record

- API and frontend URLs, tested without authentication and linked in the README.
- Successful `scripts/smoke_test.py` output generated against those URLs.
- Screenshot of the actual frontend and a check of invalid-link, loading, warnings, chart, and model-info states.
- Final test result and Docker build/run result, with any environment restrictions stated honestly.
- Konur's PR URL and green CI for the final revision; do not credit another member's PR as his contribution.

The frontend and API can remain independently available even if live Polymarket calls fail. Report upstream failures accurately; never present an example or cached fixture as a live prediction.
