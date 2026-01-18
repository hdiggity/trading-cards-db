"""Fix incorrectly normalized canonical names in database.

Issues to fix:
1. Non-player cards (team checklists, multiple players) should not have canonical names
2. Parentheses in names should be removed, keeping only text before parentheses
3. Names with commas (multiple players) should not be normalized
"""

import sqlite3
import sys

# Database paths
DB_PATH = "cards/verified/trading_cards.db"
CANONICAL_DB_PATH = "data/canonical_names.db"


def fix_non_player_cards(conn):
    """Fix cards that are not player cards (team checklists, multiple
    players)."""
    cursor = conn.cursor()

    # Cards with commas (multiple players) or team/checklist keywords
    cursor.execute("""
        UPDATE cards
        SET canonical_name = NULL, is_player = 0
        WHERE (name LIKE '%,%' OR name LIKE '%team%' OR name LIKE '%checklist%')
          AND (canonical_name IS NOT NULL OR is_player = 1)
    """)

    affected = cursor.rowcount
    print(f"Fixed {affected} non-player cards (set canonical_name=NULL, is_player=0)", file=sys.stderr)

    # Also update cards_complete
    cursor.execute("""
        UPDATE cards_complete
        SET canonical_name = NULL, is_player = 0
        WHERE (name LIKE '%,%' OR name LIKE '%team%' OR name LIKE '%checklist%')
          AND (canonical_name IS NOT NULL OR is_player = 1)
    """)

    affected_complete = cursor.rowcount
    print(f"Fixed {affected_complete} non-player cards in cards_complete", file=sys.stderr)


def fix_parentheses_names(conn):
    """Fix names with parentheses - should remove parentheses and normalize."""
    from app.player_canonical import CanonicalNameService

    cursor = conn.cursor()
    service = CanonicalNameService()

    # Find all player cards with parentheses
    cursor.execute("""
        SELECT id, name FROM cards
        WHERE name LIKE '%(%' AND is_player = 1
    """)

    cards_to_fix = cursor.fetchall()

    for card_id, name in cards_to_fix:
        # Remove parentheses and everything inside them
        clean_name = name.split('(')[0].strip()

        # Get proper canonical name
        canonical = service.get_canonical_name(clean_name, 'baseball')

        print(f"Fixing card {card_id}: '{name}' -> clean='{clean_name}' -> canonical='{canonical}'", file=sys.stderr)

        # Update cards table
        cursor.execute("""
            UPDATE cards
            SET canonical_name = ?
            WHERE id = ?
        """, (canonical, card_id))

        # Update cards_complete table
        cursor.execute("""
            UPDATE cards_complete
            SET canonical_name = ?
            WHERE card_id = ?
        """, (canonical, card_id))


def clean_canonical_cache():
    """Remove incorrect entries from canonical names cache."""
    conn = sqlite3.connect(CANONICAL_DB_PATH)
    cursor = conn.cursor()

    # Remove team checklists and multi-player entries
    cursor.execute("""
        DELETE FROM canonical_names
        WHERE input_name LIKE '%,%'
           OR input_name LIKE '%team%'
           OR input_name LIKE '%checklist%'
    """)

    affected = cursor.rowcount
    print(f"Removed {affected} non-player entries from canonical_names cache", file=sys.stderr)

    # Remove parentheses entries (they'll be re-cached with cleaned names)
    cursor.execute("""
        DELETE FROM canonical_names
        WHERE input_name LIKE '%(%'
    """)

    affected_parens = cursor.rowcount
    print(f"Removed {affected_parens} parentheses entries from canonical_names cache", file=sys.stderr)

    conn.commit()
    conn.close()


def main():
    """Run all fixes."""
    print("Starting canonical name fixes...", file=sys.stderr)

    # Backup database first
    import shutil
    from datetime import datetime
    backup_path = f"cards/verified/trading_cards_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    shutil.copy(DB_PATH, backup_path)
    print(f"Created backup: {backup_path}", file=sys.stderr)

    # Fix main database
    conn = sqlite3.connect(DB_PATH)

    print("\n1. Fixing non-player cards...", file=sys.stderr)
    fix_non_player_cards(conn)

    print("\n2. Fixing parentheses names...", file=sys.stderr)
    fix_parentheses_names(conn)

    conn.commit()
    conn.close()

    print("\n3. Cleaning canonical names cache...", file=sys.stderr)
    clean_canonical_cache()

    print("\nAll fixes complete!", file=sys.stderr)


if __name__ == "__main__":
    main()
