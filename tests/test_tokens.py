"""Unit tests for the token engine primitives (Spec M1-01).

Covers format/parse/find and right-to-left replacement. Map merge has its own
file, tests/test_map_merge.py.
"""

import pytest

from prompt_redact_core.errors import (
    InvalidEntityTypeError,
    OverlappingSpansError,
)
from prompt_redact_core.tokens import (
    Replacement,
    apply_replacements,
    find_tokens,
    format_token,
    parse_token,
)


# --- format_token -----------------------------------------------------------

def test_format_token_basic():
    assert format_token("PERSON", 1) == "[PERSON_1]"


def test_format_token_underscore_type():
    assert format_token("DATE_TIME", 3) == "[DATE_TIME_3]"


def test_format_token_multi_digit():
    assert format_token("PERSON", 12) == "[PERSON_12]"


@pytest.mark.parametrize("bad_type", ["person", "Person", "PERSON1", "P3RSON", "", "_LEAD"])
def test_format_token_rejects_invalid_type(bad_type):
    with pytest.raises(InvalidEntityTypeError):
        format_token(bad_type, 1)


@pytest.mark.parametrize("bad_n", [0, -1])
def test_format_token_rejects_non_positive_n(bad_n):
    with pytest.raises(ValueError):
        format_token("PERSON", bad_n)


# --- parse_token ------------------------------------------------------------

@pytest.mark.parametrize(
    "token,expected",
    [
        ("[PERSON_1]", ("PERSON", 1)),
        ("[DATE_TIME_3]", ("DATE_TIME", 3)),
        # The ambiguity case: must read as (PERSON, 12), not (PERSON_1, 2).
        ("[PERSON_12]", ("PERSON", 12)),
        ("[US_SSN_7]", ("US_SSN", 7)),
    ],
)
def test_parse_token_roundtrip(token, expected):
    assert parse_token(token) == expected
    # format_token is the inverse.
    assert format_token(*expected) == token


@pytest.mark.parametrize(
    "not_a_token",
    [
        "PERSON_1",          # no brackets
        "[PERSON_1] ",       # trailing space -> not a full match
        " [PERSON_1]",       # leading space
        "[person_1]",        # lowercase type
        "[PERSON_]",         # missing number
        "[PERSON]",          # no number at all
        "[PERSON_1][X_2]",   # two tokens, not one
        "[PERSON_0]",        # n must be >= 1 (we never mint _0)
        "[PERSON_01]",       # no leading zeros (we never mint _01)
        "[PERSON_007]",      # leading zeros must not alias to [PERSON_7]
        "",
    ],
)
def test_parse_token_rejects_non_tokens(not_a_token):
    assert parse_token(not_a_token) is None


# --- find_tokens ------------------------------------------------------------

def test_find_tokens_locates_all_with_offsets():
    text = "see [PERSON_1] and [DATE_TIME_2] now"
    matches = find_tokens(text)
    assert [(m.entity_type, m.n) for m in matches] == [("PERSON", 1), ("DATE_TIME", 2)]
    # Offsets round-trip to the exact token text.
    for m in matches:
        assert text[m.start : m.end] == m.token


def test_find_tokens_empty_when_none():
    assert find_tokens("no tokens here") == []


@pytest.mark.parametrize("text", ["[PERSON_0]", "[PERSON_01]", "[PERSON_007]"])
def test_find_tokens_ignores_zero_and_leading_zero(text):
    # The recognizer grammar matches only what we mint (n >= 1, no leading
    # zeros). Regression: previously [PERSON_0] matched and crashed .token.
    assert find_tokens(text) == []


def test_find_tokens_token_property_matches_slice_for_all_matches():
    # Invariant: every match's reconstructed .token equals the text it covers
    # (would break if leading-zero forms were matched).
    text = "[PERSON_1] [DATE_TIME_10] [US_SSN_100]"
    for m in find_tokens(text):
        assert text[m.start : m.end] == m.token


def test_find_tokens_adjacent():
    text = "[A_1][B_2]"
    matches = find_tokens(text)
    assert [(m.entity_type, m.n) for m in matches] == [("A", 1), ("B", 2)]
    assert (matches[0].start, matches[0].end) == (0, 5)
    assert (matches[1].start, matches[1].end) == (5, 10)


# --- apply_replacements -----------------------------------------------------

def test_apply_replacements_single():
    text = "hello WORLD"
    out = apply_replacements(text, [Replacement(6, 11, "[X_1]")])
    assert out == "hello [X_1]"


def test_apply_replacements_multiple_right_to_left():
    # Two spans of different widths; right-to-left keeps offsets valid.
    text = "John met Jane"
    reps = [Replacement(0, 4, "[PERSON_1]"), Replacement(9, 13, "[PERSON_2]")]
    assert apply_replacements(text, reps) == "[PERSON_1] met [PERSON_2]"


def test_apply_replacements_order_independent():
    text = "John met Jane"
    a = [Replacement(0, 4, "[PERSON_1]"), Replacement(9, 13, "[PERSON_2]")]
    b = list(reversed(a))
    assert apply_replacements(text, a) == apply_replacements(text, b)


def test_apply_replacements_empty():
    assert apply_replacements("unchanged", []) == "unchanged"


def test_apply_replacements_adjacent_spans_ok():
    # Touching but not overlapping (prev.end == next.start) is allowed.
    text = "ab"
    out = apply_replacements(text, [Replacement(0, 1, "[X_1]"), Replacement(1, 2, "[Y_1]")])
    assert out == "[X_1][Y_1]"


def test_apply_replacements_rejects_overlap():
    with pytest.raises(OverlappingSpansError):
        apply_replacements("abcd", [Replacement(0, 3, "[X_1]"), Replacement(2, 4, "[Y_1]")])


def test_apply_replacements_rejects_duplicate_identical_span():
    # The same span listed twice is an overlap, not a silent no-op.
    with pytest.raises(OverlappingSpansError):
        apply_replacements("abcd", [Replacement(0, 2, "[X_1]"), Replacement(0, 2, "[X_1]")])


def test_apply_replacements_unicode_offsets():
    # Offsets are code-point based; multi-byte chars must not shift the splice.
    text = "café résumé"  # 'é' is one code point; the space at index 4 is kept
    out = apply_replacements(text, [Replacement(0, 4, "[WORD_1]"), Replacement(5, 11, "[WORD_2]")])
    assert out == "[WORD_1] [WORD_2]"


@pytest.mark.parametrize(
    "rep",
    [
        Replacement(-1, 2, "[X_1]"),   # negative start
        Replacement(0, 99, "[X_1]"),   # end past length
        Replacement(3, 1, "[X_1]"),    # start > end
    ],
)
def test_apply_replacements_rejects_bad_spans(rep):
    with pytest.raises(ValueError):
        apply_replacements("abcd", [rep])
