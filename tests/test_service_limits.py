"""Tests for the request size cap (T9) and the scrubbed 500 path (T2/T3) — M2-03.

No Presidio: a fake analyzer is injected. The size-cap tests don't even reach
the analyzer (the middleware rejects first).
"""

from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from prompt_redact_service.app import create_app  # noqa: E402


class FakeAnalyzer:
    def __init__(self, analyze=None, language="en"):
        self.config = SimpleNamespace(language=language)
        self._analyze = analyze or (lambda text: [])

    def analyze(self, text):
        return self._analyze(text)


# --- size cap (T9) ----------------------------------------------------------

def test_oversize_body_413():
    app = create_app(lambda: FakeAnalyzer(), max_body_bytes=50)
    with TestClient(app) as c:
        r = c.post("/redact", json={"text": "x" * 500})
    assert r.status_code == 413
    assert r.json() == {"detail": "request body too large"}


def test_body_within_cap_ok():
    app = create_app(lambda: FakeAnalyzer(), max_body_bytes=10_000)
    with TestClient(app) as c:
        r = c.post("/redact", json={"text": "hi"})
    assert r.status_code == 200


def test_cap_from_env_var(monkeypatch):
    monkeypatch.setenv("PROMPT_REDACT_MAX_BODY_BYTES", "30")
    app = create_app(lambda: FakeAnalyzer())  # no explicit cap -> reads env
    with TestClient(app) as c:
        assert c.post("/redact", json={"text": "x" * 200}).status_code == 413
        assert c.post("/redact", json={"text": "ok"}).status_code == 200


def test_healthz_not_blocked_by_cap():
    app = create_app(lambda: FakeAnalyzer(), max_body_bytes=10)
    with TestClient(app) as c:
        assert c.get("/healthz").status_code == 200


# --- scrubbed 500 path (T2/T3) ----------------------------------------------

def test_unexpected_error_returns_generic_500_without_leaking_input():
    secret = "SECRET-John-Doe-MRN-12345"

    def boom(text):
        # Simulate an engine error whose message embeds the input (the danger).
        raise RuntimeError(f"engine choked on {text}")

    app = create_app(lambda: FakeAnalyzer(analyze=boom))
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post("/redact", json={"text": secret})
    assert r.status_code == 500
    assert r.json() == {"detail": "internal error"}
    assert secret not in r.text  # the input must not leak into the response
