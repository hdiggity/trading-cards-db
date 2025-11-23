from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func
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

    # Source/scan metadata
    source_file = Column(String, index=True)
    source_position = Column(Integer)
    grid_position = Column(String)
    original_filename = Column(String)
    verification_date = Column(DateTime, server_default=func.now())
    verified_by = Column(String, default="user")
    condition_at_scan = Column(String)
    scan_quality = Column(String)
    notes = Column(Text)
    meta_data = Column(Text)

    # Card data (denormalized for complete record)
    name = Column(String)
    sport = Column(String)
    brand = Column(String)
    number = Column(String)
    copyright_year = Column(String)
    team = Column(String)
    card_set = Column(String)
    condition = Column(String)
    value_estimate = Column(String)
    features = Column(String)
    matched_front_file = Column(String)
    cropped_back_file = Column(String)

    # relationship back to card
    card = relationship("Card", back_populates="complete_cards")
