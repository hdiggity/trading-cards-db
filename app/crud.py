from datetime import datetime
from typing import List, Optional

from sqlmodel import select

from app.database import get_session
from app.logging_system import ActionType, LogLevel, LogSource, logger
from app.models import Card, CardComplete
from app.per_card_export import write_per_card_file
from app.schemas import CardCreate


def upsert_card(card_data: CardCreate, image_path: str = None, source_metadata: dict = None):
    """
    DEPRECATED: Direct card insertion is deprecated.
    Use insert_card_complete() instead - cards table is now auto-synced from cards_complete via triggers.

    This function maintained for backward compatibility only.
    """
    # For backward compatibility, insert into cards_complete which will trigger sync to cards
    return insert_card_complete(card_data, source_metadata or {})


def insert_card_complete(card_data: CardCreate, source_metadata: dict = None):
    """
    Insert a new card into cards_complete table.
    The cards table will be automatically updated via database triggers.

    Args:
        card_data: Card information to insert
        source_metadata: Optional metadata about the source scan (source_file, position, etc.)

    Returns:
        The created CardComplete record
    """
    data = card_data.model_dump()
    source_metadata = source_metadata or {}

    with get_session() as sess:
        # Find or create the card_id (cards table entry will be created by trigger if needed)
        stmt = select(Card).where(
            Card.brand == data.get("brand"),
            Card.number == data.get("number"),
            Card.name == data.get("name"),
            Card.copyright_year == data.get("copyright_year"),
        )
        existing_card = sess.exec(stmt).first()
        card_id = existing_card.id if existing_card else None

        # If no existing card, we need to create a temporary one that will be updated by trigger
        if not card_id:
            temp_card = Card(**data)
            sess.add(temp_card)
            sess.flush()
            card_id = temp_card.id

        # Create CardComplete record (this will trigger update to cards table)
        card_complete = CardComplete(
            card_id=card_id,
            source_file=source_metadata.get('source_file'),
            grid_position=source_metadata.get('grid_position') or source_metadata.get('source_position'),
            original_filename=source_metadata.get('original_filename'),
            notes=source_metadata.get('notes'),
            # Card data fields
            name=data.get("name"),
            sport=data.get("sport"),
            brand=data.get("brand"),
            number=data.get("number"),
            copyright_year=data.get("copyright_year"),
            team=data.get("team"),
            card_set=data.get("card_set"),
            condition=data.get("condition"),
            is_player=data.get("is_player"),
            features=data.get("features"),
            value_estimate=data.get("value_estimate"),
            cropped_back_file=source_metadata.get('cropped_back_file'),
        )

        sess.add(card_complete)
        sess.commit()
        sess.refresh(card_complete)

        try:
            rec = f"{card_complete.name} #{card_complete.number or ''} {card_complete.brand or ''} {card_complete.copyright_year or ''}".strip()
            logger.log_database_operation(
                operation="insert", table="cards_complete", record_info=rec, success=True
            )
        except Exception:
            pass

        return card_complete


def list_cards() -> List[Card]:
    """Retrieve all cards in the database."""
    with get_session() as sess:
        rows = sess.exec(select(Card)).all()
        try:
            logger.log(
                LogLevel.INFO,
                LogSource.DATABASE,
                "List cards",
                ActionType.DB_QUERY,
                details=f"returned={len(rows)}",
            )
        except Exception:
            pass
        return rows


def get_card_by_id(card_id: int) -> Optional[Card]:
    """Fetch a single Card by its primary key."""
    with get_session() as sess:
        row = sess.get(Card, card_id)
        try:
            logger.log(
                LogLevel.INFO,
                LogSource.DATABASE,
                f"Get card by id {card_id}",
                ActionType.DB_QUERY,
                details="found" if row else "not_found",
            )
        except Exception:
            pass
        return row
