"""Presidio analyzer wrapper (Spec M1-04).

Wraps Presidio's ``AnalyzerEngine`` behind a small configurable surface that
returns the analyzer-agnostic ``Detection`` objects from
:mod:`prompt_redact_core.tokens`, so the redactor stays decoupled from Presidio
types. Presidio is imported **lazily** (inside engine construction): importing
this module — or the top-level package — does not require the ML stack.

The conversion and overlap logic operate on a tiny ``ScoredSpan`` value object,
not Presidio's ``RecognizerResult``, so they are pure and fast to unit-test
without loading the spaCy model. See docs/specs/m1-04-analyzer.html.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Sequence

from .tokens import Detection

if TYPE_CHECKING:  # pragma: no cover - typing only
    from presidio_analyzer import AnalyzerEngine

DEFAULT_LANGUAGE = "en"
DEFAULT_SPACY_MODEL = "en_core_web_lg"


@dataclass(frozen=True)
class ScoredSpan:
    """A candidate detection with a confidence score (pre-tokenization)."""

    start: int
    end: int
    entity_type: str
    score: float


@dataclass(frozen=True)
class AnalyzerConfig:
    """Configuration for :class:`RedactionAnalyzer`.

    ``score_threshold == 0.0`` means "Presidio defaults" (the M0 decision); it is
    tuned against the eval corpus in Specs 7-8. ``entities is None`` detects all
    supported types.
    """

    language: str = DEFAULT_LANGUAGE
    score_threshold: float = 0.0
    entities: Optional[tuple[str, ...]] = None
    spacy_model: str = DEFAULT_SPACY_MODEL


def _overlaps(a: ScoredSpan, b: ScoredSpan) -> bool:
    """True if the two half-open spans share any character (touching is not overlap)."""
    return a.start < b.end and b.start < a.end


def resolve_overlaps(spans: Sequence[ScoredSpan]) -> list[ScoredSpan]:
    """Pick a deterministic, non-overlapping subset of ``spans``.

    Presidio returns overlapping detections (e.g. EMAIL_ADDRESS vs URL over the
    same domain), but our right-to-left replacement rejects overlaps. Candidates
    are ranked by (score desc, length desc, start asc, entity-type asc) and kept
    greedily when they don't overlap an already-kept span — so highest
    confidence wins, ties favor the longer span, and the result is stable.
    """
    ranked = sorted(
        spans,
        key=lambda s: (-s.score, -(s.end - s.start), s.start, s.entity_type),
    )
    kept: list[ScoredSpan] = []
    for span in ranked:
        if any(_overlaps(span, k) for k in kept):
            continue
        kept.append(span)
    return sorted(kept, key=lambda s: (s.start, s.end))


def to_detections(spans: Sequence[ScoredSpan], text: str) -> list[Detection]:
    """Convert spans to ``Detection``s (slicing ``text``), sorted by offset."""
    return [
        Detection(s.start, s.end, s.entity_type, text[s.start : s.end])
        for s in sorted(spans, key=lambda s: (s.start, s.end))
    ]


def _ensure_offline_tldextract() -> None:
    """Pin tldextract's module-level extractor offline (threat-model hardening).

    Presidio's email recognizer calls ``tldextract.extract(...)``, whose default
    extractor fetches the public-suffix list over the network on first use. A PII
    redaction service must make no outbound calls while processing input, so we
    replace the module-level extractor with an offline one (snapshot only). The
    recognizer looks up ``tldextract.extract`` at call time, so this takes effect
    without patching Presidio. Idempotent.
    """
    import tldextract

    current = getattr(tldextract, "extract", None)
    if getattr(current, "suffix_list_urls", None) == ():
        return  # already offline
    tldextract.extract = tldextract.TLDExtract(suffix_list_urls=())


class RedactionAnalyzer:
    """Configurable wrapper over Presidio's ``AnalyzerEngine``.

    The engine (and the spaCy model) is built lazily on first ``analyze`` call.

    Thread-safety: a single instance is safe to ``analyze`` concurrently *once
    built*, but the lazy first build is not synchronized — two threads racing the
    very first ``analyze`` may each construct an engine (correct results, wasted
    load). The M2 service should build the engine eagerly at startup (call
    ``analyzer.engine`` once) before serving concurrent requests.
    """

    def __init__(self, config: Optional[AnalyzerConfig] = None):
        self.config = config or AnalyzerConfig()
        self._engine: Optional["AnalyzerEngine"] = None

    @property
    def engine(self) -> "AnalyzerEngine":
        if self._engine is None:
            self._engine = self._build_engine()
        return self._engine

    def _build_engine(self) -> "AnalyzerEngine":
        # Lazy, heavy imports — only when an engine is actually needed.
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider

        _ensure_offline_tldextract()

        provider = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [
                    {"lang_code": self.config.language, "model_name": self.config.spacy_model}
                ],
            }
        )
        nlp_engine = provider.create_engine()
        return AnalyzerEngine(
            nlp_engine=nlp_engine,
            supported_languages=[self.config.language],
        )

    def analyze(self, text: str) -> list[Detection]:
        """Detect PII in ``text`` and return clean, non-overlapping ``Detection``s."""
        entities = self.config.entities
        # entities is None -> all supported types; an explicitly empty tuple
        # means "detect nothing" and must not collapse (falsy) into "all".
        if entities is not None and len(entities) == 0:
            return []
        results = self.engine.analyze(
            text=text,
            language=self.config.language,
            entities=list(entities) if entities else None,
            score_threshold=self.config.score_threshold,
        )
        spans = [ScoredSpan(r.start, r.end, r.entity_type, r.score) for r in results]
        return to_detections(resolve_overlaps(spans), text)
