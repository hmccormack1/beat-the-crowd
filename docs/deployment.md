# Deployment and verification

Deploy the model API before the frontend. Both deployments use the same source revision, and the frontend calls the API over HTTP. Do not replace a missing API with local model inference or invented sample results.

## Deployment status

**The corrected model replacement is pending.** Both existing service URLs were publicly reachable, but their previous predictions, model metrics, and screenshots came from the invalid timestamp pipeline. Earlier HTTP success and browser checks do not validate corrected inference. Do not submit those reports as evidence of the replacement model.

- [Existing frontend](https://beat-the-crowd-app-64wo2oghua-ue.a.run.app)
- [Existing API documentation](https://beat-the-crowd-api-64wo2oghua-ue.a.run.app/docs)

Both corrected candidates finished training from the unchanged `v1` data. XGBoost was selected among the learned candidates by validation Brier; the crowd remained better. The [corrected training record](training-verification.json) contains the results and provenance. Publish the selected pair under `gs://beat-the-crowd/v2-corrected/model/`, deploy the corrected API and frontend, and collect new public HTTP and browser evidence before marking this deployment complete.

## Publish the corrected model

The configuration keeps raw data in `storage.prefix: v1`, uses `storage.model_prefix: v2-corrected` for model uploads, and loads `models/v2-corrected/model.joblib` locally. This separate local path prevents the former model cache from being reused.

Use the [corrected-release helper](../scripts/publish_corrected_model.sh) from a clean, committed checkout containing timestamp fix `855945b`. Cloud Shell supplies the required tools; only Python's standard library is needed on the host, while Docker supplies the pinned ML dependencies. The authenticated account needs the existing bucket-write, registry, and Cloud Run permissions.

```bash
ARTIFACT_REPOSITORY=cloud-run-source-deploy \
  bash scripts/publish_corrected_model.sh
```

The helper archives the committed source, builds it in Docker, trains the selected XGBoost model afresh, validates its card and a prediction, and publishes a new model/card/effective-config release. It verifies public checksums before publishing `manifest.json`, then deploys both services from that source and checks that `/model` equals the published card. It also runs public raw-prediction and frontend health checks. Release files and MLflow outputs are retained in the printed `tmp/corrected-release-...` directory.

The cloud training run has its own **full release commit**, MLflow run ID, training time, config hash, and model hash. Do not require them to equal the local comparison run's `855945b` / `a7c90470a1404d08a710ab7ff9dc1f9d` identifiers. Verify instead that the release commit contains the fix, its published artifacts match [the release manifest](https://storage.googleapis.com/beat-the-crowd/v2-corrected/model/manifest.json), and the published and served model cards match exactly. Confirm the corrected result: 7,385 markets, 23,135 snapshots, test period October 4–November 14, 2026, and XGBoost/crowd test Brier 0.1093/0.1072. The local [training record](training-verification.json) preserves the comparison evidence separately.

The helper refuses existing or partial releases rather than overwriting them. An identical complete release can be verified and redeployed from its exact `source_commit`; use `--deploy-only` for that path. `--publish-only` stops after publication/verification. If the source or model destination changes, commit a new versioned destination for a new release. Do not bypass these checks by manually publishing an old cached model. The old `v1/model/` artifacts are invalid and must never be a fallback.

The deployment sections below describe the underlying service commands. Use the release helper for the corrected replacement so publication, model identity, and deployment remain connected.

## Prerequisites

Use Google Cloud Shell, or a local installation of the Google Cloud CLI authenticated with your own account. The existing project is `project-48739550-1716-4b50-877` (display name **My First Project**); region `us-east1`. The public bucket is `beat-the-crowd`. A separate, similarly named empty project is not the intended destination.

Cloud Run source deployments require permission to enable services, deploy the service, build the image, and act as its service account. An Editor role alone may not supply every required permission. If access is denied, retain the exact error and ask the project owner for the specific missing access; do not change organization policies or grant broad roles to solve it. See Google's [source deployment prerequisites and roles](https://docs.cloud.google.com/run/docs/deploying-source-code).

The scripts use the project's existing billing configuration. They do not start a new trial or upgrade billing. Minimum instances are zero and maximum instances are two to limit compute use; builds, storage, requests, and network traffic can still consume quota or incur charges under the project's current plan.

## API on Cloud Run

From the repository root, with the intended feature branch or merged revision checked out:

```bash
gcloud auth list
bash scripts/deploy_cloud_run.sh api
```

The script defaults to the project and region above, enables Cloud Run, Cloud Build, and Artifact Registry as needed, and deploys `beat-the-crowd-api` from the root Dockerfile. It uses 1 CPU, 1 GiB memory, a 60-second request timeout, no minimum instances, at most two instances, and requests public invocation. The script then checks unauthenticated health access and fails if access is denied. Cloud Build builds the container and Artifact Registry stores it; local Docker is not required for this deployment path. [Google's source-deployment documentation](https://docs.cloud.google.com/run/docs/deploying-source-code)

To select a different authorized destination explicitly:

```bash
PROJECT_ID=your-project REGION=us-east1 API_SERVICE=beat-the-crowd-api \
  bash scripts/deploy_cloud_run.sh api
```

The trained model is outside Git. At startup, the API loads the versioned corrected local artifact when available or downloads `v2-corrected/model/model.joblib` and its companion card from the public bucket. The `/model` response must contain the matching model card, not an empty object. First requests after an idle period may take longer while the container starts.

Discover the actual URL rather than guessing it:

```bash
API_URL=$(gcloud run services describe beat-the-crowd-api \
  --project project-48739550-1716-4b50-877 --region us-east1 \
  --format='value(status.url)')
curl --fail --show-error "$API_URL/health"
curl --fail --show-error "$API_URL/model"
```

Interactive API documentation is at `$API_URL/docs`. The API's service account needs no private data credential to download the public model.

## Frontend on Cloud Run

This is an alternative to Streamlit Community Cloud and keeps both services in the existing Google Cloud project. The frontend image installs only `frontend/requirements.txt`; it never installs or loads the trained model.

```bash
bash scripts/deploy_cloud_run.sh frontend
```

The script uses `Dockerfile.frontend`, builds and stores the image, deploys `beat-the-crowd-app`, and configures its `API_URL` environment variable from the deployed API service. To use a different deployed API, supply `API_URL=https://your-api-host` explicitly. To deploy both services in sequence:

```bash
bash scripts/deploy_cloud_run.sh all
```

Discover the frontend URL:

```bash
APP_URL=$(gcloud run services describe beat-the-crowd-app \
  --project project-48739550-1716-4b50-877 --region us-east1 \
  --format='value(status.url)')
```

## When the build service account cannot read the source

If source deployment fails with `storage.objects.get` denied for the default Compute Engine service account, the build account lacks the required project access. An authorized project administrator can grant `roles/run.builder` to that account as described in Google's [source-deployment prerequisites](https://docs.cloud.google.com/run/docs/deploying-source-code). An Editor cannot necessarily update project IAM; do not grant broad roles or change organization policies as a workaround.

Alternatively, build and push using the already-authenticated user in Cloud Shell, which includes Docker:

```bash
git pull --ff-only
BUILD_MODE=local ARTIFACT_REPOSITORY=cloud-run-source-deploy \
  bash scripts/deploy_cloud_run.sh all
```

This reuses the Artifact Registry repository created by the source-deployment attempt, builds both images locally for `linux/amd64`, configures Docker's credential helper for the regional registry, and pushes using the active user's existing permissions. It skips Cloud Build and does not grant project IAM roles. Cloud Run deployment, service-account impersonation, and public-access permissions still apply. If public invocation fails with `run.services.setIamPolicy` denied, an administrator must authorize public access or grant the deployer the appropriate Cloud Run role; see [Google's public-access requirements](https://docs.cloud.google.com/run/docs/authenticating/public).

## Alternative: Streamlit Community Cloud

1. Push the frontend branch to GitHub, review its pull request, and merge when checks pass.
2. In [Streamlit Community Cloud](https://share.streamlit.io/), create an app from `hmccormack1/beat-the-crowd`, branch `main`, entry point `frontend/app.py`.
3. Select Python 3.12. Set the following in the app's Secrets settings, replacing the example with the verified API URL:

   ```toml
   API_URL = "https://your-verified-api-host"
   ```

4. Deploy, open the app as a signed-out visitor, and score a current event. Put its actual URL in the README.

The frontend requirements file sits beside the app entry point. Keep this dependency set separate from the root training dependencies. Never commit account credentials or a local `secrets.toml`. See the [official Streamlit deployment guide](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app).

## HTTP verification

Install the project's requirements (or the frontend requirements, which include `requests`) before running the smoke script:

```bash
python scripts/smoke_test.py --api-url "$API_URL" \
  --frontend-url "$APP_URL" \
  --output docs/deployment-verification.json
```

This validates serving behavior, model metadata, and a deterministic JSON request to `/predict`. A successful HTTP request can still serve an old model: require the served card to match the **published release card**, whose full `git_commit` agrees with `manifest.json`'s `source_commit`. Verify release checksums and the corrected counts/metrics listed above. The release run ID and hashes can differ from the local comparison record because the helper retrains in Docker. The frontend HTTP check verifies reachability; a browser check below is still necessary to exercise user interactions. Include a live event test with a currently open link:

```bash
python scripts/smoke_test.py --api-url "$API_URL" \
  --market-url https://polymarket.com/event/fed-decision-in-december-20260729232808632 \
  --frontend-url "$APP_URL" \
  --output docs/deployment-verification.json
```

The example event may eventually close. If it does, choose an open event from `/markets/trending`; do not treat a legitimate 404 as a successful live prediction. The raw `/predict` request is independent of Polymarket availability.

## Browser verification and submission

Open the public frontend in a signed-out browser. Score an open event, verify that both probability values and the percentage-point difference appear, expand model information, and check warnings and the chart. Try an invalid link and ensure the error is readable. Check at a narrow/mobile width. Record the result in `docs/browser-verification.json` and save hosted screenshots to `docs/images/app-live.jpg` and `docs/images/app-live-mobile.jpg`. Replace earlier model-dependent screenshots only after checking that the page displays the corrected model card and predictions; the README can then embed the corrected desktop capture.

Konur's merged [PR #5](https://github.com/hmccormack1/beat-the-crowd/pull/5) contains the original second-half implementation. The timestamp correction is on `feature/fix-snapshot-time-units`. The expanded local suite passed 113 tests. [Corrected CI at `238bcef`](https://github.com/hmccormack1/beat-the-crowd/actions/runs/45282540880) completed at **2026-11-23 22:48:48 UTC**, with both jobs passing, including fresh Docker training and serving the resulting model for HTTP checks. [CI evidence](ci-verification.json) lists every job and step. The correction review/merge and verified corrected public release remain pending. Pre-correction CI missed the timestamp-unit error and is historical evidence only.

## Troubleshooting

### Public invocation denied

If a future deployment succeeds but unauthenticated requests return **401 or 403**, a project owner or Cloud Run administrator can authorize invocation on only these services:

```bash
for service in beat-the-crowd-api beat-the-crowd-app; do
  gcloud run services add-iam-policy-binding "$service" \
    --project=project-48739550-1716-4b50-877 \
    --region=us-east1 --member=allUsers --role=roles/run.invoker
done
```

This needs `run.services.setIamPolicy`, but no image rebuild or project-wide role grant to the deployer. See [Google's public-access documentation](https://docs.cloud.google.com/run/docs/authenticating/public). Rerun the public smoke test after changing access. Deployment requests public invocation through `--allow-unauthenticated`; if that fails, the script reports the access failure without running the suggested permission-remediation command automatically.

### Other failures

- **Missing model or model card:** check the public bucket URLs in `config.yaml` and the [model card](https://storage.googleapis.com/beat-the-crowd/v2-corrected/model/model_card.json). Publish matching artifacts from the same training run, then deploy a new API revision. Never hand-edit metrics to fill a missing response.
- **Build or service-account permission failure:** use the exact failing permission to request a targeted fix from the project owner. Source-build IAM requirements are documented by Google; the script does not grant roles.
- **First request times out:** inspect Cloud Run revision logs and confirm startup completed. Retry after the cold start; the app uses a 60-second client timeout.
- **Polymarket returns an error:** `/predict/market` and trending require upstream connectivity. Confirm `/health` and raw `/predict` separately to distinguish serving failure from an upstream outage.
- **Frontend cannot reach the API:** verify `API_URL` contains the HTTPS origin, not `/docs` or `/predict`, and that the API allows unauthenticated invocation.
- **New model does not appear:** containers cache artifacts on their local filesystem. Deploy a new revision after updating the model and card together; verify `/model` provenance against the intended training run.
