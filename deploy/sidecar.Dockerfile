# syntax=docker/dockerfile:1
# prompt-redact Python sidecar (M4-01). CPU-only, en_core_web_trf, multi-stage,
# non-root. Build context = repo root:
#   docker build -f deploy/sidecar.Dockerfile -t prompt-redact-sidecar .
#
# Workload is short interactive chat prompts (not bulk), so this is CPU-only and
# trf-only (the recall bar). lg is a documented --build-arg escape hatch, not a
# shipped variant.
ARG PYTHON_VERSION=3.11
ARG TRF_MODEL_WHEEL=https://github.com/explosion/spacy-models/releases/download/en_core_web_trf-3.8.0/en_core_web_trf-3.8.0-py3-none-any.whl

# --- builder: deps + model into a venv ---
FROM python:${PYTHON_VERSION}-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Hash-pinned runtime deps, incl. the CPU torch wheel — requirements.txt carries
# the PyTorch CPU --extra-index-url and torch==X+cpu, so the image stays CPU-only.
# --require-hashes verifies every wheel against the lockfile (threat T8).
COPY requirements.txt .
RUN pip install --require-hashes -r requirements.txt

# The spaCy transformer model, pinned by release-wheel URL. Retry — the large
# wheel occasionally 504s from GitHub's release CDN; verify the import after.
ARG TRF_MODEL_WHEEL
RUN for i in 1 2 3 4 5; do pip install "${TRF_MODEL_WHEEL}" && break; echo "model download retry $i"; sleep 10; done \
 && python -c "import en_core_web_trf"

# --- runtime: copy the venv + app, run as non-root ---
FROM python:${PYTHON_VERSION}-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1
RUN useradd --create-home --uid 10001 appuser
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY prompt_redact_core/ prompt_redact_core/
COPY prompt_redact_service/ prompt_redact_service/
USER appuser
EXPOSE 8000
# Readiness: /healthz flips ready only after the model warms (cold start ~4 s).
HEALTHCHECK --interval=10s --timeout=3s --start-period=60s --retries=6 \
  CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"
CMD ["uvicorn", "prompt_redact_service.app:app", "--host", "0.0.0.0", "--port", "8000"]
