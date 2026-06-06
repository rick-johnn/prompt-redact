"""Unit tests for the T5 token-shaped-input guard (Spec M1-02)."""

import pytest

from prompt_redact_core.errors import TokenShapedInputError
from prompt_redact_core.guards import (
    assert_no_token_shapes,
    contains_token_shapes,
)


# --- accepted: no token-shaped substring, guard is a no-op ------------------

ACCEPTED = [
    "",                              # empty input is accepted (M0 decision)
    "Just some plain text.",
    "Update patient John Doe, MRN 12345.",
    "[hello] and [world]",           # brackets, but not token-shaped
    "[PERSON]",                      # no number
    "[person_1]",                    # lowercase type -> never minted
    "[X1_2]",                        # digit in type -> never minted
    "[PERSON_1",                     # unclosed
    "PERSON_1]",                     # no opening bracket
    "[_X_1]",                        # leading underscore -> never minted
]


@pytest.mark.parametrize("text", ACCEPTED)
def test_accepted_inputs_pass(text):
    assert contains_token_shapes(text) is False
    # Should not raise.
    assert assert_no_token_shapes(text) is None


# --- rejected: contains a minted-token-shaped substring --------------------

REJECTED = [
    "[PERSON_1]",
    "Please review [PERSON_1] today.",
    "[DATE_TIME_3] is the appointment.",
    "[PERSON_12]",                   # multi-digit
    "[US_SSN_7]",
]


@pytest.mark.parametrize("text", REJECTED)
def test_rejected_inputs_raise(text):
    assert contains_token_shapes(text) is True
    with pytest.raises(TokenShapedInputError):
        assert_no_token_shapes(text)


# --- error payload ----------------------------------------------------------

def test_error_carries_first_match_offset_and_token():
    text = "hello [PERSON_1] world"
    with pytest.raises(TokenShapedInputError) as exc:
        assert_no_token_shapes(text)
    err = exc.value
    assert len(err.matches) == 1
    first = err.matches[0]
    assert first.token == "[PERSON_1]"
    assert text[first.start : first.end] == "[PERSON_1]"
    # Message names the first offender.
    assert "[PERSON_1]" in str(err)


def test_error_collects_all_matches():
    text = "[PERSON_1] met [PERSON_2] at [DATE_TIME_1]"
    with pytest.raises(TokenShapedInputError) as exc:
        assert_no_token_shapes(text)
    tokens = [m.token for m in exc.value.matches]
    assert tokens == ["[PERSON_1]", "[PERSON_2]", "[DATE_TIME_1]"]


# --- more behavioural edges -------------------------------------------------

def test_token_on_a_later_line_is_detected():
    # The scan is whole-text, not first-line; newlines don't hide a token.
    with pytest.raises(TokenShapedInputError):
        assert_no_token_shapes("a clean line\nthen a [PERSON_1] appears\nmore")


@pytest.mark.parametrize("boundary_text", ["[PERSON_1] tail", "head [PERSON_1]"])
def test_token_at_text_boundaries_rejected(boundary_text):
    with pytest.raises(TokenShapedInputError):
        assert_no_token_shapes(boundary_text)


@pytest.mark.parametrize("text", ["[A1B_2]", "[123_4]", "[1_2]"])
def test_digit_bearing_types_are_not_token_shaped(text):
    # Types must start with A-Z and contain no digits, so these can never be
    # confused with a minted token -> accepted.
    assert contains_token_shapes(text) is False
    assert assert_no_token_shapes(text) is None


@pytest.mark.parametrize("text", ["[PERSON_0]", "[PERSON_01]", "[PERSON_007]"])
def test_zero_and_leading_zero_forms_do_not_crash_and_are_accepted(text):
    # Regression: these once matched find_tokens and crashed .token with a raw
    # ValueError. They are not minted forms, so the guard must accept them
    # cleanly (no exception of any kind).
    assert contains_token_shapes(text) is False
    assert assert_no_token_shapes(text) is None
