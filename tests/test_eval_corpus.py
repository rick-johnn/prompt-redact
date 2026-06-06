"""Tests for the eval corpus generator + model (Spec M1-07).

Pure-Python; no Presidio. Verifies the invariants the harness (Spec M1-08) will
rely on: offsets are exact, checksum identifiers are valid, generation is
deterministic, and the JSONL round-trips.
"""

import os

import pytest

from evals import (
    CorpusValidationError,
    Example,
    Span,
    dumps_jsonl,
    generate_corpus,
    load_corpus,
    loads_jsonl,
    validate_example,
)
from prompt_redact_core.recognizers import _luhn_check_digit, is_valid_dea, is_valid_npi

CORPUS = generate_corpus(seed=0, n_per_template=20)


# --- determinism ------------------------------------------------------------

def test_generation_is_deterministic():
    assert generate_corpus(seed=0, n_per_template=5) == generate_corpus(seed=0, n_per_template=5)


def test_different_seed_differs():
    a = generate_corpus(seed=0, n_per_template=5)
    b = generate_corpus(seed=1, n_per_template=5)
    assert [e.text for e in a] != [e.text for e in b]


# --- offsets exact (the core invariant) -------------------------------------

def test_every_example_validates():
    for ex in CORPUS:
        validate_example(ex)  # raises on any offset/overlap/value mismatch


def test_every_span_slices_to_its_value():
    for ex in CORPUS:
        for s in ex.spans:
            assert ex.text[s.start : s.end] == s.value


# --- checksum identifiers are genuinely valid -------------------------------

def test_npi_spans_are_checksum_valid():
    npis = [s.value for ex in CORPUS for s in ex.spans if s.entity_type == "NPI"]
    assert npis, "expected NPI spans in the corpus"
    assert all(is_valid_npi(v) for v in npis)


def test_dea_spans_are_checksum_valid():
    deas = [s.value for ex in CORPUS for s in ex.spans if s.entity_type == "DEA"]
    assert deas, "expected DEA spans in the corpus"
    assert all(is_valid_dea(v) for v in deas)


def test_credit_cards_are_luhn_valid():
    cards = [s.value for ex in CORPUS for s in ex.spans if s.entity_type == "CREDIT_CARD"]
    assert cards, "expected CREDIT_CARD spans in the corpus"
    for c in cards:
        assert len(c) == 16 and c[0] == "4"
        assert _luhn_check_digit(c[:15]) == int(c[15])


# --- coverage ---------------------------------------------------------------

def test_entity_type_coverage():
    types = {s.entity_type for ex in CORPUS for s in ex.spans}
    expected = {
        "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "US_SSN", "CREDIT_CARD",
        "DATE_TIME", "LOCATION", "NPI", "DEA", "MRN", "MEMBER_ID", "RX_NUMBER",
    }
    assert expected <= types


def test_domain_coverage():
    domains = {ex.domain for ex in CORPUS}
    assert {"healthcare", "finance", "pbm", "generic"} <= domains


def test_includes_a_no_pii_example():
    assert any(len(ex.spans) == 0 for ex in CORPUS)


def test_ids_are_unique():
    ids = [ex.id for ex in CORPUS]
    assert len(ids) == len(set(ids))


# --- JSONL round-trip -------------------------------------------------------

def test_jsonl_round_trip():
    assert loads_jsonl(dumps_jsonl(CORPUS)) == CORPUS


def test_jsonl_blank_lines_skipped():
    text = dumps_jsonl(CORPUS[:2]) + "\n   \n"
    assert loads_jsonl(text) == list(CORPUS[:2])


# --- validation catches malformed examples ----------------------------------

def test_validate_rejects_wrong_value():
    ex = Example("x", "test", "John called", (Span(0, 4, "PERSON", "Jane"),))
    with pytest.raises(CorpusValidationError):
        validate_example(ex)


def test_validate_rejects_out_of_bounds():
    ex = Example("x", "test", "hi", (Span(0, 5, "PERSON", "hi"),))
    with pytest.raises(CorpusValidationError):
        validate_example(ex)


def test_validate_rejects_overlap():
    ex = Example("x", "test", "John Doe", (
        Span(0, 4, "PERSON", "John"),
        Span(2, 8, "PERSON", "hn Doe"),
    ))
    with pytest.raises(CorpusValidationError):
        validate_example(ex)


def test_validate_rejects_empty_type():
    ex = Example("x", "test", "John", (Span(0, 4, "", "John"),))
    with pytest.raises(CorpusValidationError):
        validate_example(ex)


# --- committed sample -------------------------------------------------------

def test_committed_sample_loads_and_validates():
    sample = os.path.join(os.path.dirname(__file__), "..", "evals", "corpus", "sample.jsonl")
    examples = load_corpus(sample)
    assert examples
    for ex in examples:
        validate_example(ex)
