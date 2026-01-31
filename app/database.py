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
        cursor.execute("PRAGMA journal_mode=DELETE;")
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
    """Context manager for database sessions with logging."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
        _log_db_event("commit", "session committed successfully")
    except Exception as e:
        session.rollback()
        _log_db_event("rollback", f"session rolled back: {e}", error=True)
        raise
    finally:
        session.close()


def _log_db_event(event_type: str, message: str, error: bool = False):
    """Log database events to integrity log."""
    try:
        from app.logging_system import log_db_operation
        log_db_operation(event_type, "session", details=message, success=not error)
    except ImportError:
        pass  # Logging not available


def run_startup_integrity_check():
    """Run integrity check on database startup."""
    try:
        import os

        from app.db_integrity import run_full_check

        # Only run if db exists
        if not DB_PATH.exists():
            return

        # Check if we should auto-fix (env var)
        auto_fix = os.environ.get("DB_AUTO_FIX", "false").lower() == "true"

        issues = run_full_check(auto_fix=auto_fix)

        if issues and not auto_fix:
            print(f"WARNING: Database has {len(issues)} integrity issues. "
                  f"Set DB_AUTO_FIX=true to auto-repair.")

    except ImportError:
        pass  # Integrity module not available
    except Exception as e:
        print(f"Integrity check failed: {e}")
