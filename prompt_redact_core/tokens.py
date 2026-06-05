"""Token engine for prompt-redact (Spec M1-01).

Pure-Python core for the reversible ``[TYPE_N]`` token vocabulary: formatting,
parsing, the caller-supplied map merge (token assignment), and right-to-left
replacement. This module has **no Presidio/spaCy dependency**, so it is fully
unit-testable on its own; the redactor (Spec M1-06) wires it to the analyzer.

Token map contract (in-memory shape, this spec): a flat dict mapping
``token -> original``, e.g. ``{"[PERSON_1]": "John Doe"}``. The caller owns the
map and round-trips it on every call (ADR 0002). ``assign_tokens`` builds the
``original -> token`` reverse index internally so repeated identifiers reuse
their existing token.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping

from .errors import (
    InvalidEntityTypeError,
    MalformedTokenMapError,
    OverlappingSpansError,
)

# Entity types are uppercase letters and underscores only — digits are
# deliberately excluded so the ``_<N>`` numeric suffix parses unambiguously
# (otherwise ``[PERSON_12]`` could read as either (PERSON, 12) or (PERSON_1, 2)).
# See docs/specs/m1-01-token-engine.html. This is the same shape the T5 guard
# (Spec M1-02) keys on.
_TYPE = r"[A-Z][A-Z_]*"
TOKEN_RE = re.compile(rf"\[({_TYPE})_(\d+)\]")
_FULL_TOKEN_RE = re.compile(rf"^\[({_TYPE})_(\d+)\]$")
_VALID_TYPE_RE = re.compile(rf"^{_TYPE}$")


@dataclass(frozen=True)
class TokenMatch:
    """A single ``[TYPE_N]`` occurrence located in some text."""

    start: int
    end: int
    entity_type: str
    n: int

    @property
    def token(self) -> str:
        return format_token(self.entity_type, self.n)


@dataclass(frozen=True)
class Detection:
    """A detected PII span, analyzer-agnostic.

    Keeping this a plain value object (rather than a Presidio type) is what lets
    the map-merge be tested without the ML stack: tests construct detections by
    hand.
    """

    start: int
    end: int
    entity_type: str
    text: str


@dataclass(frozen=True)
class Replacement:
    """An instruction to replace ``text[start:end]`` with ``token``."""

    start: int
    end: int
    token: str


def format_token(entity_type: str, n: int) -> str:
    """Render ``[ENTITY_TYPE_N]``.

    Raises ``InvalidEntityTypeError`` if the type is not ``[A-Z][A-Z_]*`` and
    ``ValueError`` if ``n < 1``.
    """
    if not _VALID_TYPE_RE.match(entity_type):
        raise InvalidEntityTypeError(
            f"entity type {entity_type!r} must match [A-Z][A-Z_]* "
            "(uppercase letters and underscores, no digits)"
        )
    if n < 1:
        raise ValueError(f"token number must be >= 1, got {n}")
    return f"[{entity_type}_{n}]"


def parse_token(s: str) -> tuple[str, int] | None:
    """Parse a full token string into ``(entity_type, n)``, or ``None``.

    Only an exact, whole-string match counts — ``parse_token("x [PERSON_1]")``
    is ``None``. Use :func:`find_tokens` to locate tokens embedded in text.
    """
    m = _FULL_TOKEN_RE.match(s)
    if m is None:
        return None
    return m.group(1), int(m.group(2))


def find_tokens(text: str) -> list[TokenMatch]:
    """Return every ``[TYPE_N]`` occurrence in ``text``, in order."""
    return [
        TokenMatch(m.start(), m.end(), m.group(1), int(m.group(2)))
        for m in TOKEN_RE.finditer(text)
    ]


def assign_tokens(
    detections: Iterable[Detection],
    token_map: Mapping[str, str],
) -> tuple[list[Replacement], dict[str, str]]:
    """Merge detections against a caller-supplied map (the map-merge algorithm).

    Returns ``(replacements, new_map)``. The input ``token_map`` is never
    mutated; ``new_map`` is a fresh dict containing the supplied entries plus
    any newly minted ones.

    Behaviour (see Spec M1-01):

    * Same original value reuses its existing token, within a call and across
      calls when ``new_map`` is passed back in.
    * New originals mint ``max_existing_N + 1`` for their type, so numbering
      continues from the supplied map and per-type counters are independent.
    * Minting order follows detection ``(start, end)`` offsets, so the result
      is independent of the order detections are passed in.

    Raises ``MalformedTokenMapError`` if a map key is not a valid token or a
    single original is reachable from two different tokens.
    """
    reverse: dict[str, str] = {}  # original -> token
    max_n: dict[str, int] = {}  # entity_type -> highest N seen

    for token, original in token_map.items():
        parsed = parse_token(token)
        if parsed is None:
            raise MalformedTokenMapError(
                f"token map key {token!r} is not a well-formed [TYPE_N] token"
            )
        entity_type, n = parsed
        existing = reverse.get(original)
        if existing is not None and existing != token:
            raise MalformedTokenMapError(
                f"original {original!r} is mapped from both {existing!r} and "
                f"{token!r}; redact-side reuse would be ambiguous"
            )
        reverse[original] = token
        max_n[entity_type] = max(max_n.get(entity_type, 0), n)

    new_map = dict(token_map)
    replacements: list[Replacement] = []

    for det in sorted(detections, key=lambda d: (d.start, d.end)):
        token = reverse.get(det.text)
        if token is None:
            n = max_n.get(det.entity_type, 0) + 1
            max_n[det.entity_type] = n
            token = format_token(det.entity_type, n)
            reverse[det.text] = token
            new_map[token] = det.text
        replacements.append(Replacement(det.start, det.end, token))

    return replacements, new_map


def apply_replacements(text: str, replacements: Iterable[Replacement]) -> str:
    """Apply ``replacements`` to ``text``, right-to-left.

    Spans are validated (in-bounds, ``start <= end``, non-overlapping) and then
    spliced in descending start order, so each splice leaves the offsets of the
    not-yet-applied spans valid.

    Raises ``ValueError`` for out-of-bounds or inverted spans and
    ``OverlappingSpansError`` if two spans overlap.
    """
    ordered = sorted(replacements, key=lambda r: (r.start, r.end))

    for r in ordered:
        if r.start < 0 or r.end > len(text):
            raise ValueError(
                f"replacement span [{r.start}, {r.end}) out of bounds for "
                f"text of length {len(text)}"
            )
        if r.start > r.end:
            raise ValueError(
                f"replacement span [{r.start}, {r.end}) has start > end"
            )

    for prev, nxt in zip(ordered, ordered[1:]):
        if nxt.start < prev.end:
            raise OverlappingSpansError(
                f"replacement spans [{prev.start}, {prev.end}) and "
                f"[{nxt.start}, {nxt.end}) overlap"
            )

    out = text
    for r in sorted(ordered, key=lambda r: r.start, reverse=True):
        out = out[: r.start] + r.token + out[r.end :]
    return out
