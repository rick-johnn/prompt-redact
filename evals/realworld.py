"""Real-world / independent recall measurement (follow-up to the M1-08 gate).

The synthetic corpus (`generator.py`) and the recognizers share authorship, so a
high score there proves the pipeline is consistent and regression-free — but not
that real-world recall is high (the review's top finding). This module scores the
analyzer against an **external, independently-authored** corpus instead: a JSONL
file in the same `Example` format (see `models.py`), but written by hand to be
realistically messy/adversarial — ideally by someone who never saw the recognizer
code, to break the coupling.

It is **report-only**: real-world recall is informational, not the synthetic
regression gate, so it never fails a build. It reuses the exact scoring logic
(`run_eval.evaluate` / `metrics`) — only the corpus *source* differs.

PII WARNING: a real hand-labeled corpus may contain real identifiers. Keep such
files OUT of the repo (e.g. a gitignored `evals/corpus/real/` path); only
synthetic, adversarial samples are committed.

Usage:  python -m evals.realworld <corpus.jsonl> [spacy_model]
"""

from __future__ import annotations

import sys

from .models import load_corpus, validate_example
from .run_eval import evaluate


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: python -m evals.realworld <corpus.jsonl> [spacy_model]")
        return 2
    path, model = argv[0], (argv[1] if len(argv) > 1 else None)

    corpus = load_corpus(path)
    for ex in corpus:
        validate_example(ex)  # offsets must be internally consistent

    # Heavy import deferred to runtime.
    from prompt_redact_core.analyzer import AnalyzerConfig, RedactionAnalyzer

    cfg = AnalyzerConfig(spacy_model=model) if model else AnalyzerConfig()
    report = evaluate(corpus, RedactionAnalyzer(cfg))

    print("=" * 64)
    print("REAL-WORLD / INDEPENDENT CORPUS — informational, NOT the synthetic gate")
    print(f"corpus: {path}  ({report.n_examples} examples)")
    print("=" * 64)
    print(report.format())
    print(
        "\nNote: this is the honest real-world-ish picture on messy/independent\n"
        "data; recall here is expected to be below the synthetic-corpus gate, and\n"
        "the gap IS the product's true quality. (The committed sample is still\n"
        "synthetic-but-adversarial — a truly independent number needs a corpus\n"
        "hand-labeled by someone who never saw the recognizer code.)"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
