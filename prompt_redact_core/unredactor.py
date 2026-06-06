"""Unredaction: token -> original substitution (Spec M1-03).

The reverse of :func:`prompt_redact_core.redactor.redact`. Pure-Python; reuses
``find_tokens`` and ``apply_replacements`` from
:mod:`prompt_redact_core.tokens`, so it inherits their single-pass,
right-to-left replacement — an original value that itself contains a
token-shaped substring is spliced in verbatim and never re-substituted.

Centralized here (rather than in the M2 service) so the substitution rules live
in one place and the milestone's round-trip exit criterion can be proven at the
library level. See docs/specs/m1-03-unredactor.html.
"""

from __future__ import annotations

from typing import Mapping

from .errors import UnknownTokenError
from .tokens import Replacement, apply_replacements, find_tokens


def unredact(text: str, token_map: Mapping[str, str]) -> str:
    """Replace every ``[TYPE_N]`` token in ``text`` with its original.

    ``token_map`` is the caller-owned ``token -> original`` map (the same shape
    ``redact`` returns). Lookup is by the tokens actually present in ``text``;
    the rest of the map is ignored.

    Raises ``UnknownTokenError`` if ``text`` contains a token absent from the
    map (all-or-nothing: nothing is substituted when this happens). Text with no
    token shapes — including the empty string — is returned unchanged.
    """
    replacements: list[Replacement] = []
    unknown = []

    for match in find_tokens(text):
        original = token_map.get(match.token)
        if original is None:  # `is None`, so an empty-string original is "known"
            unknown.append(match)
        else:
            replacements.append(Replacement(match.start, match.end, original))

    if unknown:
        first = unknown[0]
        raise UnknownTokenError(
            f"text contains {len(unknown)} token(s) absent from the map; first "
            f"is {first.token!r} at offset {first.start}. The text and map are "
            f"out of sync.",
            matches=unknown,
        )

    return apply_replacements(text, replacements)
