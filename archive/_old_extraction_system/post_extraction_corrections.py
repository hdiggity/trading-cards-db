"""
Post-extraction correction system

Applies learned corrections AFTER GPT extraction, not in prompts.
This allows GPT to work naturally, then fixes common known mistakes.
"""

import sqlite3
from pathlib import Path
from typing import Dict, List
import sys


class PostExtractionCorrector:
    """Applies learned corrections to extracted data"""

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = Path(__file__).parent.parent / "data" / "corrections.db"

        self.db_path = Path(db_path)
        if not self.db_path.exists():
            self.corrections = []
            return

        self.conn = sqlite3.connect(str(self.db_path))
        self._load_high_confidence_corrections()

    def _load_high_confidence_corrections(self):
        """Load corrections that appear multiple times (high confidence)"""

        cursor = self.conn.execute("""
            SELECT field, original_value, corrected_value, COUNT(*) as count
            FROM corrections
            WHERE original_value IS NOT NULL
              AND corrected_value IS NOT NULL
            GROUP BY field, original_value, corrected_value
            HAVING count >= 2
            ORDER BY count DESC
        """)

        self.corrections = [
            {
                'field': row[0],
                'original': row[1].lower() if row[1] else '',
                'corrected': row[2],
                'count': row[3]
            }
            for row in cursor.fetchall()
        ]

        print(f"[Post-Correction] Loaded {len(self.corrections)} high-confidence corrections", file=sys.stderr)

    def apply_corrections(self, card_data: Dict) -> Dict:
        """
        Apply learned corrections to card data

        Args:
            card_data: Extracted card data

        Returns:
            Corrected card data with _auto_corrections field if any applied
        """

        if not hasattr(self, 'corrections'):
            return card_data

        applied = []

        for correction in self.corrections:
            field = correction['field']
            if field not in card_data:
                continue

            value = card_data.get(field)
            if not value:
                continue

            value_lower = str(value).lower()

            # Check if this matches a known mistake
            if value_lower == correction['original']:
                old_value = card_data[field]
                card_data[field] = correction['corrected']
                applied.append({
                    'field': field,
                    'from': old_value,
                    'to': correction['corrected'],
                    'confidence': correction['count']
                })

                print(f"[Auto-Correction] {field}: '{old_value}' → '{correction['corrected']}' (learned from {correction['count']} corrections)", file=sys.stderr)

        if applied:
            card_data['_auto_corrections'] = applied

        return card_data

    def apply_to_batch(self, cards: List[Dict]) -> List[Dict]:
        """Apply corrections to a batch of cards"""

        corrected = []
        for card in cards:
            corrected.append(self.apply_corrections(card))

        return corrected

    def close(self):
        """Close database connection"""
        if hasattr(self, 'conn'):
            self.conn.close()


def apply_learned_corrections(card_data: Dict) -> Dict:
    """
    Convenience function to apply learned corrections to a single card

    Args:
        card_data: Extracted card data

    Returns:
        Corrected card data
    """

    corrector = PostExtractionCorrector()
    corrected = corrector.apply_corrections(card_data)
    corrector.close()

    return corrected


def apply_learned_corrections_batch(cards: List[Dict]) -> List[Dict]:
    """
    Convenience function to apply learned corrections to multiple cards

    Args:
        cards: List of extracted card data

    Returns:
        List of corrected card data
    """

    corrector = PostExtractionCorrector()
    corrected = corrector.apply_to_batch(cards)
    corrector.close()

    return corrected


def analyze_corrections_database():
    """Analyze corrections database and print summary"""

    db_path = Path(__file__).parent.parent / "data" / "corrections.db"
    conn = sqlite3.connect(str(db_path))

    print("Corrections Database Analysis")
    print("=" * 60)

    # Total corrections
    cursor = conn.execute("SELECT COUNT(*) FROM corrections")
    total = cursor.fetchone()[0]
    print(f"\nTotal Corrections: {total}")

    # By field
    cursor = conn.execute("""
        SELECT field, COUNT(*) as count
        FROM corrections
        GROUP BY field
        ORDER BY count DESC
    """)
    print("\nCorrections by Field:")
    for field, count in cursor.fetchall():
        print(f"  {field}: {count}")

    # Most common name corrections (2+ occurrences)
    print("\n" + "=" * 60)
    print("High-Confidence Name Corrections (auto-applied)")
    print("=" * 60)

    cursor = conn.execute("""
        SELECT original_value, corrected_value, COUNT(*) as count
        FROM corrections
        WHERE field = 'name'
          AND original_value IS NOT NULL
          AND corrected_value IS NOT NULL
        GROUP BY original_value, corrected_value
        HAVING count >= 2
        ORDER BY count DESC
    """)

    for original, corrected, count in cursor.fetchall():
        print(f"  '{original}' → '{corrected}' ({count}x)")

    # Team normalizations
    print("\n" + "=" * 60)
    print("Team Normalizations (auto-applied)")
    print("=" * 60)

    cursor = conn.execute("""
        SELECT original_value, corrected_value, COUNT(*) as count
        FROM corrections
        WHERE field = 'team'
          AND original_value IS NOT NULL
          AND corrected_value IS NOT NULL
        GROUP BY original_value, corrected_value
        HAVING count >= 2
        ORDER BY count DESC
        LIMIT 10
    """)

    for original, corrected, count in cursor.fetchall():
        print(f"  '{original}' → '{corrected}' ({count}x)")

    conn.close()


if __name__ == "__main__":
    analyze_corrections_database()
