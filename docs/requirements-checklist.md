# Submission requirement evidence

A submission audit found a timestamp-unit bug that allowed later prices into training snapshots. The former model and evaluation claims are invalid. Corrected local training is complete and all 113 local tests passed in 18.18 seconds; [Corrected CI at `7470d97`](https://github.com/hmccormack1/beat-the-crowd/actions/runs/45283570027) also passed. The corrected release passed public HTTP checks at 23:11:11 UTC on November 23, 2026. Corrected hosted browser inspection and independent artifact verification also passed. Correction PR review/merge remains required. This checklist separates implementation from verified corrected results and does not assert a grade.

| Requirement | Implementation or evidence | Current verification status |
|---|---|---|
| Public dataset, supervised task, target, metric | README Data/Model; [Polymarket API docs](https://docs.polymarket.com/); binary `resolved_yes`, primary Brier score | Documented |
| Clean/preprocess data and host it in cloud storage | `src/data/clean.py`; public `gs://beat-the-crowd/v1/` Parquet files | Raw files unchanged; SHA-256 hashes recorded in [corrected training evidence](training-verification.json) |
| Programmatically download cloud data | `src/data/storage.py`; `python -m src.data.storage download` | Download path implemented; corrected runs use the public v1 dataset |
| Ingestion, features, train/validation/test, training and evaluation | `src/data/`, `src/features/build.py`, `src/models/` | Timestamp conversion fixed in `855945b`; both corrected candidates FINISHED; 44,346 total / 23,135 contested snapshots |
| Parameterized configuration | `config.yaml`, `src/config.py` | Data stays v1; corrected model upload/cache paths are versioned separately |
| Dependencies and reproducible environment | Root `requirements.txt`, Python 3.12 Dockerfile, lightweight `frontend/requirements.txt` | Pinned installation and both corrected image builds passed in [CI at `7470d97`](https://github.com/hmccormack1/beat-the-crowd/actions/runs/45283570027) |
| Experiment runs, parameters, metrics, artifacts | `src/models/train.py`; [training-verification.json](training-verification.json) | Two corrected local comparison runs FINISHED with config/model/reports; metrics and local artifact hashes recorded, plus [actual MLflow capture](images/mlflow-corrected.jpg). Docker publication created release run `06ce2592fc0345669447c8a67246f443` at source `7470d97`, separate from the local comparison runs |
| Model choice and evaluation | README corrected comparison; [training evidence](training-verification.json) | XGBoost wins among learned candidates on validation Brier; crowd beats both candidates on validation and test |
| Docker entry points for training and serving | `Dockerfile`, `src/cli.py`; README commands | Fresh corrected training inside Docker and HTTP serving of its resulting model passed in [CI at `7470d97`](https://github.com/hmccormack1/beat-the-crowd/actions/runs/45283570027), independently of artifact publication |
| JSON `/predict` API and local test | `src/serving/app.py`, `tests/test_api.py`, timestamp regression tests | [Corrected local HTTP checks](local-verification.json), all 113 local tests, and [corrected CI](ci-verification.json) passed, including timestamp regression/helper coverage. Former 90-test result did not cover this bug |
| Public deployed corrected model API | [corrected-release helper](../scripts/publish_corrected_model.sh); README API link | Corrected release `7470d97` is public; served card identifies the new Docker run and corrected metrics |
| Confirm deployed endpoint with HTTP test input | `scripts/smoke_test.py`; corrected `/model` provenance | [Fresh public HTTP report](deployment-verification.json) passed health/model, raw prediction, five live-market predictions, and frontend health; [independent manifest/hash audit](release-verification.json) also passed |
| Interactive frontend calls deployed API | `frontend/app.py` and HTTP client; no local model loading | [Hosted browser inspection](browser-verification.json) passed trending selection, five prediction cards/charts, model metrics/warnings, invalid-link handling, and mobile layout |
| Public frontend linked in README | Existing frontend URL in README | Public URL linked; frontend HTML/health and [browser checks](browser-verification.json) passed; corrected hosted screenshots are embedded/linked in the README |
| Setup, train, local API, container and cloud instructions | README; [deployment guide](deployment.md) | Updated for v1 data and v2-corrected model paths, publication, and provenance checks |
| Dataset description/link, model/evaluation, cloud services | README Data, Model, Corrected results, Cloud services | Corrected metrics and negative result documented; earlier positive and calibration claims withdrawn |
| Ethical implications and limitations | README Limitations and ethics; app disclaimer/warnings | Corrected XGBoost test skill -1.97% and ROI -37.97% disclosed; metadata and retrospective-split limitations retained |
| Branches, PRs from both teammates, clear commits | Hadley's merged [PR #1](https://github.com/hmccormack1/beat-the-crowd/pull/1), [#2](https://github.com/hmccormack1/beat-the-crowd/pull/2), [#3](https://github.com/hmccormack1/beat-the-crowd/pull/3), [#4](https://github.com/hmccormack1/beat-the-crowd/pull/4); Konur's merged [PR #5](https://github.com/hmccormack1/beat-the-crowd/pull/5) | Both-member PR requirement met; timestamp-correction branch review and merge still required |

## Completed corrected test evidence

All 113 local tests passed in 18.18 seconds. [CI run 45283570027](https://github.com/hmccormack1/beat-the-crowd/actions/runs/45283570027) completed successfully at **2026-11-23 22:55:25 UTC** for exact revision `7470d972efa47bfecbb7bf45dd0ebb6fefcca7d4`. Both jobs passed: the automated suite, both image builds, backend container tests, fresh model training inside Docker, HTTP inference with that newly trained model, and frontend startup. See [job and step evidence](ci-verification.json). This run verifies the corrected implementation and deployed source revision. The separate [public HTTP report](deployment-verification.json) now records the deployed corrected release.

## Corrected release evidence

The public API now serves source `7470d972efa47bfecbb7bf45dd0ebb6fefcca7d4`, trained at `2026-11-23T23:07:08+00:00`, run `06ce2592fc0345669447c8a67246f443`, config hash `06593fd4bb`. Its counts, test period, and rounded test metrics match the corrected local evaluation. [Public HTTP verification](deployment-verification.json) passed on November 23, 2026, at 23:11:11 UTC. The [release manifest](release-manifest.json) and [independent release audit](release-verification.json) confirm source ancestry, data/artifact checksums, and exact published/served card agreement. [Hosted browser verification](browser-verification.json) passed at 23:14:03 UTC with refreshed desktop/mobile captures. Local comparison runs retain their own distinct IDs and model hashes.

## Remaining submission work

- Create, review, and merge the correction PR; both team members' original PR contribution requirement is already met.

The previous training reproduction, HTTP success, and screenshots described a functioning system with an invalid model. They remain superseded and must not be used as evidence for the corrected release. Verification describes behavior at its recorded time; future availability and results can change.
