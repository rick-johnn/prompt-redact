"""Typed errors raised by the redactor core.

Every error the library raises derives from ``RedactError`` so callers can catch
the whole family with one ``except``.

Error -> meaning -> HTTP status. The status column is the mapping the M2 service
(``prompt_redact_service``) applies; it is documented here so a *direct,
non-HTTP* consumer of this library has the same error-to-meaning contract without
reverse-engineering the service layer. The library itself is transport-agnostic.

    RedactError              base of the family (catch-all)
    InvalidEntityTypeError   entity type is not ``[A-Z][A-Z_]*``        -> 400
    MalformedTokenMapError   a map key is not a valid token, or one
                             original is reachable from two tokens      -> 400
    OverlappingSpansError    two replacement spans overlap              -> 400
    TokenShapedInputError    redact input already contains a ``[TYPE_N]``
                             token-shaped substring (threat T5)         -> 400
    UnknownTokenError        unredact: a token in the text is absent
                             from the map (text and map out of sync)    -> 422
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


class _MatchCarryingError(RedactError):
    """Base for errors that carry the offending ``TokenMatch``es for diagnostics.

    The matches are passed in (rather than importing ``TokenMatch``) so this
    module stays free of any dependency on ``tokens``, which imports from here.
    """

    def __init__(self, message: str, matches=None):
        super().__init__(message)
        self.matches = list(matches) if matches is not None else []


class TokenShapedInputError(_MatchCarryingError):
    """Caller input already contains a redaction-token-shaped substring (T5).

    Carries the offending occurrences in ``matches`` so the M2 service can
    surface an explanatory ``400``.
    """


class UnknownTokenError(_MatchCarryingError):
    """``unredact`` found a token in the text that is not a key in the map.

    In a correct round trip this cannot happen (the T5 guard ensures redacted
    text only contains tokens we minted into the map), so it signals a corrupted
    or mismatched map. Carries the unmapped tokens in ``matches``.
    """
