"""Tests for the real-world / independent recall harness (evals/realworld.py).

Pure tests load the committed adversarial sample and score it with a fake
analyzer (no Presidio). One integration test runs the real analyzer.
"""

import os

import pytest

from evals import evaluate, load_corpus, validate_example

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "evals", "corpus", "realworld_sample.jsonl")


def test_sample_loads_and_validates():
    corpus = load_corpus(SAMPLE)
    assert len(corpus) >= 20
    for ex in corpus:
        validate_example(ex)  # offsets internally consistent
    types = {s.entity_type for ex in corpus for s in ex.spans}
    # The sample deliberately spans easy + hard types, incl. ones with no recognizer.
    assert {"PERSON", "EMAIL_ADDRESS", "US_SSN", "LOCATION", "NPI", "DEA", "MRN"} <= types
    assert any(not ex.spans for ex in corpus)  # includes clean (no-PII) examples


class _BlindAnalyzer:
    """Detects nothing — to confirm the harness reports (doesn't crash) on misses."""

    def analyze(self, text):
        return []


def test_report_only_scoring_does_not_crash_on_total_miss():
    corpus = load_corpus(SAMPLE)
    report = evaluate(corpus, _BlindAnalyzer())
    assert report.n_examples == len(corpus)
    assert report.recall()["PERSON"] == 0.0          # blind misses everything
    assert report.leakage_rate > 0.0                  # and everything with gold "leaks"
    # report-only: no exception, scoring just records the (bad) numbers.


@pytest.mark.integration
def test_realworld_main_runs_report_only():
    pytest.importorskip("presidio_analyzer")
    from evals.realworld import main

    try:
        rc = main([SAMPLE])
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"Presidio/model unavailable: {exc}")
    assert rc == 0  # report-only: always exits 0, never gates a build
