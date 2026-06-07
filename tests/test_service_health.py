"""Tests for the service skeleton + /healthz (M2 Spec 01).

Run without Presidio by injecting a fake analyzer provider; FastAPI's TestClient
runs the lifespan (eager build) on context entry.
"""

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from prompt_redact_service.app import create_app  # noqa: E402


def test_healthz_ok_when_analyzer_builds():
    app = create_app(lambda: object())  # dummy analyzer
    with TestClient(app) as client:
        r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_healthz_unavailable_when_provider_fails():
    def boom():
        raise RuntimeError("model load failed")

    app = create_app(boom)
    with TestClient(app) as client:
        r = client.get("/healthz")
    assert r.status_code == 503
    assert r.json() == {"status": "unavailable"}


def test_analyzer_built_eagerly_exactly_once():
    calls = []

    def provider():
        calls.append(1)
        return object()

    app = create_app(provider)
    with TestClient(app) as client:
        client.get("/healthz")
        client.get("/healthz")
    assert calls == [1]  # built once at startup, not per request


def test_state_holds_built_analyzer():
    sentinel = object()
    app = create_app(lambda: sentinel)
    with TestClient(app):
        assert app.state.service.analyzer is sentinel
        assert app.state.service.ready is True


def test_state_unready_after_failed_build():
    app = create_app(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    with TestClient(app):
        assert app.state.service.ready is False
        assert app.state.service.analyzer is None
