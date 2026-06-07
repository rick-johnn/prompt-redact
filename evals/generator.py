"""Deterministic synthetic corpus generator (Spec M1-07).

Produces span-annotated ``Example``s with exact character offsets. Everything is
seeded, so a given ``seed`` always yields the same corpus — reproducible and
auditable, with no third-party data and no network.

Offsets are correct *by construction*: text is assembled from ``(chunk, type)``
parts via :func:`_assemble`, which tracks the running position, so a span can
never drift out of sync with its value.

Checksum-bearing identifiers are minted *valid* (NPI/DEA/credit card) using the
same algorithms the recognizers validate, so they are actually detectable —
``tests/test_eval_corpus.py`` cross-checks that with the real validators.

Entity-type names match Presidio's for built-ins (PERSON, EMAIL_ADDRESS, …) so
the harness (Spec M1-08) can compare predictions to gold by type.
"""

from __future__ import annotations

import random
import string
from typing import Callable

from prompt_redact_core.recognizers import _luhn_check_digit
from .models import Example, Span

_FIRST = ["John", "Jane", "Maria", "Wei", "Omar", "Aisha", "Carlos", "Priya", "Liam", "Noor"]
_LAST = ["Doe", "Smith", "Garcia", "Chen", "Khan", "Okafor", "Rossi", "Patel", "Nguyen", "Cohen"]
_CITY = ["Boston", "Chicago", "Seattle", "Denver", "Houston", "Atlanta", "Portland", "Dallas"]
_DEA_FIRST = list("ABFGMPRX")  # valid DEA registrant-type letters


def _digits(rng: random.Random, n: int) -> str:
    return "".join(rng.choice(string.digits) for _ in range(n))


# --- value providers (return the literal string to embed) -------------------

def _person(rng: random.Random) -> str:
    return f"{rng.choice(_FIRST)} {rng.choice(_LAST)}"


def _email(rng: random.Random) -> str:
    return f"{rng.choice(_FIRST).lower()}.{rng.choice(_LAST).lower()}@example.com"


def _nanp3(rng: random.Random) -> str:
    # NANP area code / exchange: leading digit 2-9 so the number validates
    # (Presidio's phone recognizer rejects NANP-invalid numbers).
    return f"{rng.randint(2, 9)}{rng.randint(0, 9)}{rng.randint(0, 9)}"


def _phone(rng: random.Random) -> str:
    return f"({_nanp3(rng)}) {_nanp3(rng)}-{_digits(rng, 4)}"


def _ssn(rng: random.Random) -> str:
    return f"{_digits(rng, 3)}-{_digits(rng, 2)}-{_digits(rng, 4)}"


def _date(rng: random.Random) -> str:
    return f"{rng.randint(1, 12):02d}/{rng.randint(1, 28):02d}/{rng.randint(1950, 2020)}"


def _city(rng: random.Random) -> str:
    # City-level LOCATION (a real city spaCy recognizes). Street-level addresses
    # are a known gap: stock Presidio has no street-address recognizer, so they
    # need a dedicated one (tracked for the recognizer-tuning step).
    return rng.choice(_CITY)


def _credit_card(rng: random.Random) -> str:
    # Visa-style: starts with 4, 16 digits, Luhn-valid (recognizers/Presidio check Luhn).
    body = "4" + _digits(rng, 14)
    return body + str(_luhn_check_digit(body))


def _npi(rng: random.Random) -> str:
    base = _digits(rng, 9)
    return base + str(_luhn_check_digit("80840" + base))


def _dea(rng: random.Random) -> str:
    letters = rng.choice(_DEA_FIRST) + rng.choice(string.ascii_uppercase)
    d = [int(c) for c in _digits(rng, 6)]
    check = (d[0] + d[2] + d[4] + 2 * (d[1] + d[3] + d[5])) % 10
    return letters + "".join(map(str, d)) + str(check)


def _mrn(rng: random.Random) -> str:
    return _digits(rng, rng.choice([6, 7, 8]))


def _member_id(rng: random.Random) -> str:
    return rng.choice(string.ascii_uppercase) + _digits(rng, 9)


def _rx(rng: random.Random) -> str:
    return _digits(rng, 7)


# --- templates: each returns (domain, parts) --------------------------------
# parts is a list of (chunk, entity_type_or_None); chunks with a type become spans.

def _t_health_visit(rng):
    return "healthcare", [
        ("Patient ", None), (_person(rng), "PERSON"),
        (", DOB ", None), (_date(rng), "DATE_TIME"),
        (", MRN ", None), (_mrn(rng), "MRN"),
        (", seen ", None), (_date(rng), "DATE_TIME"), (".", None),
    ]


def _t_health_provider(rng):
    return "healthcare", [
        ("Provider ", None), (_person(rng), "PERSON"),
        (" (NPI ", None), (_npi(rng), "NPI"),
        (", DEA ", None), (_dea(rng), "DEA"),
        (") ordered the lab.", None),
    ]


def _t_finance(rng):
    return "finance", [
        ("Account holder ", None), (_person(rng), "PERSON"),
        (", SSN ", None), (_ssn(rng), "US_SSN"),
        (", card ", None), (_credit_card(rng), "CREDIT_CARD"), (".", None),
    ]


def _t_pbm(rng):
    return "pbm", [
        ("Member ", None), (_person(rng), "PERSON"),
        (", member ID ", None), (_member_id(rng), "MEMBER_ID"),
        (", Rx ", None), (_rx(rng), "RX_NUMBER"),
        (" prescribed by NPI ", None), (_npi(rng), "NPI"), (".", None),
    ]


def _t_generic(rng):
    return "generic", [
        ("Contact ", None), (_person(rng), "PERSON"),
        (" at ", None), (_email(rng), "EMAIL_ADDRESS"),
        (" or ", None), (_phone(rng), "PHONE_NUMBER"),
        (", based in ", None), (_city(rng), "LOCATION"), (".", None),
    ]


def _t_no_pii(rng):
    return "generic", [(rng.choice([
        "The meeting is rescheduled to next week.",
        "Please review the attached summary.",
        "All systems are operating normally.",
    ]), None)]


_TEMPLATES: list[Callable] = [
    _t_health_visit,
    _t_health_provider,
    _t_finance,
    _t_pbm,
    _t_generic,
    _t_no_pii,
]


def _assemble(parts) -> tuple[str, tuple[Span, ...]]:
    """Build text from ``(chunk, type)`` parts, emitting a span per typed chunk."""
    out: list[str] = []
    spans: list[Span] = []
    pos = 0
    for chunk, etype in parts:
        if etype is not None:
            spans.append(Span(pos, pos + len(chunk), etype, chunk))
        out.append(chunk)
        pos += len(chunk)
    return "".join(out), tuple(spans)


def generate_corpus(seed: int = 0, n_per_template: int = 20) -> list[Example]:
    """Generate a deterministic corpus: ``n_per_template`` examples per template.

    The same ``seed`` always yields the same corpus.
    """
    rng = random.Random(seed)
    examples: list[Example] = []
    for template in _TEMPLATES:
        name = template.__name__.removeprefix("_t_")
        for i in range(n_per_template):
            domain, parts = template(rng)
            text, spans = _assemble(parts)
            examples.append(
                Example(id=f"{name}-{i:04d}", domain=domain, text=text, spans=spans)
            )
    return examples
