#!/usr/bin/env bash
# Deploy from Cloud Shell or a machine with gcloud; no local Docker required.
set -euo pipefail

usage() {
  cat <<'HELP'
Usage: bash scripts/deploy_cloud_run.sh [api|frontend|all]

Deploy the API (default), the Streamlit front-end, or both to Google Cloud Run.
Run "gcloud auth login" first, or use the already-authenticated Cloud Shell.

Environment overrides:
  PROJECT_ID        project-48739550-1716-4b50-877
  REGION            us-east1
  API_SERVICE       beat-the-crowd-api
  FRONTEND_SERVICE  beat-the-crowd-app
  API_URL           existing public API URL (front-end only; otherwise discovered)

The API uses the root Dockerfile through Cloud Run's source build.
The front-end uses Dockerfile.frontend through Cloud Build and Artifact Registry.
Each service is public, scales to zero, and is limited to two instances.
This script enables required APIs but does not change billing or grant IAM roles.
After deployment, run scripts/smoke_test.py to verify public HTTP access.
HELP
}

TARGET="${1:-api}"
case "$TARGET" in
  -h|--help) usage; exit 0 ;;
  api|frontend|all) ;;
  *) usage >&2; exit 2 ;;
esac
[[ $# -le 1 ]] || { usage >&2; exit 2; }

PROJECT_ID="${PROJECT_ID:-project-48739550-1716-4b50-877}"
REGION="${REGION:-us-east1}"
API_SERVICE="${API_SERVICE:-beat-the-crowd-api}"
FRONTEND_SERVICE="${FRONTEND_SERVICE:-beat-the-crowd-app}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

command -v gcloud >/dev/null || {
  echo "gcloud is required. Use Google Cloud Shell or install the Google Cloud CLI." >&2
  exit 1
}
ACCOUNT="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' --limit=1)"
[[ -n "$ACCOUNT" ]] || {
  echo "No active gcloud account. Run gcloud auth login, then rerun this script." >&2
  exit 1
}
gcloud projects describe "$PROJECT_ID" --format='value(projectId)' >/dev/null
printf 'Deploying %s to project %s in %s as %s\n' "$TARGET" "$PROJECT_ID" "$REGION" "$ACCOUNT"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com --project="$PROJECT_ID" --quiet

api_url() {
  gcloud run services describe "$API_SERVICE" --project="$PROJECT_ID" \
    --region="$REGION" --format='value(status.url)'
}

deploy_api() {
  gcloud run deploy "$API_SERVICE" --source=. --project="$PROJECT_ID" \
    --region="$REGION" --allow-unauthenticated \
    --memory=1Gi --cpu=1 --min-instances=0 --max-instances=2 \
    --timeout=60 --port=8080 --quiet
  API_URL="$(api_url)"
  printf 'API_URL=%s\nAPI docs: %s/docs\n' "$API_URL" "$API_URL"
}

deploy_frontend() {
  API_URL="${API_URL:-$(api_url)}"
  # A public base origin only, so gcloud's comma-delimited env parser stays safe.
  [[ "$API_URL" =~ ^https://[A-Za-z0-9.-]+/?$ ]] || {
    echo "API_URL must be a public HTTPS base URL, without a path or query." >&2
    exit 1
  }
  API_URL="${API_URL%/}"
  local repository=beat-the-crowd
  if ! gcloud artifacts repositories describe "$repository" --project="$PROJECT_ID" \
    --location="$REGION" >/dev/null 2>&1; then
    gcloud artifacts repositories create "$repository" --project="$PROJECT_ID" \
      --location="$REGION" --repository-format=docker \
      --description="Beat the Crowd application images" --quiet
  fi
  # A new tag per build avoids accidentally serving a stale mutable image.
  local image="$REGION-docker.pkg.dev/$PROJECT_ID/$repository/$FRONTEND_SERVICE:$(date -u +%Y%m%d%H%M%S)"
  gcloud builds submit . --project="$PROJECT_ID" \
    --config=scripts/cloudbuild.frontend.yaml --substitutions="_IMAGE=$image" --quiet
  gcloud run deploy "$FRONTEND_SERVICE" --image="$image" --project="$PROJECT_ID" \
    --region="$REGION" --allow-unauthenticated \
    --memory=512Mi --cpu=1 --min-instances=0 --max-instances=2 \
    --timeout=3600 --session-affinity --port=8080 \
    --update-env-vars="API_URL=$API_URL" --quiet
  local frontend_url
  frontend_url="$(gcloud run services describe "$FRONTEND_SERVICE" \
    --project="$PROJECT_ID" --region="$REGION" --format='value(status.url)')"
  printf 'FRONTEND_URL=%s\nAPI_URL=%s\n' "$frontend_url" "$API_URL"
}

if [[ "$TARGET" == api || "$TARGET" == all ]]; then deploy_api; fi
if [[ "$TARGET" == frontend || "$TARGET" == all ]]; then deploy_frontend; fi
