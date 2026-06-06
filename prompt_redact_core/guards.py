"""Input guards for the redactor core (Spec M1-02).

Currently the threat-T5 guard: reject caller input that already contains a
substring shaped like one of our minted ``[TYPE_N]`` tokens. Pure-Python; no
Presidio dependency. It deliberately reuses ``find_tokens`` (and therefore
``TOKEN_RE``) from :mod:`prompt_redact_core.tokens`, so the guard and the
minter share a single definition of what a token looks like — see
docs/specs/m1-02-t5-guard.html for why this is narrower than the plan's
``[A-Z_]+`` sketch.

This guard is a *redact-path* precondition only. It must not run on
``unredact`` input, which is supposed to be full of tokens.
"""

from __future__ import annotations

from .errors import TokenShapedInputError
from .tokens import TokenMatch, find_tokens


def contains_token_shapes(text: str) -> bool:
    """Return ``True`` if ``text`` contains any minted-token-shaped substring."""
    return bool(find_tokens(text))


def assert_no_token_shapes(text: str) -> None:
    """Raise ``TokenShapedInputError`` if ``text`` contains token-shaped substrings.

    The raised error carries every offending match (``.matches``) so callers and
    the M2 service can build an explanatory ``400``.
    """
    matches: list[TokenMatch] = find_tokens(text)
    if not matches:
        return
    first = matches[0]
    raise TokenShapedInputError(
        f"input contains {len(matches)} token-shaped substring(s) matching the "
        f"redaction token format [TYPE_N]; first is {first.token!r} at offset "
        f"{first.start}. Callers must not submit text containing redaction tokens.",
        matches=matches,
    )
