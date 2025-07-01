from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base

DATABASE_URL = "sqlite:///./trading_cards.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)


def init_db():
    """Initialize database with all tables including logging tables"""
    Base.metadata.create_all(bind=engine)
    
    # Also initialize logging tables
    try:
        from app.logging_system import init_logging_tables
        init_logging_tables()
    except ImportError:
        pass  # Logging system not available


@contextmanager
def get_session():
    """Context manager for database sessions"""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
