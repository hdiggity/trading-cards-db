"""
Card Set Checklist Database System

Stores and queries complete card set checklists for validation.
Data sources: TCDB (Trading Card Database), manual entry, scraped data
"""

import sqlite3
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass
import difflib


@dataclass
class ChecklistEntry:
    """Single card in a set checklist"""
    brand: str
    year: str
    card_number: str
    player_name: str
    team: str
    card_type: str = "player"  # player, team_checklist, league_leaders, etc.
    subset: Optional[str] = None  # traded, all-star, etc.


class CardSetDatabase:
    """Database for card set checklists"""

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = Path(__file__).parent.parent / "data" / "card_sets.db"

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.init_database()

    def init_database(self):
        """Create tables if they don't exist"""
        cursor = self.conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS card_sets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brand TEXT NOT NULL,
                year TEXT NOT NULL,
                set_name TEXT,
                total_cards INTEGER,
                notes TEXT,
                UNIQUE(brand, year, set_name)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS checklist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                set_id INTEGER NOT NULL,
                card_number TEXT NOT NULL,
                player_name TEXT NOT NULL,
                team TEXT,
                card_type TEXT DEFAULT 'player',
                subset TEXT,
                notes TEXT,
                FOREIGN KEY (set_id) REFERENCES card_sets(id),
                UNIQUE(set_id, card_number)
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_checklist_lookup
            ON checklist(card_number, player_name)
        """)

        self.conn.commit()

    def add_set(self, brand: str, year: str, set_name: str = None, total_cards: int = None) -> int:
        """Add a card set"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO card_sets (brand, year, set_name, total_cards)
            VALUES (?, ?, ?, ?)
        """, (brand.lower(), year, set_name or "base", total_cards))
        self.conn.commit()

        # Get the set ID
        cursor.execute("""
            SELECT id FROM card_sets
            WHERE brand = ? AND year = ? AND set_name = ?
        """, (brand.lower(), year, set_name or "base"))

        return cursor.fetchone()[0]

    def add_checklist_entry(self, entry: ChecklistEntry) -> bool:
        """Add a checklist entry"""
        # Get or create set
        set_id = self.add_set(entry.brand, entry.year, entry.subset)

        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO checklist (set_id, card_number, player_name, team, card_type, subset)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (set_id, entry.card_number, entry.player_name.lower(),
                  entry.team.lower() if entry.team else None,
                  entry.card_type, entry.subset))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            # Entry already exists
            return False

    def bulk_add_checklist(self, entries: List[ChecklistEntry]):
        """Add multiple checklist entries efficiently"""
        for entry in entries:
            self.add_checklist_entry(entry)

    def lookup_card(self, brand: str, year: str, card_number: str,
                    subset: str = None) -> Optional[ChecklistEntry]:
        """
        Look up expected card info by brand, year, and number

        Returns:
            ChecklistEntry if found, None otherwise
        """
        cursor = self.conn.cursor()

        query = """
            SELECT c.card_number, c.player_name, c.team, c.card_type, c.subset
            FROM checklist c
            JOIN card_sets s ON c.set_id = s.id
            WHERE s.brand = ? AND s.year = ? AND c.card_number = ?
        """
        params = [brand.lower(), year, card_number]

        if subset:
            query += " AND s.set_name = ?"
            params.append(subset)

        cursor.execute(query, params)
        result = cursor.fetchone()

        if result:
            return ChecklistEntry(
                brand=brand,
                year=year,
                card_number=result[0],
                player_name=result[1],
                team=result[2],
                card_type=result[3],
                subset=result[4]
            )

        return None

    def validate_extraction(self, extracted_data: Dict) -> Dict:
        """
        Validate extracted card data against checklist

        Args:
            extracted_data: Dict with brand, year, number, name, team

        Returns:
            Dict with validation results and suggestions
        """
        brand = extracted_data.get('brand', '').lower()
        year = extracted_data.get('copyright_year', '')
        number = extracted_data.get('number', '')
        extracted_name = extracted_data.get('name', '').lower()

        if not (brand and year and number):
            return {
                'valid': None,
                'message': 'Insufficient data for validation (need brand, year, number)'
            }

        # Look up expected card
        expected = self.lookup_card(brand, year, number)

        if not expected:
            return {
                'valid': None,
                'message': f'No checklist entry found for {brand} {year} #{number}',
                'in_database': False
            }

        # Compare names
        expected_name = expected.player_name.lower()
        similarity = difflib.SequenceMatcher(None, extracted_name, expected_name).ratio()

        # Check for exact match
        if extracted_name == expected_name:
            return {
                'valid': True,
                'message': 'Exact match with checklist',
                'expected': expected,
                'similarity': 1.0,
                'in_database': True
            }

        # Check for fuzzy match (OCR errors)
        elif similarity > 0.8:
            return {
                'valid': 'fuzzy',
                'message': f'Possible OCR error: extracted "{extracted_name}", expected "{expected_name}"',
                'expected': expected,
                'similarity': similarity,
                'suggestion': expected_name,
                'in_database': True
            }

        # Name mismatch
        else:
            return {
                'valid': False,
                'message': f'Name mismatch: extracted "{extracted_name}", expected "{expected_name}"',
                'expected': expected,
                'similarity': similarity,
                'suggestion': expected_name,
                'in_database': True
            }

    def get_set_checklist(self, brand: str, year: str, subset: str = None) -> List[ChecklistEntry]:
        """Get complete checklist for a set"""
        cursor = self.conn.cursor()

        query = """
            SELECT c.card_number, c.player_name, c.team, c.card_type, c.subset
            FROM checklist c
            JOIN card_sets s ON c.set_id = s.id
            WHERE s.brand = ? AND s.year = ?
        """
        params = [brand.lower(), year]

        if subset:
            query += " AND s.set_name = ?"
            params.append(subset)

        query += " ORDER BY CAST(c.card_number AS INTEGER)"

        cursor.execute(query, params)

        entries = []
        for row in cursor.fetchall():
            entries.append(ChecklistEntry(
                brand=brand,
                year=year,
                card_number=row[0],
                player_name=row[1],
                team=row[2],
                card_type=row[3],
                subset=row[4]
            ))

        return entries

    def get_available_sets(self) -> List[Tuple[str, str, str]]:
        """Get list of all sets in database"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT brand, year, set_name, total_cards
            FROM card_sets
            ORDER BY year DESC, brand
        """)
        return cursor.fetchall()

    def close(self):
        """Close database connection"""
        self.conn.close()


def seed_common_topps_sets():
    """Seed database with common Topps baseball sets (1970s-1980s)"""

    db = CardSetDatabase()

    # Example entries - these would be expanded with full checklists
    # 1984 Topps Baseball (partial for demonstration)
    topps_1984 = [
        ChecklistEntry("topps", "1984", "1", "tony gwynn", "san diego padres"),
        ChecklistEntry("topps", "1984", "3", "dan quisenberry", "kansas city royals"),
        ChecklistEntry("topps", "1984", "21", "joe altobelli", "baltimore orioles", card_type="manager"),
        ChecklistEntry("topps", "1984", "82", "doug bird", "boston red sox"),
        ChecklistEntry("topps", "1984", "89", "mike smithson", "texas rangers"),
        ChecklistEntry("topps", "1984", "115", "andre thornton", "cleveland indians"),
        ChecklistEntry("topps", "1984", "144", "jesse jefferson", "toronto blue jays"),
        ChecklistEntry("topps", "1984", "245", "rick sutcliffe", "cleveland indians"),
        ChecklistEntry("topps", "1984", "287", "warren cromartie", "montreal expos"),
        ChecklistEntry("topps", "1984", "316", "mark bradley", "new york mets"),
        ChecklistEntry("topps", "1984", "352", "dave stewart", "texas rangers"),
        ChecklistEntry("topps", "1984", "426", "baltimore orioles team checklist", "baltimore orioles", card_type="team_checklist"),
        ChecklistEntry("topps", "1984", "495", "rollie fingers", "milwaukee brewers"),
        ChecklistEntry("topps", "1984", "515", "gorman thomas", "cleveland indians"),
        ChecklistEntry("topps", "1984", "638", "george vukovich", "cleveland indians"),
        ChecklistEntry("topps", "1984", "641", "mike richardt", "houston astros"),
        ChecklistEntry("topps", "1984", "643", "mike brown", "california angels"),
        ChecklistEntry("topps", "1984", "667", "vance law", "chicago white sox"),
        ChecklistEntry("topps", "1984", "724", "eric rasmussen", "kansas city royals"),
        ChecklistEntry("topps", "1984", "764", "mike hargrove", "cleveland indians"),
        ChecklistEntry("topps", "1984", "779", "jim sundberg", "texas rangers"),
    ]

    db.bulk_add_checklist(topps_1984)

    print(f"Seeded {len(topps_1984)} cards from 1984 Topps Baseball")

    # Show what we have
    sets = db.get_available_sets()
    print(f"\nAvailable sets in database: {len(sets)}")
    for brand, year, set_name, total in sets:
        print(f"  - {brand} {year} {set_name} ({total or '?'} cards)")

    db.close()


if __name__ == "__main__":
    seed_common_topps_sets()
