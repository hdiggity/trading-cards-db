"""
Migration script to lowercase all text fields in existing card data.
Run this once to fix cards that were added before lowercase enforcement.
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.database import get_session
from app.models import Card, CardComplete


def lowercase_existing_cards():
    """Lowercase all text fields in cards and cards_complete tables."""

    text_fields = ['name', 'sport', 'brand', 'team', 'card_set', 'features', 'condition', 'notes']

    with get_session() as session:
        # Update cards table
        cards = session.query(Card).all()
        print(f"Processing {len(cards)} cards in 'cards' table...")

        for card in cards:
            for field in text_fields:
                value = getattr(card, field, None)
                if value and isinstance(value, str):
                    lowered = value.lower()
                    if lowered != value:
                        setattr(card, field, lowered)
                        print(f"  Card {card.id}: {field} '{value}' -> '{lowered}'")

        session.commit()
        print(f"Updated cards table.\n")

        # Update cards_complete table
        cards_complete = session.query(CardComplete).all()
        print(f"Processing {len(cards_complete)} records in 'cards_complete' table...")

        for card in cards_complete:
            for field in text_fields:
                value = getattr(card, field, None)
                if value and isinstance(value, str):
                    lowered = value.lower()
                    if lowered != value:
                        setattr(card, field, lowered)
                        print(f"  CardComplete {card.id}: {field} '{value}' -> '{lowered}'")

        session.commit()
        print(f"Updated cards_complete table.\n")

        print("✓ Migration complete! All card text data is now lowercase.")


if __name__ == "__main__":
    try:
        lowercase_existing_cards()
    except Exception as e:
        print(f"✗ Migration failed: {e}")
        sys.exit(1)
