from datetime import datetime
from typing import List, Optional

from sqlmodel import select

from app.database import get_session
from app.logging_system import logger, LogSource, ActionType, LogLevel
from app.models import Card
from app.schemas import CardCreate
from app.per_card_export import write_per_card_file


def upsert_card(card_data: CardCreate, image_path: str = None):
    # insert or update card record
    data = card_data.model_dump()
    with get_session() as sess:
        stmt = select(Card).where(
            Card.brand == data.get("brand"),
            Card.number == data.get("number"),
            Card.name == data.get("name"),
            Card.copyright_year == data.get("copyright_year"),
        )
        existing = sess.exec(stmt).first()
        if existing:
            existing.quantity += 1
            existing.last_updated = datetime.utcnow()
            for key, value in data.items():
                setattr(existing, key, value)
            sess.add(existing)
            sess.commit()
            sess.refresh(existing)
            try:
                rec = f"{existing.name} #{existing.number or ''} {existing.brand or ''} {existing.copyright_year or ''}".strip()
                logger.log_database_operation(
                    operation="update",
                    table="cards",
                    record_info=rec,
                    success=True
                )
                # Update per-unique-card JSON snapshot
                try:
                    write_per_card_file(existing)
                except Exception:
                    pass
            except Exception:
                pass
            return existing

        new_card = Card(**data)
        sess.add(new_card)
        sess.commit()
        sess.refresh(new_card)
        try:
            rec = f"{new_card.name} #{new_card.number or ''} {new_card.brand or ''} {new_card.copyright_year or ''}".strip()
            logger.log_database_operation(
                operation="insert",
                table="cards",
                record_info=rec,
                success=True
            )
            # Create per-unique-card JSON snapshot
            try:
                write_per_card_file(new_card)
            except Exception:
                pass
        except Exception:
            pass
        return new_card


def list_cards() -> List[Card]:
    """
    Retrieve all cards in the database.
    """
    with get_session() as sess:
        rows = sess.exec(select(Card)).all()
        try:
            logger.log(
                LogLevel.INFO,
                LogSource.DATABASE,
                "List cards",
                ActionType.DB_QUERY,
                details=f"returned={len(rows)}"
            )
        except Exception:
            pass
        return rows


def get_card_by_id(card_id: int) -> Optional[Card]:
    """
    Fetch a single Card by its primary key.
    """
    with get_session() as sess:
        row = sess.get(Card, card_id)
        try:
            logger.log(
                LogLevel.INFO,
                LogSource.DATABASE,
                f"Get card by id {card_id}",
                ActionType.DB_QUERY,
                details="found" if row else "not_found"
            )
        except Exception:
            pass
        return row
