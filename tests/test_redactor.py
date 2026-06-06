"""Unit tests for redact() (Spec M1-06).

The orchestration (guard -> analyze -> assign -> replace) is exercised without
Presidio via a fake analyzer that returns hand-built Detections. A couple of
integration tests run the real analyzer and are skipped if the model is absent.
"""

import pytest

from prompt_redact_core.errors import TokenShapedInputError
from prompt_redact_core.redactor import redact
from prompt_redact_core.tokens import Detection
from prompt_redact_core.unredactor import unredact


class FakeAnalyzer:
    """Stand-in for RedactionAnalyzer: returns preset detections, records calls.

    The orchestration doesn't care where detections come from, so a fake that
    yields hand-built spans lets every redact() path be tested without the ML
    stack. ``calls`` records each analyzed text so tests can assert the guard
    runs before detection.
    """

    def __init__(self, detections=()):
        self._detections = list(detections)
        self.calls = []

    def analyze(self, text):
        self.calls.append(text)
        return list(self._detections)


# --- basic redaction (no Presidio) ------------------------------------------

def test_single_detection():
    text = "Patient John Doe"
    dets = [Detection(8, 16, "PERSON", "John Doe")]
    redacted, m = redact(text, analyzer=FakeAnalyzer(dets))
    assert redacted == "Patient [PERSON_1]"
    assert m == {"[PERSON_1]": "John Doe"}


def test_multiple_distinct_identifiers_get_distinct_tokens():
    text = "John met Jane"
    dets = [Detection(0, 4, "PERSON", "John"), Detection(9, 13, "PERSON", "Jane")]
    redacted, m = redact(text, analyzer=FakeAnalyzer(dets))
    assert redacted == "[PERSON_1] met [PERSON_2]"
    assert m == {"[PERSON_1]": "John", "[PERSON_2]": "Jane"}


def test_repeated_identifier_reuses_token_within_a_call():
    text = "John told John"
    dets = [Detection(0, 4, "PERSON", "John"), Detection(10, 14, "PERSON", "John")]
    redacted, m = redact(text, analyzer=FakeAnalyzer(dets))
    assert redacted == "[PERSON_1] told [PERSON_1]"
    assert m == {"[PERSON_1]": "John"}


def test_mixed_entity_types_number_independently():
    text = "Name: John Doe\nMRN: 12345"
    dets = [Detection(6, 14, "PERSON", "John Doe"), Detection(20, 25, "MRN", "12345")]
    redacted, m = redact(text, analyzer=FakeAnalyzer(dets))
    assert redacted == "Name: [PERSON_1]\nMRN: [MRN_1]"


# --- no-op cases ------------------------------------------------------------

def test_no_detections_is_identity():
    fake = FakeAnalyzer([])
    redacted, m = redact("no identifiers here", analyzer=fake)
    assert redacted == "no identifiers here"
    assert m == {}
    assert fake.calls == ["no identifiers here"]


def test_empty_text():
    redacted, m = redact("", analyzer=FakeAnalyzer([]))
    assert redacted == ""
    assert m == {}


# --- offset independence ----------------------------------------------------

def test_detections_out_of_order_number_by_offset():
    # Detections supplied Jane-first, but numbering follows text offset.
    text = "John met Jane"
    dets = [Detection(9, 13, "PERSON", "Jane"), Detection(0, 4, "PERSON", "John")]
    redacted, m = redact(text, analyzer=FakeAnalyzer(dets))
    assert redacted == "[PERSON_1] met [PERSON_2]"
    assert m == {"[PERSON_1]": "John", "[PERSON_2]": "Jane"}


# --- cross-call continuity --------------------------------------------------

def test_cross_call_reuses_known_and_mints_new():
    # Call 1 mints John -> [PERSON_1].
    _, m1 = redact("John here", analyzer=FakeAnalyzer([Detection(0, 4, "PERSON", "John")]))
    assert m1 == {"[PERSON_1]": "John"}

    # Call 2 passes m1 back: John reuses [PERSON_1], Jane mints [PERSON_2].
    text2 = "John and Jane"
    dets2 = [Detection(0, 4, "PERSON", "John"), Detection(9, 13, "PERSON", "Jane")]
    redacted2, m2 = redact(text2, m1, analyzer=FakeAnalyzer(dets2))
    assert redacted2 == "[PERSON_1] and [PERSON_2]"
    assert m2 == {"[PERSON_1]": "John", "[PERSON_2]": "Jane"}


def test_input_map_not_mutated():
    original = {"[PERSON_1]": "John"}
    text = "John and Jane"
    dets = [Detection(0, 4, "PERSON", "John"), Detection(9, 13, "PERSON", "Jane")]
    _, new_map = redact(text, original, analyzer=FakeAnalyzer(dets))
    assert original == {"[PERSON_1]": "John"}  # unchanged
    assert new_map is not original
    assert new_map == {"[PERSON_1]": "John", "[PERSON_2]": "Jane"}


# --- T5 guard runs first ----------------------------------------------------

def test_token_shaped_input_rejected_before_analysis():
    fake = FakeAnalyzer([Detection(0, 4, "PERSON", "John")])
    with pytest.raises(TokenShapedInputError):
        redact("contains a [PERSON_1] token", analyzer=fake)
    assert fake.calls == []  # guard short-circuits before analyze()


# --- round trip (no Presidio) -----------------------------------------------

def test_round_trip_with_fake_analyzer():
    text = "Update patient John Doe."
    dets = [Detection(15, 23, "PERSON", "John Doe")]
    redacted, m = redact(text, analyzer=FakeAnalyzer(dets))
    assert unredact(redacted, m) == text


# ===========================================================================
# Integration tests — real Presidio + spaCy model
# ===========================================================================

@pytest.fixture(scope="session")
def analyzer():
    pytest.importorskip("presidio_analyzer")
    from prompt_redact_core.analyzer import RedactionAnalyzer

    a = RedactionAnalyzer()
    try:
        a.analyze("warmup")  # forces engine + model load
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"Presidio/model unavailable: {exc}")
    return a


SAMPLE = "John Smith emailed john@example.com."


@pytest.mark.integration
def test_redact_real_round_trip_and_scrubs_identifiers(analyzer):
    redacted, m = redact(SAMPLE, analyzer=analyzer)
    # Raw identifiers must be gone from the redacted text...
    assert "John Smith" not in redacted
    assert "john@example.com" not in redacted
    # ...at least one token was minted...
    assert m, "expected at least one token minted"
    # ...and the round trip restores the original exactly.
    assert unredact(redacted, m) == SAMPLE


@pytest.mark.integration
def test_redact_real_rejects_token_shaped_input(analyzer):
    with pytest.raises(TokenShapedInputError):
        redact("already redacted [PERSON_1] text", analyzer=analyzer)
