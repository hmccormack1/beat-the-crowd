#!/usr/bin/env bash
# Standard-library Python orchestrates Docker and gcloud; no host ML install needed.
set -euo pipefail
exec python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/publish_corrected_model.py" "$@"
