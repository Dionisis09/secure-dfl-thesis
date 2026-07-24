"""Optional blockchain audit layer for DFL experiments."""

from .blockchain import AuditBlockchain
from .verification import verify_chain

__all__ = ["AuditBlockchain", "verify_chain"]
