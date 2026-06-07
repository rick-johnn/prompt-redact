"""Multi-turn conversation integration test (M2 Spec 04) — M2's exit criterion.

A synthetic caller drives a multi-turn conversation through the service,
round-tripping the token map (out of each /redact response, back into the next
/redact request) exactly as a real chat app would. Asserts:

  * cross-turn token stability — the same identifier keeps its token across turns;
  * new identifiers mint fresh, non-colliding tokens;
  * round-trip fidelity — /unredact restores an LLM-style reply.

The in-sandbox version injects a fake analyzer (deterministic detections), so it
proves the *service contract* end-to-end without Presidio. A Presidio-backed
variant is skipped if the model isn't installed.
"""

from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from prompt_redact_core.tokens import Detection  # noqa: E402
from prompt_redact_service.app import create_app  # noqa: E402


# Turn texts and their gold detections (offsets verified against the strings).
TURN1 = "Patient John Doe, MRN 12345."
TURN2 = "Jane Roe reviewed John Doe's chart."
DETECTIONS = {
    TURN1: [Detection(8, 16, "PERSON", "John Doe"), Detection(22, 27, "MRN", "12345")],
    TURN2: [Detection(0, 8, "PERSON", "Jane Roe"), Detection(18, 26, "PERSON", "John Doe")],
}


class ScriptedAnalyzer:
    def __init__(self, script, language="en"):
        self.config = SimpleNamespace(language=language)
        self._script = script

    def analyze(self, text):
        return list(self._script.get(text, []))


def test_multi_turn_conversation_through_the_service():
    app = create_app(lambda: ScriptedAnalyzer(DETECTIONS))
    with TestClient(app) as c:
        # Turn 1 — first redaction, empty starting map.
        r1 = c.post("/redact", json={"text": TURN1}).json()
        assert r1["redacted_text"] == "Patient [PERSON_1], MRN [MRN_1]."
        assert r1["token_map"] == {"[PERSON_1]": "John Doe", "[MRN_1]": "12345"}

        # Turn 2 — caller passes the accumulated map back in.
        r2 = c.post("/redact", json={"text": TURN2, "token_map": r1["token_map"]}).json()
        # John Doe REUSES [PERSON_1] across turns; Jane Roe mints [PERSON_2].
        assert r2["redacted_text"] == "[PERSON_2] reviewed [PERSON_1]'s chart."
        assert r2["token_map"] == {
            "[PERSON_1]": "John Doe",
            "[MRN_1]": "12345",
            "[PERSON_2]": "Jane Roe",
        }

        # An LLM reply comes back with tokens; unredact restores originals.
        reply = "I told [PERSON_1] that [PERSON_2] approved, re [MRN_1]."
        back = c.post("/unredact", json={"text": reply, "token_map": r2["token_map"]}).json()
        assert back["text"] == "I told John Doe that Jane Roe approved, re 12345."


def test_cross_turn_token_is_stable():
    # The same entity in two separate calls keeps the same token when the map
    # is round-tripped — the property that makes a conversation coherent.
    app = create_app(lambda: ScriptedAnalyzer(DETECTIONS))
    with TestClient(app) as c:
        m1 = c.post("/redact", json={"text": TURN1}).json()["token_map"]
        m2 = c.post("/redact", json={"text": TURN2, "token_map": m1}).json()["token_map"]
    assert m1["[PERSON_1]"] == "John Doe"
    assert m2["[PERSON_1]"] == "John Doe"  # unchanged across the turn


# --- Presidio-backed variant (skipped if the model is unavailable) ----------

@pytest.mark.integration
def test_multi_turn_with_real_analyzer():
    pytest.importorskip("presidio_analyzer")
    from prompt_redact_service.app import default_analyzer_provider

    try:
        provider_holds = default_analyzer_provider()  # warms the model
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"Presidio/model unavailable: {exc}")

    app = create_app(lambda: provider_holds)
    with TestClient(app) as c:
        t1 = "Email John Smith at john@example.com."
        r1 = c.post("/redact", json={"text": t1}).json()
        assert "John Smith" not in r1["redacted_text"]
        # Same person next turn, map passed back -> stable token.
        t2 = "John Smith replied."
        r2 = c.post("/redact", json={"text": t2, "token_map": r1["token_map"]}).json()
        person_tokens = [t for t, v in r2["token_map"].items() if v == "John Smith"]
        assert len(person_tokens) == 1  # one stable token for the person
        assert person_tokens[0] in r2["redacted_text"]
        # Round-trip the second turn.
        back = c.post("/unredact", json={
            "text": r2["redacted_text"], "token_map": r2["token_map"]
        }).json()
        assert back["text"] == t2
