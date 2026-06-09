"""Tests for request correlation IDs (operability).

Every response carries an ``X-Correlation-ID`` header; error responses also
include it in the JSON body. A caller-supplied ID is reused when it is log-safe,
otherwise the service mints its own. No Presidio needed — a fake analyzer is
injected. See ``CorrelationIdMiddleware`` in ``prompt_redact_service.app``.
"""

from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from prompt_redact_core.tokens import Detection  # noqa: E402
from prompt_redact_service.app import create_app  # noqa: E402

HEADER = "X-Correlation-ID"


class FakeAnalyzer:
    def __init__(self, mapping=None, language="en"):
        self._mapping = mapping or {}
        self.config = SimpleNamespace(language=language)

    def analyze(self, text):
        return list(self._mapping.get(text, []))


def _client(analyzer=None):
    return TestClient(create_app(lambda: analyzer or FakeAnalyzer()))


# --- the header is always present -------------------------------------------

def test_success_response_carries_a_generated_id():
    with _client() as c:
        r = c.post("/redact", json={"text": "nothing here"})
    assert r.status_code == 200
    assert r.headers[HEADER]  # minted by the service
    # success bodies are NOT polluted with the id — header only
    assert "correlation_id" not in r.json()


def test_distinct_requests_get_distinct_ids():
    with _client() as c:
        a = c.post("/redact", json={"text": "a"}).headers[HEADER]
        b = c.post("/redact", json={"text": "b"}).headers[HEADER]
    assert a and b and a != b


def test_healthz_carries_id():
    with _client() as c:
        r = c.get("/healthz")
    assert r.headers[HEADER]


# --- caller-supplied IDs are reused when log-safe ---------------------------

def test_caller_correlation_id_is_echoed():
    with _client() as c:
        r = c.post("/redact", json={"text": "x"}, headers={HEADER: "abc-123_DEF.4"})
    assert r.headers[HEADER] == "abc-123_DEF.4"


def test_x_request_id_is_accepted_as_fallback():
    with _client() as c:
        r = c.post("/redact", json={"text": "x"}, headers={"X-Request-ID": "req-42"})
    assert r.headers[HEADER] == "req-42"


def test_correlation_id_wins_over_request_id():
    with _client() as c:
        r = c.post(
            "/redact",
            json={"text": "x"},
            headers={HEADER: "corr-1", "X-Request-ID": "req-1"},
        )
    assert r.headers[HEADER] == "corr-1"


# --- unsafe caller IDs are rejected (log-injection / unbounded) -------------

@pytest.mark.parametrize(
    "bad",
    [
        "has space",
        "with/slash",
        "semi;colon",
        "x" * 129,            # too long
        "",                   # empty after the client sends it
        "tab\tinside",
    ],
)
def test_unsafe_caller_id_is_replaced_not_echoed(bad):
    with _client() as c:
        r = c.post("/redact", json={"text": "x"}, headers={HEADER: bad})
    returned = r.headers[HEADER]
    assert returned != bad
    assert returned  # a safe replacement was minted
    # the replacement itself is log-safe (no whitespace/control chars)
    assert returned.strip() == returned and " " not in returned


# --- error bodies include the id, matching the header -----------------------

def test_malformed_body_400_includes_id_in_body_and_header():
    with _client() as c:
        r = c.post("/redact", json={"token_map": {}})  # missing "text"
    assert r.status_code == 400
    assert r.json()["correlation_id"] == r.headers[HEADER]


def test_unsupported_language_400_includes_id():
    with _client(FakeAnalyzer(language="en")) as c:
        r = c.post("/redact", json={"text": "hi", "language": "fr"})
    assert r.status_code == 400
    assert r.json()["correlation_id"] == r.headers[HEADER]


def test_service_unavailable_503_includes_id():
    def boom():
        raise RuntimeError("model load failed")

    with TestClient(create_app(boom)) as c:
        r = c.post("/redact", json={"text": "hi"})
    assert r.status_code == 503
    assert r.json()["correlation_id"] == r.headers[HEADER]


def test_token_shaped_400_includes_id():
    with _client() as c:
        r = c.post("/redact", json={"text": "already has [PERSON_1]"})
    assert r.status_code == 400
    assert r.json()["correlation_id"] == r.headers[HEADER]


def test_unknown_token_422_includes_id():
    with _client() as c:
        r = c.post("/unredact", json={"text": "see [PERSON_9]", "token_map": {}})
    assert r.status_code == 422
    assert r.json()["correlation_id"] == r.headers[HEADER]
