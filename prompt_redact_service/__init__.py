"""prompt-redact HTTP service (M2).

A FastAPI app wrapping prompt_redact_core. Importing this package needs FastAPI
but NOT Presidio: the analyzer is built eagerly when the server starts (lifespan),
via a provider that imports Presidio lazily. See docs/specs/m2-01-service-skeleton.html.
"""

from .app import create_app

__all__ = ["create_app"]
