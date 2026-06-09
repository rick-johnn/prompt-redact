"""Tests for /redact and /unredact (M2 Spec 02).

Exercised end-to-end through the FastAPI app without Presidio: a fake analyzer
(with a `config.language` and preset detections) is injected, and the real
prompt_redact_core runs the redaction. No ML stack needed.
"""

from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from prompt_redact_core.tokens import Detection  # noqa: E402
from prompt_redact_service.app import create_app  # noqa: E402


class FakeAnalyzer:
    """Returns preset detections per text; carries a config.language like the real one."""

    def __init__(self, mapping=None, language="en"):
        self._mapping = mapping or {}
        self.config = SimpleNamespace(language=language)

    def analyze(self, text):
        return list(self._mapping.get(text, []))


def _client(analyzer):
    return TestClient(create_app(lambda: analyzer))


# --- /redact ----------------------------------------------------------------

def test_redact_single_detection():
    text = "Patient John Doe"
    fake = FakeAnalyzer({text: [Detection(8, 16, "PERSON", "John Doe")]})
    with _client(fake) as c:
        r = c.post("/redact", json={"text": text})
    assert r.status_code == 200
    body = r.json()
    assert body["redacted_text"] == "Patient [PERSON_1]"
    assert body["token_map"] == {"[PERSON_1]": "John Doe"}


def test_redact_no_pii_is_identity():
    fake = FakeAnalyzer({"nothing here": []})
    with _client(fake) as c:
        r = c.post("/redact", json={"text": "nothing here"})
    assert r.status_code == 200
    assert r.json() == {"redacted_text": "nothing here", "token_map": {}}


def test_redact_reuses_supplied_token_map():
    text = "John and Jane"
    fake = FakeAnalyzer({text: [Detection(0, 4, "PERSON", "John"), Detection(9, 13, "PERSON", "Jane")]})
    with _client(fake) as c:
        r = c.post("/redact", json={"text": text, "token_map": {"[PERSON_1]": "John"}})
    assert r.status_code == 200
    body = r.json()
    assert body["redacted_text"] == "[PERSON_1] and [PERSON_2]"
    assert body["token_map"] == {"[PERSON_1]": "John", "[PERSON_2]": "Jane"}


def test_redact_token_shaped_input_400():
    fake = FakeAnalyzer()
    with _client(fake) as c:
        r = c.post("/redact", json={"text": "already has [PERSON_1]"})
    assert r.status_code == 400


def test_redact_unsupported_language_400():
    fake = FakeAnalyzer(language="en")
    with _client(fake) as c:
        r = c.post("/redact", json={"text": "hi", "language": "fr"})
    assert r.status_code == 400


def test_redact_malformed_body_400():
    fake = FakeAnalyzer()
    with _client(fake) as c:
        r = c.post("/redact", json={"token_map": {}})  # missing required "text"
    assert r.status_code == 400
    assert r.json()["detail"] == "malformed request body"
    assert r.json()["correlation_id"]


def test_redact_503_when_not_ready():
    def boom():
        raise RuntimeError("model load failed")

    with TestClient(create_app(boom)) as c:
        r = c.post("/redact", json={"text": "hi"})
    assert r.status_code == 503


# --- /unredact --------------------------------------------------------------

def test_unredact_restores_originals():
    with _client(FakeAnalyzer()) as c:
        r = c.post("/unredact", json={
            "text": "I updated [PERSON_1]'s record.",
            "token_map": {"[PERSON_1]": "John Doe"},
        })
    assert r.status_code == 200
    assert r.json() == {"text": "I updated John Doe's record."}


def test_unredact_unknown_token_422():
    with _client(FakeAnalyzer()) as c:
        r = c.post("/unredact", json={"text": "see [PERSON_9]", "token_map": {}})
    assert r.status_code == 422


def test_unredact_no_tokens_passthrough():
    with _client(FakeAnalyzer()) as c:
        r = c.post("/unredact", json={"text": "plain text", "token_map": {}})
    assert r.status_code == 200
    assert r.json() == {"text": "plain text"}


def test_unredact_malformed_body_400():
    with _client(FakeAnalyzer()) as c:
        r = c.post("/unredact", json={"text": "x"})  # missing required token_map
    assert r.status_code == 400


# --- round trip through the API ---------------------------------------------

def test_round_trip_through_api():
    text = "Call John Doe today."
    fake = FakeAnalyzer({text: [Detection(5, 13, "PERSON", "John Doe")]})
    with _client(fake) as c:
        red = c.post("/redact", json={"text": text}).json()
        back = c.post("/unredact", json={
            "text": red["redacted_text"], "token_map": red["token_map"]
        }).json()
    assert back["text"] == text
