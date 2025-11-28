"""
Create database triggers to automatically sync cards_complete to cards table.

This script creates SQLite triggers that maintain the cards table as an aggregated
view of cards_complete, with quantity tracking for duplicates.
"""

import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "cards" / "verified" / "trading_cards.db"

def create_triggers():
    """Create triggers to auto-sync cards_complete changes to cards table"""

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Drop existing triggers if they exist
    cursor.execute("DROP TRIGGER IF EXISTS sync_cards_on_insert")
    cursor.execute("DROP TRIGGER IF EXISTS sync_cards_on_update")
    cursor.execute("DROP TRIGGER IF EXISTS sync_cards_on_delete")

    # Trigger 1: After INSERT on cards_complete
    cursor.execute("""
        CREATE TRIGGER sync_cards_on_insert
        AFTER INSERT ON cards_complete
        BEGIN
            -- Update existing card or insert new one
            INSERT INTO cards (
                id, name, sport, brand, number, copyright_year, team, card_set,
                condition, is_player, features, value_estimate, notes, quantity, last_updated
            )
            VALUES (
                NEW.card_id,
                NEW.name,
                NEW.sport,
                NEW.brand,
                NEW.number,
                NEW.copyright_year,
                NEW.team,
                NEW.card_set,
                NEW.condition,
                NEW.is_player,
                NEW.features,
                NEW.value_estimate,
                NEW.notes,
                (SELECT COUNT(*) FROM cards_complete WHERE card_id = NEW.card_id),
                CURRENT_TIMESTAMP
            )
            ON CONFLICT(id) DO UPDATE SET
                name = NEW.name,
                sport = NEW.sport,
                brand = NEW.brand,
                number = NEW.number,
                copyright_year = NEW.copyright_year,
                team = NEW.team,
                card_set = NEW.card_set,
                condition = NEW.condition,
                is_player = NEW.is_player,
                features = NEW.features,
                value_estimate = NEW.value_estimate,
                notes = NEW.notes,
                quantity = (SELECT COUNT(*) FROM cards_complete WHERE card_id = NEW.card_id),
                last_updated = CURRENT_TIMESTAMP;
        END
    """)

    # Trigger 2: After UPDATE on cards_complete
    cursor.execute("""
        CREATE TRIGGER sync_cards_on_update
        AFTER UPDATE ON cards_complete
        BEGIN
            -- Update the corresponding card record
            UPDATE cards SET
                name = NEW.name,
                sport = NEW.sport,
                brand = NEW.brand,
                number = NEW.number,
                copyright_year = NEW.copyright_year,
                team = NEW.team,
                card_set = NEW.card_set,
                condition = NEW.condition,
                is_player = NEW.is_player,
                features = NEW.features,
                value_estimate = NEW.value_estimate,
                notes = NEW.notes,
                quantity = (SELECT COUNT(*) FROM cards_complete WHERE card_id = NEW.card_id),
                last_updated = CURRENT_TIMESTAMP
            WHERE id = NEW.card_id;
        END
    """)

    # Trigger 3: After DELETE on cards_complete
    cursor.execute("""
        CREATE TRIGGER sync_cards_on_delete
        AFTER DELETE ON cards_complete
        BEGIN
            -- If this was the last cards_complete record for a card, delete the card
            -- Otherwise update the quantity
            DELETE FROM cards WHERE id = OLD.card_id AND NOT EXISTS (
                SELECT 1 FROM cards_complete WHERE card_id = OLD.card_id
            );

            -- Update quantity if card still exists
            UPDATE cards SET
                quantity = (SELECT COUNT(*) FROM cards_complete WHERE card_id = OLD.card_id),
                last_updated = CURRENT_TIMESTAMP
            WHERE id = OLD.card_id AND EXISTS (
                SELECT 1 FROM cards_complete WHERE card_id = OLD.card_id
            );
        END
    """)

    conn.commit()
    conn.close()

    print(f"Database triggers created successfully in {DB_PATH}")
    print("The following triggers were created:")
    print("  - sync_cards_on_insert: Syncs new cards_complete records to cards table")
    print("  - sync_cards_on_update: Updates cards table when cards_complete is modified")
    print("  - sync_cards_on_delete: Removes or updates cards when cards_complete records are deleted")

if __name__ == "__main__":
    create_triggers()
