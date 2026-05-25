"""
Database connection management.

Provides a shared connection factory and context managers for
transactional (write) and read-only database access.
"""

import os
import sqlite3
from contextlib import contextmanager

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
DB_PATH = os.path.join(DATA_DIR, 'database.db')


def _dict_factory(cursor, row):
    """Row factory that returns dicts keyed by column name."""
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def get_connection():
    """Create a new SQLite connection with WAL mode and dict row factory."""
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.row_factory = _dict_factory
    return conn


@contextmanager
def transact(lock):
    """
    Context manager for write operations.

    Acquires *lock*, yields ``(conn, cursor)``, auto-commits on success,
    rolls back on exception, and always closes the connection.

    Usage::

        with transact(self.lock) as (conn, c):
            c.execute("UPDATE ...", (...))
    """
    with lock:
        conn = get_connection()
        try:
            c = conn.cursor()
            yield conn, c
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


@contextmanager
def read_only():
    """
    Context manager for read-only queries (no lock needed).

    Yields ``(conn, cursor)`` and always closes the connection.

    Usage::

        with read_only() as (conn, c):
            c.execute("SELECT ...", (...))
            rows = c.fetchall()
    """
    conn = get_connection()
    try:
        c = conn.cursor()
        yield conn, c
    finally:
        conn.close()
