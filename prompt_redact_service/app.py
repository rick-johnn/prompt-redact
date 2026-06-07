"""FastAPI app skeleton + readiness (M2 Spec 01).

This spec stands up the app and the ``/healthz`` readiness probe; the redaction
endpoints arrive in M2-02. The analyzer (Presidio + spaCy model) is built
**eagerly at startup** via the lifespan handler — the analyzer's own docs note
that its lazy first build isn't synchronized, so the service must warm it before
serving concurrent requests.

The analyzer builder is injected (``analyzer_provider``) so the app is testable
without Presidio: tests pass a fake provider. The module-level ``app`` uses the
real provider and is what uvicorn serves (``prompt_redact_service.app:app``).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Callable

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from prompt_redact_core import redact as core_redact
from prompt_redact_core import unredact as core_unredact
from prompt_redact_core.errors import RedactError, TokenShapedInputError, UnknownTokenError

logger = logging.getLogger("prompt_redact_service")


# --- request/response models (flat token-map wire contract, v1) -------------

class RedactRequest(BaseModel):
    text: str
    token_map: dict[str, str] = Field(default_factory=dict)
    language: str = "en"


class RedactResponse(BaseModel):
    redacted_text: str
    token_map: dict[str, str]


class UnredactRequest(BaseModel):
    text: str
    token_map: dict[str, str]


class UnredactResponse(BaseModel):
    text: str


def default_analyzer_provider():
    """Build and warm the real analyzer. Imports Presidio lazily (only here)."""
    from prompt_redact_core.analyzer import RedactionAnalyzer

    analyzer = RedactionAnalyzer()
    analyzer.analyze("warmup")  # force the engine + spaCy model to load now
    return analyzer


class ServiceState:
    """Holds the built analyzer and whether the service is ready to serve."""

    def __init__(self):
        self.analyzer = None
        self.ready = False


def create_app(analyzer_provider: Callable = default_analyzer_provider) -> FastAPI:
    """Build the FastAPI app. ``analyzer_provider`` builds the analyzer at startup."""
    state = ServiceState()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Build eagerly. On failure, stay up but unready so the readiness probe
        # fails (no traffic routed) rather than crashing the process.
        try:
            state.analyzer = analyzer_provider()
            state.ready = True
        except Exception:  # pragma: no cover - exercised via a failing provider
            logger.exception("analyzer build failed; service starting unready")
            state.ready = False
        yield

    app = FastAPI(title="prompt-redact", lifespan=lifespan)
    app.state.service = state

    @app.get("/healthz")
    def healthz():
        if state.ready:
            return {"status": "ok"}
        return JSONResponse(status_code=503, content={"status": "unavailable"})

    @app.exception_handler(RequestValidationError)
    async def _on_validation_error(request, exc):
        # Generic 400 for a malformed body. We deliberately do NOT echo the
        # offending input — it may contain PII (threat T2).
        return JSONResponse(status_code=400, content={"detail": "malformed request body"})

    def _require_ready():
        if not state.ready:
            raise HTTPException(status_code=503, detail="service unavailable")

    @app.post("/redact", response_model=RedactResponse)
    def redact(req: RedactRequest):
        _require_ready()
        if req.language != state.analyzer.config.language:
            raise HTTPException(status_code=400, detail=f"unsupported language: {req.language!r}")
        try:
            redacted_text, token_map = core_redact(
                req.text, req.token_map, analyzer=state.analyzer
            )
        except TokenShapedInputError:
            raise HTTPException(
                status_code=400, detail="input contains redaction-token-shaped substrings"
            )
        except RedactError:
            raise HTTPException(status_code=400, detail="invalid token_map")
        return RedactResponse(redacted_text=redacted_text, token_map=token_map)

    @app.post("/unredact", response_model=UnredactResponse)
    def unredact(req: UnredactRequest):
        _require_ready()
        try:
            text = core_unredact(req.text, req.token_map)
        except UnknownTokenError:
            raise HTTPException(
                status_code=422, detail="text contains a token not present in the token map"
            )
        except RedactError:
            raise HTTPException(status_code=400, detail="invalid request")
        return UnredactResponse(text=text)

    return app


app = create_app()
