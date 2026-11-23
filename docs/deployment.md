# Deployment and verification

Deploy the model API before the frontend. Both deployments use the same source revision, and the frontend calls the API over HTTP. Do not replace a missing API with local model inference or invented sample results.

## Deployment status

Public deployment verification is pending. Replace this status and the README live-links table only after the deployed URLs pass the checks below. Preserve the resulting `docs/deployment-verification.json` as evidence of the URL, time, and HTTP checks performed; it does not guarantee future uptime.

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

The script defaults to the project and region above, enables Cloud Run, Cloud Build, and Artifact Registry as needed, and deploys `beat-the-crowd-api` from the root Dockerfile. It uses 1 CPU, 1 GiB memory, a 60-second request timeout, no minimum instances, at most two instances, and public invocation. Cloud Build builds the container and Artifact Registry stores it; local Docker is not required for this deployment path. [Google's source-deployment documentation](https://docs.cloud.google.com/run/docs/deploying-source-code)

To select a different authorized destination explicitly:

```bash
PROJECT_ID=your-project REGION=us-east1 API_SERVICE=beat-the-crowd-api \
  bash scripts/deploy_cloud_run.sh api
```

The trained model is outside Git. At startup, the API loads local artifacts when available or downloads the configured public artifacts. The `/model` response must contain the matching model card, not an empty object. First requests after an idle period may take longer while the container starts.

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

This validates the loaded model, model metadata, and a deterministic JSON request to `/predict`. The frontend HTTP check verifies reachability; a browser check below is still necessary to exercise user interactions. Include a live event test with a currently open link:

```bash
python scripts/smoke_test.py --api-url "$API_URL" \
  --market-url https://polymarket.com/event/fed-decision-in-december \
  --frontend-url "$APP_URL" \
  --output docs/deployment-verification.json
```

The example event may eventually close. If it does, choose an open event from `/markets/trending`; do not treat a legitimate 404 as a successful live prediction. The raw `/predict` request is independent of Polymarket availability.

## Browser verification and submission

Open the public frontend in a signed-out browser. Score an open event, verify that both probability values and the percentage-point difference appear, expand model information, and check warnings and the chart. Try an invalid link and ensure the error is readable. Check at a narrow/mobile width. Save an actual app screenshot to `docs/images/app.png` and embed it in the README.

Record the API and frontend URLs in the README, attach smoke-check evidence, and link Konur's pull request in `docs/requirements-checklist.md`. Confirm that GitHub CI passed on the final revision. Each team member must submit a PR from their own account; a local branch or commit is insufficient.

## Troubleshooting

- **Missing model or model card:** check the public bucket URLs in `config.yaml` and the [model card](https://storage.googleapis.com/beat-the-crowd/v1/model/model_card.json). Publish matching artifacts from the same training run, then deploy a new API revision. Never hand-edit metrics to fill a missing response.
- **Build or service-account permission failure:** use the exact failing permission to request a targeted fix from the project owner. Source-build IAM requirements are documented by Google; the script does not grant roles.
- **First request times out:** inspect Cloud Run revision logs and confirm startup completed. Retry after the cold start; the app uses a 60-second client timeout.
- **Polymarket returns an error:** `/predict/market` and trending require upstream connectivity. Confirm `/health` and raw `/predict` separately to distinguish serving failure from an upstream outage.
- **Frontend cannot reach the API:** verify `API_URL` contains the HTTPS origin, not `/docs` or `/predict`, and that the API allows unauthenticated invocation.
- **New model does not appear:** containers cache artifacts on their local filesystem. Deploy a new revision after updating the model and card together; verify `/model` provenance against the intended training run.
