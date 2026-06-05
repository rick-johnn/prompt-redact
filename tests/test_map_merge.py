"""Unit tests for the caller-supplied map merge (Spec M1-01, ``assign_tokens``).

These exercise the redactor's stability guarantees without any Presidio
dependency: detections are constructed by hand.
"""

import pytest

from prompt_redact_core.errors import MalformedTokenMapError
from prompt_redact_core.tokens import Detection, assign_tokens


def _det(start, end, etype, text):
    return Detection(start, end, etype, text)


def test_empty_map_mints_from_one():
    reps, new_map = assign_tokens([_det(0, 8, "PERSON", "John Doe")], {})
    assert new_map == {"[PERSON_1]": "John Doe"}
    assert reps[0].token == "[PERSON_1]"


def test_distinct_originals_numbered_by_appearance():
    dets = [_det(0, 4, "PERSON", "John"), _det(9, 13, "PERSON", "Jane")]
    reps, new_map = assign_tokens(dets, {})
    assert [r.token for r in reps] == ["[PERSON_1]", "[PERSON_2]"]
    assert new_map == {"[PERSON_1]": "John", "[PERSON_2]": "Jane"}


def test_repeated_original_reuses_token_within_call():
    # "John" appears twice -> one token, two replacement instructions.
    dets = [_det(0, 4, "PERSON", "John"), _det(14, 18, "PERSON", "John")]
    reps, new_map = assign_tokens(dets, {})
    assert [r.token for r in reps] == ["[PERSON_1]", "[PERSON_1]"]
    assert new_map == {"[PERSON_1]": "John"}


def test_cross_call_stability_via_returned_map():
    _, map1 = assign_tokens([_det(0, 4, "PERSON", "John")], {})
    # Second call: same person reused, new person continues numbering.
    dets2 = [_det(0, 4, "PERSON", "John"), _det(9, 13, "PERSON", "Jane")]
    reps2, map2 = assign_tokens(dets2, map1)
    assert [r.token for r in reps2] == ["[PERSON_1]", "[PERSON_2]"]
    assert map2 == {"[PERSON_1]": "John", "[PERSON_2]": "Jane"}


def test_numbering_continues_from_prepopulated_map():
    existing = {"[PERSON_1]": "Alice", "[PERSON_2]": "Bob"}
    reps, new_map = assign_tokens([_det(0, 3, "PERSON", "Cat")], existing)
    assert reps[0].token == "[PERSON_3]"
    assert new_map["[PERSON_3]"] == "Cat"


def test_per_type_counters_are_independent():
    dets = [
        _det(0, 4, "PERSON", "John"),
        _det(9, 21, "EMAIL_ADDRESS", "a@example.com"),
        _det(30, 34, "PERSON", "Jane"),
    ]
    reps, _ = assign_tokens(dets, {})
    assert [r.token for r in reps] == ["[PERSON_1]", "[EMAIL_ADDRESS_1]", "[PERSON_2]"]


def test_minting_independent_of_input_order():
    # Same detections, shuffled input order -> identical tokens by offset.
    a = [_det(0, 4, "PERSON", "John"), _det(9, 13, "PERSON", "Jane")]
    b = list(reversed(a))
    _, map_a = assign_tokens(a, {})
    _, map_b = assign_tokens(b, {})
    assert map_a == map_b == {"[PERSON_1]": "John", "[PERSON_2]": "Jane"}


def test_input_map_not_mutated():
    original = {"[PERSON_1]": "Alice"}
    snapshot = dict(original)
    assign_tokens([_det(0, 3, "PERSON", "Bob")], original)
    assert original == snapshot


def test_rejects_malformed_map_key():
    with pytest.raises(MalformedTokenMapError):
        assign_tokens([], {"PERSON_1": "John"})  # missing brackets


def test_rejects_ambiguous_original():
    bad = {"[PERSON_1]": "John", "[PERSON_2]": "John"}  # one original, two tokens
    with pytest.raises(MalformedTokenMapError):
        assign_tokens([], bad)
