"""Tests for custom recognizers (Spec M1-05).

The checksum validators are pure and tested without Presidio. Detection through
the live engine is covered by integration tests, skipped if the model is absent.
"""

import pytest

from prompt_redact_core.recognizers import (
    _luhn_check_digit,
    is_valid_dea,
    is_valid_npi,
)


# --- NPI checksum (pure) ----------------------------------------------------

@pytest.mark.parametrize("npi", ["1234567893", "1245319599"])
def test_valid_npi(npi):
    assert is_valid_npi(npi) is True


def test_npi_wrong_check_digit():
    # 1234567893 is valid; flipping the check digit makes it invalid.
    assert is_valid_npi("1234567890") is False


@pytest.mark.parametrize(
    "bad",
    [
        "",            # empty
        "123456789",   # 9 digits
        "12345678901",  # 11 digits
        "12345abcde",  # non-digit
        "123456789X",  # non-digit check position
    ],
)
def test_npi_rejects_malformed(bad):
    assert is_valid_npi(bad) is False


# --- DEA checksum (pure) ----------------------------------------------------

def test_valid_dea():
    # digits 1234563: (1+3+5) + 2*(2+4+6) = 9 + 24 = 33 -> last digit 3 == d7.
    assert is_valid_dea("AB1234563") is True


def test_dea_case_insensitive_letters():
    assert is_valid_dea("ab1234563") is True


def test_dea_wrong_checksum():
    assert is_valid_dea("AB1234567") is False


@pytest.mark.parametrize(
    "bad",
    [
        "",             # empty
        "A1234563",     # one letter
        "ABC123456",    # three letters
        "AB123456",     # 6 digits
        "AB12345678",   # 8 digits
        "1234563AB",    # wrong order
        "A_1234563",    # non-letter
    ],
)
def test_dea_rejects_malformed(bad):
    assert is_valid_dea(bad) is False


# --- Luhn helper ------------------------------------------------------------

def test_luhn_check_digit_known_value():
    # "80840" + "123456789" -> check digit 3 (the NPI 1234567893 case).
    assert _luhn_check_digit("80840123456789") == 3


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


@pytest.mark.integration
def test_valid_npi_detected(analyzer):
    dets = analyzer.analyze("Provider NPI 1245319599 wrote the order.")
    npis = [d for d in dets if d.entity_type == "NPI"]
    assert any(d.text == "1245319599" for d in npis)


@pytest.mark.integration
def test_checksum_invalid_number_not_flagged_as_npi(analyzer):
    # 1234567890 has a bad NPI check digit; it must not be an NPI (it may still
    # be picked up as some other type, e.g. a phone number — we only assert NPI).
    dets = analyzer.analyze("Reference number 1234567890 on file.")
    assert all(d.entity_type != "NPI" for d in dets)


@pytest.mark.integration
def test_valid_dea_detected(analyzer):
    dets = analyzer.analyze("Prescriber DEA AB1234563 on file.")
    deas = [d for d in dets if d.entity_type == "DEA"]
    assert any(d.text == "AB1234563" for d in deas)


@pytest.mark.integration
def test_custom_recognizers_can_be_disabled():
    from prompt_redact_core.analyzer import AnalyzerConfig, RedactionAnalyzer

    plain = RedactionAnalyzer(AnalyzerConfig(custom_recognizers=False))
    try:
        dets = plain.analyze("Provider NPI 1245319599 wrote the order.")
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"Presidio/model unavailable: {exc}")
    assert all(d.entity_type != "NPI" for d in dets)
