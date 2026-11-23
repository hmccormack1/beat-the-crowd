# Submission requirement evidence

A submission audit found a timestamp-unit bug that allowed later prices into training snapshots. The former model and evaluation claims are invalid. Corrected local training is complete and all 113 local tests passed in 18.18 seconds; corrected CI and deployment evidence remain required. This checklist separates implementation from verified corrected results and does not assert a grade.

| Requirement | Implementation or evidence | Current verification status |
|---|---|---|
| Public dataset, supervised task, target, metric | README Data/Model; [Polymarket API docs](https://docs.polymarket.com/); binary `resolved_yes`, primary Brier score | Documented |
| Clean/preprocess data and host it in cloud storage | `src/data/clean.py`; public `gs://beat-the-crowd/v1/` Parquet files | Raw files unchanged; SHA-256 hashes recorded in [corrected training evidence](training-verification.json) |
| Programmatically download cloud data | `src/data/storage.py`; `python -m src.data.storage download` | Download path implemented; corrected runs use the public v1 dataset |
| Ingestion, features, train/validation/test, training and evaluation | `src/data/`, `src/features/build.py`, `src/models/` | Timestamp conversion fixed in `855945b`; both corrected candidates FINISHED; 44,346 total / 23,135 contested snapshots |
| Parameterized configuration | `config.yaml`, `src/config.py` | Data stays v1; corrected model upload/cache paths are versioned separately |
| Dependencies and reproducible environment | Root `requirements.txt`, Python 3.12 Dockerfile, lightweight `frontend/requirements.txt` | Present; final corrected container checks pending |
| Experiment runs, parameters, metrics, artifacts | `src/models/train.py`; [training-verification.json](training-verification.json) | Two corrected local comparison runs FINISHED with config/model/reports; metrics and local artifact hashes recorded, plus [actual MLflow capture](images/mlflow-corrected.jpg). Docker publication creates a separately identified release run |
| Model choice and evaluation | README corrected comparison; [training evidence](training-verification.json) | XGBoost wins among learned candidates on validation Brier; crowd beats both candidates on validation and test |
| Docker entry points for training and serving | `Dockerfile`, `src/cli.py`; README commands | CI now trains a fresh corrected model inside Docker and serves that model for HTTP checks, independently of artifact publication; corrected CI execution pending |
| JSON `/predict` API and local test | `src/serving/app.py`, `tests/test_api.py`, timestamp regression tests | [Corrected local HTTP checks](local-verification.json) and all 113 local tests passed, including timestamp regression/helper coverage; corrected CI pending. Former 90-test result did not cover this bug |
| Public deployed corrected model API | [corrected-release helper](../scripts/publish_corrected_model.sh); README API link | Existing service is public but still needs the v2-corrected model and new revision |
| Confirm deployed endpoint with HTTP test input | `scripts/smoke_test.py`; corrected `/model` provenance | Pending new public checks matched to the published release manifest/card and corrected results; local comparison run IDs need not match the new release |
| Interactive frontend calls deployed API | `frontend/app.py` and HTTP client; no local model loading | Corrected local HTTP and browser flow passed with five prediction cards; public frontend must be verified again after replacement |
| Public frontend linked in README | Existing frontend URL in README | Link present with replacement-pending status; corrected screenshots/browser evidence pending |
| Setup, train, local API, container and cloud instructions | README; [deployment guide](deployment.md) | Updated for v1 data and v2-corrected model paths, publication, and provenance checks |
| Dataset description/link, model/evaluation, cloud services | README Data, Model, Corrected results, Cloud services | Corrected metrics and negative result documented; earlier positive and calibration claims withdrawn |
| Ethical implications and limitations | README Limitations and ethics; app disclaimer/warnings | Corrected XGBoost test skill -1.97% and ROI -37.97% disclosed; metadata and retrospective-split limitations retained |
| Branches, PRs from both teammates, clear commits | Hadley's merged [PR #1](https://github.com/hmccormack1/beat-the-crowd/pull/1), [#2](https://github.com/hmccormack1/beat-the-crowd/pull/2), [#3](https://github.com/hmccormack1/beat-the-crowd/pull/3), [#4](https://github.com/hmccormack1/beat-the-crowd/pull/4); Konur's merged [PR #5](https://github.com/hmccormack1/beat-the-crowd/pull/5) | Both-member PR requirement met; timestamp-correction branch review and merge still required |
| No notebooks or committed private/runtime artifacts | `.gitignore`; source-tree review | Recheck final corrected diff before submission |

## Corrected evidence required before submission

- The release helper retrains the selected XGBoost model from a clean committed checkout containing `855945b`, publishes under `gs://beat-the-crowd/v2-corrected/model/`, and verifies artifact hashes against its release manifest. Local comparison hashes are retained separately.
- A new API revision whose served card equals the published release card: full source commit, new MLflow run ID, corrected counts/metrics, raw JSON prediction, and a live-market prediction.
- Frontend copy that states the model underperformed the crowd, plus fresh hosted browser inspection and screenshots of corrected predictions and metrics.
- Corrected CI success for the expanded suite and both container checks, including fresh Docker training and inference. The complete local suite already passed all 113 tests.
- Review/merge of the correction and replacement of prior model-dependent evidence with explicitly corrected reports.

The previous training reproduction, HTTP success, and screenshots described a functioning system with an invalid model. They must not be used as evidence that the corrected model is deployed or evaluated correctly. Verification describes behavior at its recorded time; future availability and results can change.
