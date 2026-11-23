"""Single entry point used by the Docker image.

    python -m src.cli ingest     # pull raw data from Polymarket (slow, ~10-20 min)
    python -m src.cli clean      # raw JSONL -> processed Parquet
    python -m src.cli upload     # processed Parquet -> GCS (needs gcloud credentials)
    python -m src.cli train      # GCS -> features -> model, tracked in MLflow
    python -m src.cli serve      # start the FastAPI server on $PORT (default 8080)
"""

from __future__ import annotations

import os
import sys


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help"}:
        print(__doc__)
        sys.exit(0)

    command, rest = sys.argv[1], sys.argv[2:]
    sys.argv = [f"src.cli {command}", *rest]

    if command == "ingest":
        from src.data.ingest import main as run
    elif command == "clean":
        from src.data.clean import main as run
    elif command == "upload":
        sys.argv = [sys.argv[0], "upload", *rest]
        from src.data.storage import main as run
    elif command == "upload-model":
        sys.argv = [sys.argv[0], "upload-model", *rest]
        from src.data.storage import main as run
    elif command == "train":
        from src.models.train import main as run
    elif command == "serve":
        import uvicorn

        uvicorn.run("src.serving.app:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
        return
    else:
        print(f"unknown command: {command}\n{__doc__}")
        sys.exit(1)
    run()


if __name__ == "__main__":
    main()
