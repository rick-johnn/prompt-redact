"""Evaluation corpus for prompt-redact (Spec M1-07).

Synthetic, span-annotated data used to measure the redactor against the M0
quality bar (recall, precision, leakage). The corpus is *generated*
deterministically (no third-party data, no network, no extra dependency) so it
can be regenerated and audited from source. See docs/specs/m1-07-eval-corpus.html.

``models`` defines the on-disk JSONL shape and validation; ``generator`` mints
the examples. Neither imports Presidio — the corpus is pure data; the harness
(Spec M1-08) runs it through the redactor.
"""

from .models import (
    CorpusValidationError,
    Example,
    Span,
    dump_corpus,
    dumps_jsonl,
    load_corpus,
    loads_jsonl,
    validate_example,
)
from .generator import generate_corpus

__all__ = [
    "Span",
    "Example",
    "CorpusValidationError",
    "validate_example",
    "dumps_jsonl",
    "loads_jsonl",
    "load_corpus",
    "dump_corpus",
    "generate_corpus",
]
