"""Redactor: text -> redacted text + token map (Spec M1-06).

Top-level entry point that ties the already-built pieces together: the T5 input
guard (Spec M1-02), the Presidio analyzer (Spec M1-04), and the token engine's
map-merge + right-to-left replacement (Spec M1-01). The reverse direction is
:func:`prompt_redact_core.unredactor.unredact` (Spec M1-03).

``redact`` is thin, pure orchestration. It takes the analyzer as a parameter
rather than constructing one, because the analyzer owns the heavy spaCy model
and must be built once and reused — a new analyzer per call would reload the
model. Tests inject a fake analyzer to exercise the orchestration without
Presidio. See docs/specs/m1-06-redactor.html.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Mapping, Optional

from .guards import assert_no_token_shapes
from .tokens import apply_replacements, assign_tokens

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .analyzer import RedactionAnalyzer


def redact(
    text: str,
    token_map: Optional[Mapping[str, str]] = None,
    *,
    analyzer: "RedactionAnalyzer",
) -> tuple[str, dict[str, str]]:
    """Redact PII in ``text``, returning ``(redacted_text, token_map)``.

    The returned map is the caller-supplied map plus any newly minted entries —
    a fresh dict; the input is never mutated. Pass it back in on the next call so
    repeated identifiers keep the same token across a conversation (ADR 0002: the
    caller owns the map).

    Steps:

    1. **T5 guard** — reject input that already contains a ``[TYPE_N]`` token
       shape (raises ``TokenShapedInputError`` before any analysis).
    2. **Detect** — ``analyzer.analyze(text)`` returns non-overlapping
       ``Detection``s.
    3. **Assign** — merge detections against the supplied map, reusing tokens for
       known originals and minting new ones otherwise.
    4. **Replace** — splice tokens in right-to-left so offsets stay valid.

    ``analyzer`` is required (keyword-only): it owns the spaCy model and is meant
    to be built once and reused across calls. Any object with an
    ``analyze(text) -> list[Detection]`` method satisfies the contract.
    """
    assert_no_token_shapes(text)
    detections = analyzer.analyze(text)
    replacements, new_map = assign_tokens(detections, token_map or {})
    redacted_text = apply_replacements(text, replacements)
    return redacted_text, new_map
