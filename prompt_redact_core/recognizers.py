"""Custom Presidio recognizers for domain identifiers (Spec M1-05).

Presidio's out-of-the-box recognizers do not cover provider/payer identifiers.
This module adds the two that have a **self-validating checksum**, so they reach
high precision without depending on the (not-yet-tuned) confidence threshold:

* **NPI** — National Provider Identifier. 10 digits; the last is a Luhn check
  digit computed over ``"80840"`` + the first 9 digits.
* **DEA** — DEA registration number. Two letters + 7 digits; the 7th digit is a
  checksum over the first six.

Context-only identifiers without a checksum — **MRN, member ID, Rx number** — are
deliberately *not* here yet. A bare numeric pattern fires on every number at the
default threshold (M0 chose Presidio defaults), which would over-redact wildly.
They need the eval corpus to calibrate a threshold first, so they land with
Specs 07-08. See docs/specs/m1-05-recognizers.html.

The checksum validators below are pure (no Presidio import), so they are fully
unit-testable on their own. Presidio is imported lazily inside
:func:`build_custom_recognizers`, which the analyzer (Spec M1-04) calls only when
it builds the engine — so importing this module, or the package, never requires
the ML stack.
"""

from __future__ import annotations

import re

_NPI_RE = re.compile(r"\A\d{10}\Z")
_DEA_RE = re.compile(r"\A[A-Za-z]{2}(\d{7})\Z")

# NPI check digits are computed as if every NPI were prefixed with this issuer
# identifier (80840 = the ISO prefix assigned to the NPI numbering system).
_NPI_LUHN_PREFIX = "80840"


def _luhn_check_digit(payload: str) -> int:
    """Return the Luhn check digit for ``payload`` (a digit string, no check digit).

    Doubles every second digit starting from the rightmost payload digit (which
    is where the check digit will sit once appended).
    """
    total = 0
    for i, ch in enumerate(reversed(payload)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - (total % 10)) % 10


def is_valid_npi(text: str) -> bool:
    """True if ``text`` is a 10-digit NPI with a correct Luhn check digit."""
    if not _NPI_RE.match(text):
        return False
    return _luhn_check_digit(_NPI_LUHN_PREFIX + text[:9]) == int(text[9])


def is_valid_dea(text: str) -> bool:
    """True if ``text`` is a DEA number (2 letters + 7 digits) with a valid checksum.

    Checksum: ``(d1 + d3 + d5) + 2 * (d2 + d4 + d6)`` must end in the 7th digit.
    """
    m = _DEA_RE.match(text)
    if not m:
        return False
    d = [int(c) for c in m.group(1)]
    return (d[0] + d[2] + d[4] + 2 * (d[1] + d[3] + d[5])) % 10 == d[6]


def build_custom_recognizers() -> list:
    """Build the custom Presidio ``PatternRecognizer``s (NPI, DEA).

    Presidio is imported here, lazily, so the rest of the package stays
    importable without the ML stack. The recognizer subclasses are defined
    inside this function for the same reason — subclassing ``PatternRecognizer``
    at module level would force a top-level Presidio import.

    Each uses ``validate_result`` (Presidio's checksum hook, as the built-in
    credit-card/SSN recognizers do): a checksum-valid match is confirmed, an
    invalid one is discarded. So only genuinely valid NPIs/DEAs are emitted,
    independent of the confidence threshold.
    """
    from presidio_analyzer import Pattern, PatternRecognizer

    class _NpiRecognizer(PatternRecognizer):
        def __init__(self):
            super().__init__(
                supported_entity="NPI",
                patterns=[Pattern("npi (10 digits)", r"\b\d{10}\b", 0.1)],
                context=["npi", "national provider", "provider id", "provider number"],
            )

        def validate_result(self, pattern_text: str):
            return is_valid_npi(pattern_text)

    class _DeaRecognizer(PatternRecognizer):
        def __init__(self):
            super().__init__(
                supported_entity="DEA",
                patterns=[Pattern("dea (2 letters + 7 digits)", r"\b[A-Za-z]{2}\d{7}\b", 0.3)],
                context=["dea", "dea#", "dea number", "dea registration"],
            )

        def validate_result(self, pattern_text: str):
            return is_valid_dea(pattern_text)

    return [_NpiRecognizer(), _DeaRecognizer()]
