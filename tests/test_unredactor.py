"""Unit tests for unredaction (Spec M1-03).

Includes the redact/unredact round-trip property, exercised without Presidio by
standing in synthetic detections for the analyzer.
"""

import pytest

from prompt_redact_core.errors import UnknownTokenError
from prompt_redact_core.tokens import Detection, apply_replacements, assign_tokens
from prompt_redact_core.unredactor import unredact


# --- basic substitution -----------------------------------------------------

def test_single_token():
    assert unredact("[PERSON_1] called", {"[PERSON_1]": "John"}) == "John called"


def test_multiple_tokens():
    text = "[PERSON_1] met [PERSON_2]"
    m = {"[PERSON_1]": "John", "[PERSON_2]": "Jane"}
    assert unredact(text, m) == "John met Jane"


def test_repeated_token_restores_same_original():
    text = "[PERSON_1] is [PERSON_1]"
    assert unredact(text, {"[PERSON_1]": "John"}) == "John is John"


# --- passthrough ------------------------------------------------------------

def test_empty_text():
    assert unredact("", {}) == ""


def test_no_tokens_passthrough():
    assert unredact("nothing to do here", {"[PERSON_1]": "John"}) == "nothing to do here"


# --- single-pass safety (the re-substitution trap) --------------------------

def test_original_containing_token_shape_is_not_resubstituted():
    # The inserted original holds "[X_1]"; it must survive verbatim and must
    # NOT trigger an unknown-token lookup.
    text = "[PERSON_1] arrived"
    m = {"[PERSON_1]": "agent [X_1] smith"}
    assert unredact(text, m) == "agent [X_1] smith arrived"


def test_token_valued_original_is_not_recursively_resolved():
    # The dangerous case the test above does NOT prove: the inserted value is
    # itself a *known* token. A recursive implementation would silently leak
    # "SHOULD_NOT_APPEAR"; the single-pass guarantee must yield "[PERSON_2]"
    # verbatim. This is a wrong-result (leak) failure mode, not a raised error.
    m = {"[PERSON_1]": "[PERSON_2]", "[PERSON_2]": "SHOULD_NOT_APPEAR"}
    assert unredact("[PERSON_1]", m) == "[PERSON_2]"


def test_adjacent_tokens():
    m = {"[A_1]": "X", "[B_1]": "Y"}
    assert unredact("[A_1][B_1]", m) == "XY"


def test_tokens_at_text_boundaries():
    m = {"[PERSON_1]": "John", "[PERSON_2]": "Jane"}
    # Token at the very start and the very end of the string.
    assert unredact("[PERSON_1] and [PERSON_2]", m) == "John and Jane"


# --- unknown token (strict, all-or-nothing) ---------------------------------

def test_unknown_token_raises():
    with pytest.raises(UnknownTokenError):
        unredact("[PERSON_9] missing", {})


def test_unknown_token_payload():
    text = "ok [PERSON_1] then [PERSON_2]"
    with pytest.raises(UnknownTokenError) as exc:
        unredact(text, {"[PERSON_1]": "John"})  # PERSON_2 absent
    unknown = [m.token for m in exc.value.matches]
    assert unknown == ["[PERSON_2]"]
    assert "[PERSON_2]" in str(exc.value)


def test_partially_known_text_substitutes_nothing():
    # All-or-nothing: a single unknown token aborts the whole call.
    text = "[PERSON_1] and [PERSON_2]"
    with pytest.raises(UnknownTokenError):
        unredact(text, {"[PERSON_1]": "John"})


def test_empty_valued_mapping_is_known():
    # A token mapping to "" substitutes to nothing rather than raising.
    assert unredact("x[REDACTED_1]y", {"[REDACTED_1]": ""}) == "xy"


@pytest.mark.parametrize("text", ["[PERSON_0] x", "say [PERSON_01] now", "[PERSON_007]"])
def test_zero_and_leading_zero_forms_pass_through_without_crash(text):
    # Regression: these once crashed in unredact (.token raised ValueError).
    # They are not minted token forms, so they are left untouched.
    assert unredact(text, {"[PERSON_7]": "LEAK"}) == text


# --- round-trip property (no Presidio): mint -> replace -> unredact ----------

def _redact(text, detections, token_map=None):
    """Stand-in for redact() using only the pure token pipeline."""
    reps, new_map = assign_tokens(detections, token_map or {})
    return apply_replacements(text, reps), new_map


def test_round_trip_basic():
    text = "Update patient John Doe, seen by Jane."
    dets = [
        Detection(15, 23, "PERSON", "John Doe"),
        Detection(33, 37, "PERSON", "Jane"),
    ]
    redacted, m = _redact(text, dets)
    assert redacted == "Update patient [PERSON_1], seen by [PERSON_2]."
    assert unredact(redacted, m) == text


def test_round_trip_repeated_identifier():
    text = "John told John to call John"
    dets = [
        Detection(0, 4, "PERSON", "John"),
        Detection(10, 14, "PERSON", "John"),
        Detection(23, 27, "PERSON", "John"),
    ]
    redacted, m = _redact(text, dets)
    assert redacted == "[PERSON_1] told [PERSON_1] to call [PERSON_1]"
    assert unredact(redacted, m) == text


def test_round_trip_unicode():
    text = "Café owner José Núñez emailed."
    dets = [Detection(11, 21, "PERSON", "José Núñez")]
    redacted, m = _redact(text, dets)
    assert unredact(redacted, m) == text


def test_round_trip_no_pii_is_identity():
    text = "No identifiers in this sentence."
    redacted, m = _redact(text, [])
    assert redacted == text
    assert unredact(redacted, m) == text


def test_round_trip_multiline():
    text = "Name: John Doe\nMRN: 12345\n"
    dets = [
        Detection(6, 14, "PERSON", "John Doe"),
        Detection(20, 25, "MRN", "12345"),
    ]
    redacted, m = _redact(text, dets)
    assert redacted == "Name: [PERSON_1]\nMRN: [MRN_1]\n"
    assert unredact(redacted, m) == text
