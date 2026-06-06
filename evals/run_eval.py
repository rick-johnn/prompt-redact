"""Eval harness CLI + regression gate (Spec M1-08).

Runs the synthetic corpus (Spec M1-07) through the analyzer and scores detection
against the gold spans (``metrics``). Per-entity recall >= 0.99 on the gated
types is the M1 exit gate; leakage is reported. Exits non-zero if the gate fails,
so it can run in CI.

``evaluate`` takes the analyzer as an argument (any object with
``analyze(text) -> spans``), so the whole harness loop is unit-testable with a
fake analyzer — no Presidio needed. ``main`` wires the real
``RedactionAnalyzer`` and the generated corpus.

Recall is measured on the analyzer's detections, which is exactly what the
redactor redacts (it splices a token over every detected span), so detection
recall is redaction recall.

Usage:
    python -m evals.run_eval [n_per_template] [seed]
"""

from __future__ import annotations

import sys
from typing import Sequence

from .generator import generate_corpus
from .metrics import Report, score_corpus


def evaluate(corpus: Sequence, analyzer) -> Report:
    """Score ``corpus`` using ``analyzer`` (anything with ``analyze(text)``)."""
    return score_corpus((ex.spans, analyzer.analyze(ex.text)) for ex in corpus)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    n_per_template = int(argv[0]) if len(argv) > 0 else 50
    seed = int(argv[1]) if len(argv) > 1 else 0

    # Heavy import deferred to runtime so importing this module needs no ML stack.
    from prompt_redact_core.analyzer import RedactionAnalyzer

    corpus = generate_corpus(seed=seed, n_per_template=n_per_template)
    analyzer = RedactionAnalyzer()
    report = evaluate(corpus, analyzer)
    print(report.format())
    return 0 if report.passed() else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
