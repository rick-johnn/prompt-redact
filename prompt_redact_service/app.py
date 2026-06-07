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

from fastapi import FastAPI
from fastapi.responses import JSONResponse

logger = logging.getLogger("prompt_redact_service")


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

    return app


app = create_app()
