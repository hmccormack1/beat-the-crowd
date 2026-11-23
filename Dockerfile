FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    GIT_PYTHON_REFRESH=quiet \
    PORT=8080

WORKDIR /app

# Install dependencies first so code changes don't bust the cache layer
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY config.yaml pyproject.toml ./
COPY src/ src/
COPY tests/ tests/
COPY scripts/smoke_test.py scripts/smoke_test.py
# models/ is optional: if a trained model is present it gets baked in,
# otherwise the API downloads it from cloud storage on startup.
COPY models/ models/

EXPOSE 8080

# Default: serve the API. Override the command to train, e.g.
#   docker run beat-the-crowd train
ENTRYPOINT ["python", "-m", "src.cli"]
CMD ["serve"]
