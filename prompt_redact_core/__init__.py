"""prompt-redact core: the standalone, importable redactor library (M1).

No HTTP surface, no LLM calls — pure redaction logic per ADR 0002. The token
engine (`tokens`) and error hierarchy (`errors`) are dependency-light and have
no Presidio/spaCy import, so they can be used and tested on their own.
"""

from .errors import (
    InvalidEntityTypeError,
    MalformedTokenMapError,
    OverlappingSpansError,
    RedactError,
    TokenShapedInputError,
)
from .guards import assert_no_token_shapes, contains_token_shapes
from .tokens import (
    TOKEN_RE,
    Detection,
    Replacement,
    TokenMatch,
    apply_replacements,
    assign_tokens,
    find_tokens,
    format_token,
    parse_token,
)

__all__ = [
    # errors
    "RedactError",
    "InvalidEntityTypeError",
    "MalformedTokenMapError",
    "OverlappingSpansError",
    "TokenShapedInputError",
    # guards (T5)
    "contains_token_shapes",
    "assert_no_token_shapes",
    # token engine
    "TOKEN_RE",
    "Detection",
    "Replacement",
    "TokenMatch",
    "format_token",
    "parse_token",
    "find_tokens",
    "assign_tokens",
    "apply_replacements",
]
