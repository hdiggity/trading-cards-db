"""
Import card set checklists from CSV files

CSV Format:
brand,year,card_number,player_name,team,card_type,subset
topps,1984,1,tony gwynn,san diego padres,player,
topps,1984,2,steve garvey,san diego padres,player,
...
"""

import csv
from pathlib import Path
from typing import List
from card_set_database import CardSetDatabase, ChecklistEntry


def import_from_csv(csv_path: str) -> int:
    """
    Import checklist from CSV file

    Returns:
        Number of entries imported
    """

    db = CardSetDatabase()
    count = 0

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        for row in reader:
            entry = ChecklistEntry(
                brand=row['brand'].lower().strip(),
                year=row['year'].strip(),
                card_number=row['card_number'].strip(),
                player_name=row['player_name'].lower().strip(),
                team=row.get('team', '').lower().strip() or None,
                card_type=row.get('card_type', 'player').strip(),
                subset=row.get('subset', '').strip() or None
            )

            if db.add_checklist_entry(entry):
                count += 1

    db.close()
    return count


def export_to_csv(brand: str, year: str, csv_path: str):
    """Export a set checklist to CSV"""

    db = CardSetDatabase()
    entries = db.get_set_checklist(brand, year)

    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'brand', 'year', 'card_number', 'player_name', 'team', 'card_type', 'subset'
        ])
        writer.writeheader()

        for entry in entries:
            writer.writerow({
                'brand': entry.brand,
                'year': entry.year,
                'card_number': entry.card_number,
                'player_name': entry.player_name,
                'team': entry.team or '',
                'card_type': entry.card_type,
                'subset': entry.subset or ''
            })

    db.close()
    print(f"Exported {len(entries)} entries to {csv_path}")


def import_from_existing_cards():
    """
    Bootstrap checklist database from your existing verified cards
    This creates partial checklists based on cards you've already processed
    """

    import sqlite3
    from pathlib import Path

    # Connect to your main cards database
    cards_db_path = Path(__file__).parent.parent / "cards" / "verified" / "trading_cards.db"
    cards_conn = sqlite3.connect(str(cards_db_path))
    cursor = cards_conn.cursor()

    # Get all unique cards with brand, year, number, name
    cursor.execute("""
        SELECT DISTINCT brand, copyright_year, number, name, team
        FROM cards
        WHERE brand IS NOT NULL
          AND copyright_year IS NOT NULL
          AND number IS NOT NULL
          AND name IS NOT NULL
        ORDER BY copyright_year, brand, CAST(number AS INTEGER)
    """)

    results = cursor.fetchall()
    cards_conn.close()

    # Import into checklist database
    db = CardSetDatabase()
    count = 0

    for brand, year, number, name, team in results:
        entry = ChecklistEntry(
            brand=brand.lower().strip(),
            year=str(year).strip(),
            card_number=str(number).strip(),
            player_name=name.lower().strip(),
            team=team.lower().strip() if team else None,
            card_type="player"
        )

        if db.add_checklist_entry(entry):
            count += 1

    db.close()

    print(f"Imported {count} cards from existing verified cards database")
    print("This creates partial checklists for the sets you've already processed")

    return count


if __name__ == "__main__":
    print("Card Set Checklist Importer")
    print("=" * 60)
    print("\nOptions:")
    print("1. Import from existing verified cards (bootstrap)")
    print("2. Import from CSV file")
    print("3. Export set to CSV")
    print("4. Exit")

    choice = input("\nEnter choice (1-4): ")

    if choice == "1":
        count = import_from_existing_cards()
        print(f"\n✓ Successfully imported {count} entries")

    elif choice == "2":
        csv_path = input("Enter CSV file path: ")
        count = import_from_csv(csv_path)
        print(f"\n✓ Successfully imported {count} entries from {csv_path}")

    elif choice == "3":
        brand = input("Enter brand (e.g., topps): ")
        year = input("Enter year (e.g., 1984): ")
        csv_path = input("Enter output CSV path: ")
        export_to_csv(brand, year, csv_path)

    else:
        print("Exiting")
