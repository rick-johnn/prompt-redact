"""Tests for the Presidio analyzer wrapper (Spec M1-04).

Split into pure tests (no model load) and integration tests (Presidio-backed,
skipped if the model is unavailable).
"""

import pytest

from prompt_redact_core.analyzer import (
    AnalyzerConfig,
    ScoredSpan,
    resolve_overlaps,
    to_detections,
)
from prompt_redact_core.tokens import Detection, assign_tokens


# ===========================================================================
# Pure tests — no Presidio, no model load
# ===========================================================================

def test_config_defaults():
    c = AnalyzerConfig()
    assert c.language == "en"
    assert c.score_threshold == 0.0
    assert c.entities is None
    assert c.spacy_model == "en_core_web_lg"


def _span(start, end, etype, score):
    return ScoredSpan(start, end, etype, score)


def test_resolve_overlaps_no_overlap_passthrough_sorted():
    spans = [_span(10, 14, "B", 0.5), _span(0, 4, "A", 0.5)]
    out = resolve_overlaps(spans)
    assert [(s.start, s.entity_type) for s in out] == [(0, "A"), (10, "B")]


def test_resolve_overlaps_higher_score_wins():
    # The email/URL case: same characters, email (1.0) beats url (0.5).
    email = _span(43, 59, "EMAIL_ADDRESS", 1.0)
    url = _span(48, 59, "URL", 0.5)
    out = resolve_overlaps([url, email])
    assert out == [email]


def test_resolve_overlaps_equal_score_longer_wins():
    short = _span(0, 4, "SHORT", 0.7)
    long = _span(0, 8, "LONG", 0.7)
    assert resolve_overlaps([short, long]) == [long]


def test_resolve_overlaps_equal_score_and_length_deterministic():
    a = _span(0, 4, "AAA", 0.7)
    b = _span(0, 4, "BBB", 0.7)
    # Tie broken by start then entity-type asc -> "AAA"; stable regardless of input order.
    assert resolve_overlaps([a, b]) == [a]
    assert resolve_overlaps([b, a]) == [a]


def test_resolve_overlaps_chain():
    a = _span(0, 10, "A", 0.9)
    b = _span(5, 15, "B", 0.8)   # overlaps both A and C
    c = _span(12, 20, "C", 0.95)
    out = resolve_overlaps([a, b, c])
    # C (0.95) and A (0.9) kept; B dropped (overlaps A). Sorted by start.
    assert [s.entity_type for s in out] == ["A", "C"]


def test_resolve_overlaps_touching_spans_both_kept():
    a = _span(0, 5, "A", 0.5)
    b = _span(5, 10, "B", 0.5)  # touches A but does not overlap
    assert resolve_overlaps([a, b]) == [a, b]


def test_resolve_overlaps_empty():
    assert resolve_overlaps([]) == []


def test_empty_entities_tuple_detects_nothing_without_building_engine():
    # Regression: an empty tuple is falsy and once collapsed to "all types".
    # It now means "detect nothing" and short-circuits before the engine loads,
    # so this needs no model.
    from prompt_redact_core.analyzer import RedactionAnalyzer

    a = RedactionAnalyzer(AnalyzerConfig(entities=()))
    assert a.analyze("John Smith emailed john@example.com") == []
    assert a._engine is None  # never built the engine


def test_to_detections_slices_and_sorts():
    text = "John met Jane"
    spans = [_span(9, 13, "PERSON", 0.9), _span(0, 4, "PERSON", 0.9)]
    dets = to_detections(spans, text)
    assert dets == [
        Detection(0, 4, "PERSON", "John"),
        Detection(9, 13, "PERSON", "Jane"),
    ]


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


SAMPLE = "John Smith emailed john@example.com from 212-555-1234."


@pytest.mark.integration
def test_detects_core_entity_types(analyzer):
    dets = analyzer.analyze(SAMPLE)
    found = {d.entity_type for d in dets}
    assert {"PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER"} <= found
    # Every detection slices back to the text it claims.
    for d in dets:
        assert SAMPLE[d.start : d.end] == d.text


@pytest.mark.integration
def test_person_span_is_correct(analyzer):
    dets = analyzer.analyze(SAMPLE)
    persons = [d for d in dets if d.entity_type == "PERSON"]
    assert any(d.text == "John Smith" for d in persons)


@pytest.mark.integration
def test_email_url_overlap_resolved_to_email(analyzer):
    dets = analyzer.analyze("contact me at john@example.com please")
    # The email wins; no URL span may cover characters inside the email.
    emails = [d for d in dets if d.entity_type == "EMAIL_ADDRESS"]
    assert emails, "expected an EMAIL_ADDRESS detection"
    email = emails[0]
    for d in dets:
        if d.entity_type == "URL":
            assert d.end <= email.start or d.start >= email.end  # no overlap


@pytest.mark.integration
def test_empty_input_returns_no_detections(analyzer):
    assert analyzer.analyze("") == []


@pytest.mark.integration
def test_threshold_filters_low_scores(analyzer):
    # Depends on the `analyzer` fixture only to gate on Presidio + model
    # availability (it skips if unavailable, like the other integration tests);
    # this test then builds its own custom-configured analyzer.
    from prompt_redact_core.analyzer import RedactionAnalyzer

    strict = RedactionAnalyzer(AnalyzerConfig(score_threshold=0.9))
    dets = strict.analyze(SAMPLE)
    # A perfect-score email survives a high threshold...
    assert any(d.entity_type == "EMAIL_ADDRESS" for d in dets)
    # ...while the low-score phone number (≈0.4) is filtered out.
    assert all(d.entity_type != "PHONE_NUMBER" for d in dets)


@pytest.mark.integration
def test_entities_restriction(analyzer):
    # Gated on the `analyzer` fixture for availability (see note above); builds
    # its own entity-restricted analyzer.
    from prompt_redact_core.analyzer import RedactionAnalyzer

    only_email = RedactionAnalyzer(AnalyzerConfig(entities=("EMAIL_ADDRESS",)))
    dets = only_email.analyze(SAMPLE)
    assert dets, "expected at least the email"
    assert {d.entity_type for d in dets} == {"EMAIL_ADDRESS"}


@pytest.mark.integration
def test_no_network_egress_tldextract_pinned_offline(analyzer):
    import tldextract

    # Building the engine must have pinned the extractor offline.
    assert getattr(tldextract.extract, "suffix_list_urls", None) == ()


@pytest.mark.integration
def test_output_composes_with_assign_tokens(analyzer):
    # The Detection contract holds end-to-end: analyzer output feeds the minter.
    dets = analyzer.analyze(SAMPLE)
    reps, token_map = assign_tokens(dets, {})
    assert len(reps) == len(dets)
    # Every minted token maps back to a slice of the original text.
    for tok, original in token_map.items():
        assert original in SAMPLE
