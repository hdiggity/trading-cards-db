from datetime import datetime
from typing import List, Optional

from sqlmodel import select

from app.database import get_session
from app.models import Card
from app.schemas import CardCreate


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
            return existing

        new_card = Card(**data)
        sess.add(new_card)
        sess.commit()
        sess.refresh(new_card)
        return new_card


def list_cards() -> List[Card]:
    """
    Retrieve all cards in the database.
    """
    with get_session() as sess:
        return sess.exec(select(Card)).all()


def get_card_by_id(card_id: int) -> Optional[Card]:
    """
    Fetch a single Card by its primary key.
    """
    with get_session() as sess:
        return sess.get(Card, card_id)
