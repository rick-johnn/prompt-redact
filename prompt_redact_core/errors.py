"""Typed errors raised by the redactor core.

Every error the library raises derives from ``RedactError`` so callers (and the
future M2 HTTP layer) can catch the whole family with one ``except`` and map it
to a ``400``. Later specs extend this module — e.g. the T5 token-shaped-input
guard (M1-02) and the unredact collision check (M1-03).
"""

from __future__ import annotations


class RedactError(Exception):
    """Base class for all errors raised by the redactor core."""


class InvalidEntityTypeError(RedactError, ValueError):
    """An entity type does not match the ``[A-Z][A-Z_]*`` token grammar.

    Subclasses ``ValueError`` as well so existing ``except ValueError`` call
    sites keep working; it is still catchable via ``RedactError``.
    """


class MalformedTokenMapError(RedactError):
    """The caller-supplied token map violates an invariant.

    Either a key is not a well-formed token, or a single original value is
    reachable from two different tokens (which would make redact-side reuse
    ambiguous).
    """


class OverlappingSpansError(RedactError):
    """Two replacement spans overlap, so they cannot both be applied."""


class TokenShapedInputError(RedactError):
    """Caller input already contains a redaction-token-shaped substring (T5).

    Carries ``matches`` — the list of offending occurrences (``TokenMatch`` from
    :mod:`prompt_redact_core.tokens`) — so the M2 service can surface an
    explanatory ``400``. The constructor takes the message and the matches
    rather than a ``TokenMatch`` import, to keep this module free of any
    dependency on ``tokens`` (which imports from here).
    """

    def __init__(self, message: str, matches=None):
        super().__init__(message)
        self.matches = list(matches) if matches is not None else []


class UnknownTokenError(RedactError):
    """``unredact`` found a token in the text that is not a key in the map.

    In a correct round trip this cannot happen (the T5 guard ensures redacted
    text only contains tokens we minted into the map), so it signals a corrupted
    or mismatched map. Carries ``matches`` — the unmapped ``TokenMatch``es — for
    diagnostics. Takes the matches rather than importing ``TokenMatch`` to keep
    this module dependency-free.
    """

    def __init__(self, message: str, matches=None):
        super().__init__(message)
        self.matches = list(matches) if matches is not None else []
