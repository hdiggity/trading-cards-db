from datetime import datetime

from sqlalchemy import (JSON, Boolean, Column, DateTime, ForeignKey, Integer,
                        String, Text, func)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

from app.fields import sqlalchemy_card_columns

Base = declarative_base()


class Card(Base):
    """Main cards table for UI display - unique cards with quantity for duplicates"""
    __tablename__ = "cards"

    id = Column(Integer, primary_key=True, index=True)

    # inject all fields (shared + db-only)
    locals().update(sqlalchemy_card_columns)

    # relationship to complete card copies
    complete_cards = relationship("CardComplete", back_populates="card", cascade="all, delete-orphan")


class CardComplete(Base):
    """Complete card records - one row per physical card copy with full metadata"""
    __tablename__ = "cards_complete"

    id = Column(Integer, primary_key=True, autoincrement=True)
    card_id = Column(Integer, ForeignKey("cards.id", ondelete="CASCADE"), nullable=False, index=True)

    # Card data (denormalized for complete record) - matches cards table columns
    name = Column(String, nullable=False)
    sport = Column(String)
    brand = Column(String)
    number = Column(String)
    copyright_year = Column(String)
    team = Column(String)
    card_set = Column(String)
    condition = Column(String)
    is_player = Column(Boolean, default=True)
    features = Column(String)
    value_estimate = Column(String)
    notes = Column(Text)
    quantity = Column(Integer)
    last_updated = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Source/scan metadata columns specific to cards_complete
    source_file = Column(String, index=True)
    grid_position = Column(String)
    original_filename = Column(String)
    verification_date = Column(DateTime, server_default=func.now())
    verified_by = Column(String, default="user")
    cropped_back_file = Column(String)

    # relationship back to card
    card = relationship("Card", back_populates="complete_cards")


class UndoTransaction(Base):
    """Tracks reversible operations for comprehensive undo functionality."""
    __tablename__ = "undo_transactions"

    id = Column(Integer, primary_key=True)
    transaction_id = Column(String, unique=True, index=True, nullable=False)
    file_id = Column(String, index=True, nullable=False)
    action_type = Column(String, nullable=False)
    card_index = Column(Integer, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)

    before_state = Column(JSON)
    after_state = Column(JSON)
    is_reversed = Column(Boolean, default=False, nullable=False)
    reversed_at = Column(DateTime, nullable=True)
