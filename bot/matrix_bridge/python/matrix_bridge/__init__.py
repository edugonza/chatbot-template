"""Python bindings over matrix-rust-sdk, shaped for bots.

Import from here; `matrix_bridge._native` is the compiled PyO3 module and is
an implementation detail.
"""

from ._native import MatrixError
from .client import (
    CrossSigningStatus,
    Emoji,
    EventHandler,
    MatrixClient,
    Session,
    VerificationHandler,
)

__all__ = [
    "CrossSigningStatus",
    "Emoji",
    "EventHandler",
    "MatrixClient",
    "MatrixError",
    "Session",
    "VerificationHandler",
]
