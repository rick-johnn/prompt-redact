"""Tests for the eval harness (Spec M1-08).

The scoring layer and the evaluate() loop are exercised without Presidio: gold
and predicted spans are supplied directly, and evaluate() runs against a fake
analyzer. A real-Presidio integration test is skipped if unavailable.
"""

import pytest

from evals import Example, Span, evaluate, generate_corpus, score_corpus
from evals.metrics import RECALL_TARGETS, Report


def _g(start, end, etype):
    return Span(start, end, etype, "x")  # value irrelevant to scoring


# --- score_corpus: recall / precision / leakage -----------------------------

def test_perfect_detection():
    gold = [_g(0, 4, "PERSON")]
    pred = [_g(0, 4, "PERSON")]
    r = score_corpus([(gold, pred)])
    assert r.recall()["PERSON"] == 1.0
    assert r.precision()["PERSON"] == 1.0
    assert r.leakage_rate == 0.0


def test_missed_span_is_recall_miss_and_leak():
    gold = [_g(0, 4, "PERSON"), _g(10, 15, "PERSON")]
    pred = [_g(0, 4, "PERSON")]  # second gold missed
    r = score_corpus([(gold, pred)])
    assert r.recall_counts["PERSON"] == [1, 2]
    assert r.recall()["PERSON"] == 0.5
    assert r.leaked_examples == 1
    assert r.leakage_rate == 1.0


def test_false_positive_is_precision_miss_not_leak():
    gold = [_g(0, 4, "PERSON")]
    pred = [_g(0, 4, "PERSON"), _g(20, 24, "PERSON")]  # extra prediction
    r = score_corpus([(gold, pred)])
    assert r.recall()["PERSON"] == 1.0
    assert r.precision_counts["PERSON"] == [1, 2]
    assert r.leakage_rate == 0.0  # over-redaction doesn't leak


def test_partial_offset_match_is_a_miss():
    gold = [_g(0, 8, "PERSON")]       # "John Doe"
    pred = [_g(5, 8, "PERSON")]       # caught "Doe" only
    r = score_corpus([(gold, pred)])
    assert r.recall()["PERSON"] == 0.0
    assert r.leaked_examples == 1


def test_recall_is_type_agnostic_for_catching():
    # Detector caught the exact span but labelled it differently: still caught.
    gold = [_g(0, 4, "MRN")]
    pred = [_g(0, 4, "US_DRIVER_LICENSE")]
    r = score_corpus([(gold, pred)])
    assert r.recall()["MRN"] == 1.0


def test_no_gold_example_never_leaks():
    r = score_corpus([([], [_g(0, 4, "PERSON")])])
    assert r.leaked_examples == 0
    assert r.leakage_rate == 0.0


def test_empty_corpus():
    r = score_corpus([])
    assert r.n_examples == 0
    assert r.leakage_rate == 0.0
    assert r.passed() is True


# --- gate logic -------------------------------------------------------------

def _recall_pairs(etype, hits, total):
    pairs = [([_g(0, 4, etype)], [_g(0, 4, etype)]) for _ in range(hits)]
    pairs += [([_g(0, 4, etype)], []) for _ in range(total - hits)]
    return pairs


def test_checksum_type_below_099_fails():
    # US_SSN at 0.98 (< 0.99 checksum-tier target) -> gate fails.
    r = score_corpus(_recall_pairs("US_SSN", 98, 100))
    assert [f[0] for f in r.gate_failures()] == ["US_SSN"]
    assert r.passed() is False


def test_ner_tier_097_boundary():
    # PERSON tier is 0.97: 0.97 passes, 0.96 fails.
    assert score_corpus(_recall_pairs("PERSON", 97, 100)).passed() is True
    assert score_corpus(_recall_pairs("PERSON", 96, 100)).passed() is False


def test_pattern_tier_095_boundary():
    # PHONE_NUMBER tier is 0.95: 0.95 passes, 0.94 fails.
    assert score_corpus(_recall_pairs("PHONE_NUMBER", 95, 100)).passed() is True
    assert score_corpus(_recall_pairs("PHONE_NUMBER", 94, 100)).passed() is False


def test_report_only_type_does_not_fail_gate():
    # MRN is context-only -> report-only, not gated, even at 0.0 recall.
    r = score_corpus([([_g(0, 4, "MRN")], [])])
    assert "MRN" not in RECALL_TARGETS
    assert r.gate_failures() == []
    assert r.passed() is True


def test_gated_type_at_target_passes():
    r = score_corpus(_recall_pairs("DEA", 100, 100))
    assert r.passed() is True
    assert r.recall()["DEA"] == 1.0


def test_format_smoke():
    r = score_corpus([([_g(0, 4, "PERSON")], [_g(0, 4, "PERSON")])])
    out = r.format()
    assert "GATE" in out and "PASS" in out and "leakage rate" in out


# --- evaluate() with a fake analyzer (no Presidio) --------------------------

class _FakeAnalyzer:
    """Returns gold spans for known texts, simulating perfect detection."""

    def __init__(self, mapping):
        self._mapping = mapping  # text -> list of spans

    def analyze(self, text):
        return self._mapping.get(text, [])


def test_evaluate_with_fake_analyzer_perfect():
    corpus = [
        Example("a", "t", "John called", (Span(0, 4, "PERSON", "John"),)),
        Example("b", "t", "no pii", ()),
    ]
    fake = _FakeAnalyzer({"John called": [Span(0, 4, "PERSON", "John")]})
    r = evaluate(corpus, fake)
    assert r.n_examples == 2
    assert r.recall()["PERSON"] == 1.0
    assert r.passed() is True


def test_evaluate_detects_a_gap():
    corpus = [Example("a", "t", "John called", (Span(0, 4, "PERSON", "John"),))]
    blind = _FakeAnalyzer({})  # detects nothing
    r = evaluate(corpus, blind)
    assert r.recall()["PERSON"] == 0.0
    assert r.passed() is False


# ===========================================================================
# Integration — real Presidio over the generated corpus (skipped if absent)
# ===========================================================================

@pytest.mark.integration
def test_harness_runs_end_to_end_with_real_analyzer():
    pytest.importorskip("presidio_analyzer")
    from prompt_redact_core.analyzer import RedactionAnalyzer

    analyzer = RedactionAnalyzer()
    try:
        analyzer.analyze("warmup")
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"Presidio/model unavailable: {exc}")

    corpus = generate_corpus(seed=0, n_per_template=3)
    report = evaluate(corpus, analyzer)
    assert isinstance(report, Report)
    assert report.n_examples == len(corpus)
    # Email is a strong, high-precision detector — sanity check it's caught.
    assert report.recall().get("EMAIL_ADDRESS", 0.0) > 0.0
