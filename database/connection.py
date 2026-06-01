import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import event

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
DB_PATH = os.path.join(DATA_DIR, 'database.db')

os.makedirs(DATA_DIR, exist_ok=True)
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_connection():
    # Legacy wrapper if any code still expects a raw sqlite3 connection directly
    return engine.raw_connection()

@contextmanager
def transact(lock):
    """
    Context manager for write operations using SQLAlchemy sessions.
    Acquires *lock*, yields a ``Session``, auto-commits on success,
    rolls back on exception, and always closes the session.
    """
    with lock:
        session = SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

@contextmanager
def read_only():
    """
    Context manager for read-only queries (no lock needed).
    Yields a ``Session`` and always closes it.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
