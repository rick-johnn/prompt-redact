"""Scoring for the eval harness (Spec M1-08).

Pure functions over (gold, predicted) span pairs — no Presidio, no analyzer — so
the whole scoring layer is unit-testable. The harness (``run_eval``) supplies
predicted spans from the real analyzer; here we only count.

Matching is **exact character offset**: a gold span counts as caught only if a
predicted span has the same ``(start, end)``. A partial match (e.g. the detector
caught "Doe" but not "John Doe") is a miss — the visible remainder is a leak.
Type labels are not required to match for recall: what matters for redaction is
that the characters were caught, whatever the detector called them.

Gate (M0 decision, 2026-06-05): per-entity recall >= 0.99 on the types that have
recognizers. MRN / MEMBER_ID / RX_NUMBER recognizers are deferred (Spec 05), so
those types are reported but not gated. Leakage is reported, not gated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

RECALL_TARGET = 0.99

# Types with implemented recognizers — these are gated. Anything else (MRN,
# MEMBER_ID, RX_NUMBER) is reported only, until its recognizer lands and is tuned.
GATED_TYPES = frozenset(
    {
        "PERSON",
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "US_SSN",
        "CREDIT_CARD",
        "DATE_TIME",
        "LOCATION",
        "NPI",
        "DEA",
    }
)


def _offsets(spans) -> set:
    return {(s.start, s.end) for s in spans}


@dataclass
class Report:
    """Aggregated scores over a corpus.

    ``recall_counts``/``precision_counts`` map entity type -> ``[hit, total]``.
    """

    recall_counts: dict = field(default_factory=dict)
    precision_counts: dict = field(default_factory=dict)
    leaked_examples: int = 0
    n_examples: int = 0

    def recall(self) -> dict:
        return {t: (h / n if n else 0.0) for t, (h, n) in self.recall_counts.items()}

    def precision(self) -> dict:
        return {t: (h / n if n else 0.0) for t, (h, n) in self.precision_counts.items()}

    @property
    def leakage_rate(self) -> float:
        return self.leaked_examples / self.n_examples if self.n_examples else 0.0

    def gate_failures(self, target: float = RECALL_TARGET) -> list:
        """Gated types whose recall is below ``target`` (types with no gold are skipped)."""
        failures = []
        for t, (hit, total) in sorted(self.recall_counts.items()):
            if t in GATED_TYPES and total > 0 and hit / total < target:
                failures.append((t, hit / total, hit, total))
        return failures

    def passed(self, target: float = RECALL_TARGET) -> bool:
        return not self.gate_failures(target)

    def format(self, target: float = RECALL_TARGET) -> str:
        rec, prec = self.recall(), self.precision()
        types = sorted(set(self.recall_counts) | set(self.precision_counts))
        lines = [
            f"Eval over {self.n_examples} examples",
            f"{'entity':<16}{'recall':>9}{'prec':>8}{'gold':>7}  status",
            "-" * 52,
        ]
        for t in types:
            hit, total = self.recall_counts.get(t, (0, 0))
            r = f"{rec.get(t, 0.0):.3f}" if total else "  -  "
            p = f"{prec.get(t, 0.0):.3f}" if t in prec else "  -  "
            if t not in GATED_TYPES:
                status = "report"
            elif total == 0:
                status = "no gold"
            elif hit / total < target:
                status = "FAIL"
            else:
                status = "ok"
            lines.append(f"{t:<16}{r:>9}{p:>8}{total:>7}  {status}")
        lines.append("-" * 52)
        lines.append(
            f"leakage rate: {self.leakage_rate:.5f} "
            f"({self.leaked_examples}/{self.n_examples}) [reported, not gated]"
        )
        lines.append(f"GATE (recall >= {target} on gated types): "
                     f"{'PASS' if self.passed(target) else 'FAIL'}")
        return "\n".join(lines)


def score_corpus(pairs: Iterable[tuple[Sequence, Sequence]]) -> Report:
    """Aggregate scores over ``(gold_spans, predicted_spans)`` pairs.

    Recall is bucketed by gold type, precision by predicted type. An example
    "leaks" if any of its gold spans was not caught (exact-offset).
    """
    report = Report()
    for gold, predicted in pairs:
        report.n_examples += 1
        pred_off = _offsets(predicted)
        gold_off = _offsets(gold)
        leaked = False
        for g in gold:
            counts = report.recall_counts.setdefault(g.entity_type, [0, 0])
            counts[1] += 1
            if (g.start, g.end) in pred_off:
                counts[0] += 1
            else:
                leaked = True
        for p in predicted:
            counts = report.precision_counts.setdefault(p.entity_type, [0, 0])
            counts[1] += 1
            if (p.start, p.end) in gold_off:
                counts[0] += 1
        if leaked:
            report.leaked_examples += 1
    return report
