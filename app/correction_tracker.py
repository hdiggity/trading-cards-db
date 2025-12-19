"""
Correction tracking and learning system for GPT extraction errors.

Tracks manual corrections made during verification and learns patterns
to automatically fix common extraction errors in future runs.
"""

import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import re


class CorrectionTracker:
    """Tracks and learns from manual corrections to improve extraction accuracy"""

    def __init__(self, db_path: str = "cards/verified/corrections.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize corrections database"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS corrections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_name TEXT,
                field_name TEXT NOT NULL,
                gpt_value TEXT,
                corrected_value TEXT,
                image_filename TEXT,
                brand TEXT,
                sport TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_field_name
            ON corrections(field_name)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_brand_sport
            ON corrections(brand, sport)
        """)

        conn.commit()
        conn.close()

    def log_correction(
        self,
        field_name: str,
        gpt_value: Optional[str],
        corrected_value: Optional[str],
        card_name: Optional[str] = None,
        image_filename: Optional[str] = None,
        brand: Optional[str] = None,
        sport: Optional[str] = None
    ):
        """Log a manual correction for learning"""
        # Skip if values are the same
        if gpt_value == corrected_value:
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO corrections (
                card_name, field_name, gpt_value, corrected_value,
                image_filename, brand, sport
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (card_name, field_name, gpt_value, corrected_value,
              image_filename, brand, sport))

        conn.commit()
        conn.close()

    def get_correction_patterns(
        self,
        field_name: str,
        min_occurrences: int = 2
    ) -> List[Tuple[str, str, int]]:
        """Get common correction patterns for a field

        Returns: List of (gpt_value, corrected_value, count) tuples
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT gpt_value, corrected_value, COUNT(*) as count
            FROM corrections
            WHERE field_name = ?
            AND gpt_value IS NOT NULL
            AND corrected_value IS NOT NULL
            GROUP BY gpt_value, corrected_value
            HAVING count >= ?
            ORDER BY count DESC
        """, (field_name, min_occurrences))

        patterns = cursor.fetchall()
        conn.close()

        return patterns

    def apply_learned_corrections(
        self,
        card_data: Dict,
        confidence_threshold: int = 2
    ) -> Dict:
        """Apply learned corrections to extracted card data

        Args:
            card_data: Dictionary of card fields from GPT
            confidence_threshold: Minimum correction occurrences to apply

        Returns:
            Card data with learned corrections applied
        """
        corrected_data = card_data.copy()
        corrections_applied = []

        # Fields to check for corrections
        correctable_fields = [
            'name', 'team', 'brand', 'sport', 'condition',
            'copyright_year', 'card_set'
        ]

        for field in correctable_fields:
            if field not in card_data:
                continue

            gpt_value = card_data[field]
            if not gpt_value:
                continue

            # Get learned patterns for this field
            patterns = self.get_correction_patterns(field, confidence_threshold)

            # Apply exact match corrections
            for pattern_gpt, pattern_corrected, count in patterns:
                if gpt_value.lower() == pattern_gpt.lower():
                    corrected_data[field] = pattern_corrected
                    corrections_applied.append({
                        'field': field,
                        'original': gpt_value,
                        'corrected': pattern_corrected,
                        'confidence': count
                    })
                    break

            # Apply team name corrections (city addition)
            if field == 'team':
                corrected_data[field] = self._apply_team_corrections(
                    gpt_value, patterns
                )
                if corrected_data[field] != gpt_value:
                    corrections_applied.append({
                        'field': 'team',
                        'original': gpt_value,
                        'corrected': corrected_data[field],
                        'confidence': 'pattern'
                    })

        # Add metadata about applied corrections
        if corrections_applied:
            corrected_data['_learned_corrections'] = corrections_applied

        return corrected_data

    def _apply_team_corrections(
        self,
        gpt_value: str,
        patterns: List[Tuple[str, str, int]]
    ) -> str:
        """Apply team name corrections (e.g., add missing city)"""
        if not gpt_value:
            return gpt_value

        # Check if city is missing (common GPT error)
        # Pattern: "cubs" should be "chicago cubs"
        for pattern_gpt, pattern_corrected, count in patterns:
            if not pattern_gpt or not pattern_corrected:
                continue

            # If GPT value matches the team name part
            if gpt_value.lower() == pattern_gpt.lower():
                return pattern_corrected

            # If GPT value is just the team nickname
            if pattern_corrected.lower().endswith(gpt_value.lower()):
                return pattern_corrected

        return gpt_value

    def get_field_accuracy_stats(self) -> Dict[str, Dict]:
        """Get accuracy statistics for each field"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                field_name,
                COUNT(*) as total_corrections,
                COUNT(DISTINCT gpt_value) as unique_errors,
                COUNT(DISTINCT corrected_value) as unique_corrections
            FROM corrections
            GROUP BY field_name
            ORDER BY total_corrections DESC
        """)

        stats = {}
        for row in cursor.fetchall():
            field_name, total, unique_errors, unique_corrections = row
            stats[field_name] = {
                'total_corrections': total,
                'unique_errors': unique_errors,
                'unique_corrections': unique_corrections
            }

        conn.close()
        return stats

    def get_most_common_errors(
        self,
        limit: int = 10
    ) -> List[Dict]:
        """Get the most frequently corrected errors"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                field_name,
                gpt_value,
                corrected_value,
                COUNT(*) as occurrences
            FROM corrections
            WHERE gpt_value IS NOT NULL
            AND corrected_value IS NOT NULL
            GROUP BY field_name, gpt_value, corrected_value
            ORDER BY occurrences DESC
            LIMIT ?
        """, (limit,))

        errors = []
        for row in cursor.fetchall():
            field, gpt_val, corrected_val, count = row
            errors.append({
                'field': field,
                'gpt_value': gpt_val,
                'corrected_value': corrected_val,
                'occurrences': count
            })

        conn.close()
        return errors
