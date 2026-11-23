#!/usr/bin/env bash
# Deploy with Cloud Build, or use Cloud Shell's Docker with BUILD_MODE=local.
set -euo pipefail

usage() {
  cat <<'HELP'
Usage: bash scripts/deploy_cloud_run.sh [api|frontend|all]

Deploy the API (default), the Streamlit front-end, or both to Google Cloud Run.
Run "gcloud auth login" first, or use the already-authenticated Cloud Shell.

Environment overrides:
  PROJECT_ID           project-48739550-1716-4b50-877
  REGION               us-east1
  API_SERVICE          beat-the-crowd-api
  FRONTEND_SERVICE     beat-the-crowd-app
  API_URL              existing public API URL (otherwise discovered)
  BUILD_MODE           cloud (default) | local
  ARTIFACT_REPOSITORY   beat-the-crowd (Docker repository in PROJECT_ID/REGION)

Cloud mode uses Cloud Run source build for the API and Cloud Build for the UI.
Local mode builds both images with Docker, pushes to Artifact Registry as the
active gcloud user, then deploys those images. Example from Cloud Shell:
  BUILD_MODE=local bash scripts/deploy_cloud_run.sh all
It configures Docker's gcloud credential helper only for REGION-docker.pkg.dev.
Local mode requires a running Docker daemon and the user's existing repository
write and Cloud Run deployment permissions; it creates no credentials or roles.

Each service requests public access, scales to zero, and is limited to two instances.
This script enables required APIs but does not change billing or grant IAM roles.
Requires curl to verify unauthenticated health access after each deployment.
A 401/403 exits with an owner command to fix public invocation; it runs no IAM fix.
Then run scripts/smoke_test.py to verify model metadata and predictions.
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
BUILD_MODE="${BUILD_MODE:-cloud}"
ARTIFACT_REPOSITORY="${ARTIFACT_REPOSITORY:-beat-the-crowd}"
case "$BUILD_MODE" in
  cloud|local) ;;
  *) echo "BUILD_MODE must be cloud or local." >&2; exit 2 ;;
esac
REGISTRY="$REGION-docker.pkg.dev"
REPOSITORY_READY=false
DOCKER_AUTH_READY=false
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

command -v gcloud >/dev/null || {
  echo "gcloud is required. Use Google Cloud Shell or install the Google Cloud CLI." >&2
  exit 1
}
command -v curl >/dev/null || {
  echo "curl is required to verify public deployment access. Cloud Shell includes it." >&2
  exit 1
}
if [[ "$BUILD_MODE" == local ]]; then
  command -v docker >/dev/null || {
    echo "BUILD_MODE=local requires Docker. Google Cloud Shell includes it." >&2
    exit 1
  }
  docker info >/dev/null || {
    echo "Docker is not running or the current user cannot access it." >&2
    exit 1
  }
fi
ACCOUNT="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' --limit=1)"
[[ -n "$ACCOUNT" ]] || {
  echo "No active gcloud account. Run gcloud auth login, then rerun this script." >&2
  exit 1
}
gcloud projects describe "$PROJECT_ID" --format='value(projectId)' >/dev/null
printf 'Deploying %s to project %s in %s as %s (build mode: %s)\n' \
  "$TARGET" "$PROJECT_ID" "$REGION" "$ACCOUNT" "$BUILD_MODE"
SERVICES=(run.googleapis.com artifactregistry.googleapis.com)
if [[ "$BUILD_MODE" == cloud ]]; then SERVICES+=(cloudbuild.googleapis.com); fi
gcloud services enable "${SERVICES[@]}" --project="$PROJECT_ID" --quiet

api_url() {
  gcloud run services describe "$API_SERVICE" --project="$PROJECT_ID" \
    --region="$REGION" --format='value(status.url)'
}

ensure_repository() {
  if [[ "$REPOSITORY_READY" == true ]]; then return; fi
  if ! gcloud artifacts repositories describe "$ARTIFACT_REPOSITORY" --project="$PROJECT_ID" \
    --location="$REGION" >/dev/null 2>&1; then
    gcloud artifacts repositories create "$ARTIFACT_REPOSITORY" --project="$PROJECT_ID" \
      --location="$REGION" --repository-format=docker \
      --description="Beat the Crowd application images" --quiet
  fi
  REPOSITORY_READY=true
}

image_tag() {
  # Distinct service name + timestamp avoids reusing a stale mutable image tag.
  printf '%s/%s/%s/%s:%s\n' "$REGISTRY" "$PROJECT_ID" "$ARTIFACT_REPOSITORY" \
    "$1" "$(date -u +%Y%m%d%H%M%S)"
}

build_local() {
  local dockerfile="$1" image="$2"
  ensure_repository
  if [[ "$DOCKER_AUTH_READY" == false ]]; then
    # Uses the existing authenticated user; no service account keys or tokens.
    gcloud auth configure-docker "$REGISTRY" --quiet
    DOCKER_AUTH_READY=true
  fi
  docker build --platform=linux/amd64 -f "$dockerfile" -t "$image" .
  docker push "$image"
}

verify_public_access() {
  local service="$1" url="$2" path="$3" http_status curl_status=0
  # No auth header: the rubric requires access for a visitor without credentials.
  # Retry transient cold-start/server failures, but never treat 401/403 as success.
  http_status="$(curl --disable --silent --show-error --fail --output /dev/null \
    --write-out '%{http_code}' --connect-timeout 10 --max-time 60 \
    --retry 2 --retry-delay 2 --retry-max-time 90 "$url$path")" || curl_status=$?
  if [[ "$curl_status" == 0 && "$http_status" == 200 ]]; then
    printf 'Public access verified: %s%s\n' "$url" "$path"
    return 0
  fi

  printf 'Service %s was deployed, but public access to %s%s failed (HTTP %s).\n' \
    "$service" "$url" "$path" "${http_status:-unknown}" >&2
  if [[ "$http_status" == 401 || "$http_status" == 403 ]]; then
    echo "Public invocation is denied. Ask the project owner to run:" >&2
    printf '  ' >&2
    printf '%q ' gcloud run services add-iam-policy-binding "$service" \
      "--project=$PROJECT_ID" "--region=$REGION" \
      --member=allUsers --role=roles/run.invoker >&2
    printf '\nThen rerun scripts/smoke_test.py; rebuilding the image is unnecessary.\n' >&2
  else
    echo "Check Cloud Run service logs and readiness, then rerun scripts/smoke_test.py." >&2
  fi
  return 1
}

deploy_api() {
  local source_args=(--source=.)
  if [[ "$BUILD_MODE" == local ]]; then
    local image
    image="$(image_tag "$API_SERVICE")"
    build_local Dockerfile "$image"
    source_args=(--image="$image")
  fi
  gcloud run deploy "$API_SERVICE" "${source_args[@]}" --project="$PROJECT_ID" \
    --region="$REGION" --allow-unauthenticated \
    --memory=1Gi --cpu=1 --min-instances=0 --max-instances=2 \
    --timeout=60 --port=8080 --quiet
  API_URL="$(api_url)"
  verify_public_access "$API_SERVICE" "$API_URL" /health
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
  local image
  image="$(image_tag "$FRONTEND_SERVICE")"
  if [[ "$BUILD_MODE" == local ]]; then
    build_local Dockerfile.frontend "$image"
  else
    ensure_repository
    gcloud builds submit . --project="$PROJECT_ID" \
      --config=scripts/cloudbuild.frontend.yaml --substitutions="_IMAGE=$image" --quiet
  fi
  gcloud run deploy "$FRONTEND_SERVICE" --image="$image" --project="$PROJECT_ID" \
    --region="$REGION" --allow-unauthenticated \
    --memory=512Mi --cpu=1 --min-instances=0 --max-instances=2 \
    --timeout=3600 --session-affinity --port=8080 \
    --update-env-vars="API_URL=$API_URL" --quiet
  local frontend_url
  frontend_url="$(gcloud run services describe "$FRONTEND_SERVICE" \
    --project="$PROJECT_ID" --region="$REGION" --format='value(status.url)')"
  verify_public_access "$FRONTEND_SERVICE" "$frontend_url" /_stcore/health
  printf 'FRONTEND_URL=%s\nAPI_URL=%s\n' "$frontend_url" "$API_URL"
}

if [[ "$TARGET" == api || "$TARGET" == all ]]; then deploy_api; fi
if [[ "$TARGET" == frontend || "$TARGET" == all ]]; then deploy_frontend; fi
