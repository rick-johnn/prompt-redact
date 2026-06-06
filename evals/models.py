"""Corpus data model + JSONL IO + validation (Spec M1-07).

A corpus is a list of ``Example``s. Each carries the input ``text`` and the gold
``spans`` (character offsets), so scoring in the harness (Spec M1-08) is
offset-based, not surface-form-based. Pure-Python; no Presidio.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable


class CorpusValidationError(ValueError):
    """An example's spans are inconsistent with its text."""


@dataclass(frozen=True)
class Span:
    """A gold PII span: ``text[start:end] == value``, of type ``entity_type``."""

    start: int
    end: int
    entity_type: str
    value: str


@dataclass(frozen=True)
class Example:
    """One labelled input: ``text`` plus its gold ``spans``."""

    id: str
    domain: str
    text: str
    spans: tuple[Span, ...]


def validate_example(ex: Example) -> None:
    """Raise ``CorpusValidationError`` if any span is inconsistent.

    Checks, per span: in-bounds, ``start < end``, the slice equals ``value``, and
    a non-empty ``entity_type``; and across spans: no two overlap. These are the
    invariants the harness relies on for offset-based scoring.
    """
    n = len(ex.text)
    ordered = sorted(ex.spans, key=lambda s: (s.start, s.end))
    for s in ordered:
        if not s.entity_type:
            raise CorpusValidationError(f"{ex.id}: empty entity_type")
        if s.start < 0 or s.end > n or s.start >= s.end:
            raise CorpusValidationError(
                f"{ex.id}: span [{s.start}, {s.end}) out of bounds / inverted "
                f"for text length {n}"
            )
        if ex.text[s.start : s.end] != s.value:
            raise CorpusValidationError(
                f"{ex.id}: span [{s.start}, {s.end}) slices to "
                f"{ex.text[s.start : s.end]!r}, expected {s.value!r}"
            )
    for prev, nxt in zip(ordered, ordered[1:]):
        if nxt.start < prev.end:
            raise CorpusValidationError(
                f"{ex.id}: spans [{prev.start}, {prev.end}) and "
                f"[{nxt.start}, {nxt.end}) overlap"
            )


def _example_to_dict(ex: Example) -> dict:
    return {
        "id": ex.id,
        "domain": ex.domain,
        "text": ex.text,
        "spans": [
            {"start": s.start, "end": s.end, "type": s.entity_type, "value": s.value}
            for s in ex.spans
        ],
    }


def _example_from_dict(d: dict) -> Example:
    spans = tuple(
        Span(s["start"], s["end"], s["type"], s["value"]) for s in d.get("spans", [])
    )
    return Example(id=d["id"], domain=d["domain"], text=d["text"], spans=spans)


def dumps_jsonl(examples: Iterable[Example]) -> str:
    """Serialize examples to JSONL (one compact JSON object per line)."""
    lines = [
        json.dumps(_example_to_dict(ex), ensure_ascii=False, sort_keys=True)
        for ex in examples
    ]
    return "\n".join(lines) + ("\n" if lines else "")


def loads_jsonl(text: str) -> list[Example]:
    """Parse JSONL into examples, skipping blank lines."""
    return [
        _example_from_dict(json.loads(line))
        for line in text.splitlines()
        if line.strip()
    ]


def dump_corpus(examples: Iterable[Example], path) -> None:
    """Write examples as JSONL to ``path``."""
    examples = list(examples)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(dumps_jsonl(examples))


def load_corpus(path) -> list[Example]:
    """Read a JSONL corpus from ``path``."""
    with open(path, encoding="utf-8") as fh:
        return loads_jsonl(fh.read())
