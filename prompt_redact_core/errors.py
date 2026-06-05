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
