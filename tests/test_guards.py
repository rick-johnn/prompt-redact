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
