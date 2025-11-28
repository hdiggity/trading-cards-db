from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models import Base

# Get absolute path to database file (relative to project root)
PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "cards" / "verified" / "trading_cards.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)


# Strengthen SQLite durability and integrity
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    try:
        cursor = dbapi_connection.cursor()
        # Write-Ahead Logging improves crash safety for concurrent readers
        cursor.execute("PRAGMA journal_mode=WAL;")
        # FULL sync for maximum durability on power loss
        cursor.execute("PRAGMA synchronous=FULL;")
        # Enforce foreign key constraints
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()
    except Exception:
        # If not SQLite or PRAGMAs fail, continue without raising
        pass


def init_db():
    """Initialize database with all tables including logging tables."""
    Base.metadata.create_all(bind=engine)
    
    # Also initialize logging tables
    try:
        from app.logging_system import init_logging_tables
        init_logging_tables()
    except ImportError:
        pass  # Logging system not available


@contextmanager
def get_session():
    """Context manager for database sessions."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
