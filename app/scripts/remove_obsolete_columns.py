"""
Migration script to remove obsolete columns from cards table.

Removes:
- matched_front_file (no longer used)
- last_price (replaced by value_estimate)
- price_last_checked (redundant with last_updated)
"""
import sqlite3
from pathlib import Path

# Get database path
PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH = PROJECT_ROOT / "cards" / "verified" / "trading_cards.db"

def migrate():
    """Remove obsolete columns from cards table."""

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()

        # Get current cards table columns
        cursor.execute("PRAGMA table_info(cards);")
        current_columns = cursor.fetchall()

        print("Current cards table columns:")
        for col in current_columns:
            print(f"  {col[1]}: {col[2]}")

        # Drop existing triggers first
        print("\nDropping existing triggers...")
        cursor.execute("DROP TRIGGER IF EXISTS sync_to_cards_on_insert")
        cursor.execute("DROP TRIGGER IF EXISTS sync_to_cards_on_update")
        cursor.execute("DROP TRIGGER IF EXISTS sync_to_cards_on_delete")
        cursor.execute("DROP TRIGGER IF EXISTS sync_cards_on_insert")
        cursor.execute("DROP TRIGGER IF EXISTS sync_cards_on_update")
        cursor.execute("DROP TRIGGER IF EXISTS sync_cards_on_delete")

        # Drop cards_new if it exists from a previous failed attempt
        cursor.execute("DROP TABLE IF EXISTS cards_new")

        # Define columns to keep (exclude obsolete ones)
        columns_to_keep = [
            "id",
            "name",
            "sport",
            "brand",
            "number",
            "copyright_year",
            "team",
            "card_set",
            "condition",
            "is_player",
            "features",
            "value_estimate",
            "notes",
            "quantity",
            "date_added",
            "last_updated"
        ]

        # Create new table with only desired columns
        print("\nCreating new cards table without obsolete columns...")
        cursor.execute("""
            CREATE TABLE cards_new (
                id INTEGER PRIMARY KEY,
                name VARCHAR NOT NULL,
                sport VARCHAR DEFAULT 'baseball',
                brand VARCHAR,
                number VARCHAR,
                copyright_year VARCHAR,
                team VARCHAR,
                card_set VARCHAR,
                condition VARCHAR,
                is_player BOOLEAN DEFAULT 1,
                features VARCHAR,
                value_estimate VARCHAR,
                notes VARCHAR,
                quantity INTEGER DEFAULT 1,
                date_added DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_updated DATETIME
            )
        """)

        # Copy data from old table to new table
        print("Copying data to new table...")
        columns_str = ", ".join(columns_to_keep)
        cursor.execute(f"""
            INSERT INTO cards_new ({columns_str})
            SELECT {columns_str}
            FROM cards
        """)

        # Drop old table
        print("Dropping old table...")
        cursor.execute("DROP TABLE cards")

        # Rename new table to cards
        print("Renaming new table...")
        cursor.execute("ALTER TABLE cards_new RENAME TO cards")

        # Recreate triggers for auto-sync from cards_complete
        print("Recreating triggers...")

        # Trigger for INSERT
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS sync_to_cards_on_insert
            AFTER INSERT ON cards_complete
            BEGIN
                INSERT INTO cards (
                    id, name, sport, brand, number, copyright_year, team,
                    card_set, condition, is_player, features, value_estimate,
                    notes, quantity, date_added, last_updated
                )
                SELECT
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
                    NEW.verification_date,
                    NEW.last_updated
                WHERE NOT EXISTS (SELECT 1 FROM cards WHERE id = NEW.card_id);

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
                    last_updated = NEW.last_updated
                WHERE id = NEW.card_id;
            END
        """)

        # Trigger for UPDATE
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS sync_to_cards_on_update
            AFTER UPDATE ON cards_complete
            BEGIN
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
                    last_updated = NEW.last_updated
                WHERE id = NEW.card_id;
            END
        """)

        # Trigger for DELETE
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS sync_to_cards_on_delete
            AFTER DELETE ON cards_complete
            BEGIN
                UPDATE cards SET
                    quantity = (SELECT COUNT(*) FROM cards_complete WHERE card_id = OLD.card_id)
                WHERE id = OLD.card_id;

                DELETE FROM cards
                WHERE id = OLD.card_id
                AND (SELECT COUNT(*) FROM cards_complete WHERE card_id = OLD.card_id) = 0;
            END
        """)

        conn.commit()

        # Verify new schema
        print("\nNew cards table schema:")
        cursor.execute("PRAGMA table_info(cards);")
        for col in cursor.fetchall():
            print(f"  {col[1]}: {col[2]}")

        print("\nMigration completed successfully!")
        print("Removed columns: matched_front_file, last_price, price_last_checked")

if __name__ == "__main__":
    migrate()
