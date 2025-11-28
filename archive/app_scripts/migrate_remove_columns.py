"""
Migration script to remove redundant columns from cards_complete table.

Removes:
- matched_front_file (replaced by direct card data)
- last_price (redundant with value_estimate)
- price_last_checked (redundant with value_estimate)
- date_added (replaced by verification_date)
- source_position (merged into grid_position)
- condition_at_scan (merged into condition)
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.database import get_session
from sqlalchemy import text


def migrate():
    """Remove redundant columns from cards_complete table."""

    columns_to_remove = [
        'matched_front_file',
        'last_price',
        'price_last_checked',
        'date_added',
        'source_position',
        'condition_at_scan'
    ]

    with get_session() as session:
        print("Starting migration to remove redundant columns from cards_complete...")

        # SQLite doesn't support DROP COLUMN directly, so we need to:
        # 1. Create a new table with the desired schema
        # 2. Copy data from old table
        # 3. Drop old table
        # 4. Rename new table

        # Get current columns we want to keep
        result = session.execute(text("PRAGMA table_info(cards_complete)"))
        current_columns = [(row[1], row[2]) for row in result]

        # Filter to columns we want to keep
        keep_columns = [(name, type_) for name, type_ in current_columns
                       if name not in columns_to_remove]

        print(f"Keeping {len(keep_columns)} columns, removing {len(columns_to_remove)} columns")

        # Build CREATE TABLE statement for new table
        column_defs = []
        for name, type_ in keep_columns:
            if name == 'id':
                column_defs.append(f"{name} {type_} PRIMARY KEY")
            elif name == 'card_id':
                column_defs.append(f"{name} {type_} NOT NULL REFERENCES cards(id) ON DELETE CASCADE")
            elif name == 'name':
                column_defs.append(f"{name} {type_} NOT NULL")
            elif name == 'verification_date':
                column_defs.append(f"{name} {type_} DEFAULT CURRENT_TIMESTAMP")
            elif name == 'last_updated':
                column_defs.append(f"{name} {type_}")
            else:
                column_defs.append(f"{name} {type_}")

        create_table_sql = f"""
        CREATE TABLE cards_complete_new (
            {', '.join(column_defs)}
        )
        """

        print("Creating new table with cleaned schema...")
        session.execute(text(create_table_sql))

        # Copy data to new table
        keep_column_names = [name for name, _ in keep_columns]
        copy_sql = f"""
        INSERT INTO cards_complete_new ({', '.join(keep_column_names)})
        SELECT {', '.join(keep_column_names)}
        FROM cards_complete
        """

        print("Copying data to new table...")
        session.execute(text(copy_sql))

        # Drop old table
        print("Dropping old table...")
        session.execute(text("DROP TABLE cards_complete"))

        # Rename new table
        print("Renaming new table...")
        session.execute(text("ALTER TABLE cards_complete_new RENAME TO cards_complete"))

        # Create index on card_id for performance
        print("Creating index on card_id...")
        session.execute(text("CREATE INDEX IF NOT EXISTS ix_cards_complete_card_id ON cards_complete (card_id)"))

        # Create index on source_file for performance
        print("Creating index on source_file...")
        session.execute(text("CREATE INDEX IF NOT EXISTS ix_cards_complete_source_file ON cards_complete (source_file)"))

        session.commit()

        print("\nMigration completed successfully!")
        print(f"Removed columns: {', '.join(columns_to_remove)}")

        # Verify final schema
        result = session.execute(text("PRAGMA table_info(cards_complete)"))
        final_columns = [row[1] for row in result]
        print(f"\nFinal cards_complete columns ({len(final_columns)}):")
        for col in final_columns:
            print(f"  - {col}")


if __name__ == '__main__':
    try:
        migrate()
    except Exception as e:
        print(f"\nError during migration: {e}", file=sys.stderr)
        sys.exit(1)
