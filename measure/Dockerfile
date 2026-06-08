# THROWAWAY measurement image — NOT the production Dockerfile (that's M4-01).
# Purpose: get a real sidecar image size + cold-start/latency with CPU-only torch.
# See measure/README.md. Build context = repo root.
FROM python:3.11-slim

WORKDIR /app

# CPU-only torch FIRST, from the CPU wheel index — this avoids the CUDA
# libraries that dominate image size and that a CPU deployment never executes
# (the review's key hypothesis). Then the rest (torch is already satisfied, so
# spacy-transformers/presidio won't pull the CUDA build).
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir \
      presidio-analyzer spacy spacy-transformers fastapi "uvicorn[standard]"

# Which model to bake in. Default trf (what the app uses); override to
# en_core_web_lg to measure the lg image SIZE (note: the app still defaults to
# trf, so an lg image built this way is for size comparison, not for serving).
ARG SPACY_MODEL=en_core_web_trf
RUN python -m spacy download ${SPACY_MODEL}

COPY prompt_redact_core/ prompt_redact_core/
COPY prompt_redact_service/ prompt_redact_service/

EXPOSE 8000
CMD ["uvicorn", "prompt_redact_service.app:app", "--host", "0.0.0.0", "--port", "8000"]
