"""
Base repository providing shared helpers for all domain repositories.
"""

import threading

from ..connection import transact, read_only


class BaseRepository:
    """Thin base class that gives every repo access to the shared lock."""

    def __init__(self, lock: threading.Lock):
        self._lock = lock

    # Convenience wrappers so sub-classes don't need to import directly.

    def _transact(self):
        """Return a context manager for write operations."""
        return transact(self._lock)

    @staticmethod
    def _read_only():
        """Return a context manager for read-only queries."""
        return read_only()
