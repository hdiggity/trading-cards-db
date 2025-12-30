"""Correction tracking and learning system for GPT extraction errors.

Tracks manual corrections made during verification and learns patterns
to automatically fix common extraction errors in future runs.

Includes condition prediction based on card metadata and manual
corrections.
"""

import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class CorrectionTracker:
    """Tracks and learns from manual corrections to improve extraction
    accuracy."""

    def __init__(self, db_path: str = "data/corrections.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize corrections database."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Check if table exists and what schema it has
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='corrections'")
        table_exists = cursor.fetchone() is not None

        if not table_exists:
            # Create new table matching actual schema
            cursor.execute("""
                CREATE TABLE corrections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    field TEXT NOT NULL,
                    original_value TEXT,
                    corrected_value TEXT,
                    brand TEXT,
                    year TEXT,
                    sport TEXT,
                    card_set TEXT,
                    context TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE INDEX idx_corrections_field
                ON corrections(field)
            """)

            cursor.execute("""
                CREATE INDEX idx_brand_sport
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
        sport: Optional[str] = None,
        copyright_year: Optional[str] = None,
        card_set: Optional[str] = None
    ):
        """Log a manual correction for learning."""
        # Skip if values are the same
        if gpt_value == corrected_value:
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Build context string for additional info
        context_parts = []
        if card_name:
            context_parts.append(f"name:{card_name}")
        if image_filename:
            context_parts.append(f"file:{image_filename}")
        context = "|".join(context_parts) if context_parts else None

        # Use actual database schema column names
        cursor.execute("""
            INSERT INTO corrections (
                field, original_value, corrected_value,
                brand, year, sport, card_set, context
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (field_name, gpt_value, corrected_value,
              brand, copyright_year, sport, card_set, context))

        conn.commit()
        conn.close()

    def get_correction_patterns(
        self,
        field_name: str,
        min_occurrences: int = 2
    ) -> List[Tuple[str, str, int]]:
        """Get common correction patterns for a field.

        Returns: List of (gpt_value, corrected_value, count) tuples
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT original_value, corrected_value, COUNT(*) as count
            FROM corrections
            WHERE field = ?
            AND original_value IS NOT NULL
            AND corrected_value IS NOT NULL
            GROUP BY original_value, corrected_value
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
        """Apply learned corrections to extracted card data.

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
        """Get accuracy statistics for each field."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                field,
                COUNT(*) as total_corrections,
                COUNT(DISTINCT original_value) as unique_errors,
                COUNT(DISTINCT corrected_value) as unique_corrections
            FROM corrections
            GROUP BY field
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
        """Get the most frequently corrected errors."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                field,
                original_value,
                corrected_value,
                COUNT(*) as occurrences
            FROM corrections
            WHERE original_value IS NOT NULL
            AND corrected_value IS NOT NULL
            GROUP BY field, original_value, corrected_value
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

    def predict_condition(
        self,
        card_data: Dict,
        min_samples: int = 3
    ) -> Optional[str]:
        """Predict condition based on learned patterns from manual corrections.

        Uses card metadata (brand, copyright_year, sport) to predict condition
        based on what users have corrected similar cards to.

        Args:
            card_data: Dictionary with card fields
            min_samples: Minimum corrections needed to make prediction

        Returns:
            Predicted condition or None if insufficient data
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get condition corrections for similar cards
        # Match by brand, year, and sport when available
        filters = []
        params = []

        if card_data.get('brand'):
            filters.append("brand = ?")
            params.append(card_data['brand'])

        if card_data.get('copyright_year'):
            filters.append("year = ?")
            params.append(card_data['copyright_year'])

        if card_data.get('sport'):
            filters.append("sport = ?")
            params.append(card_data['sport'])

        where_clause = " AND ".join(filters) if filters else "1=1"

        # Use correct column names based on actual schema
        cursor.execute(f"""
            SELECT corrected_value, COUNT(*) as count
            FROM corrections
            WHERE field = 'condition'
            AND corrected_value IS NOT NULL
            AND corrected_value != ''
            AND {where_clause}
            GROUP BY corrected_value
            ORDER BY count DESC
        """, params)

        results = cursor.fetchall()
        conn.close()

        if not results:
            return None

        # Check if we have enough samples
        total_samples = sum(count for _, count in results)
        if total_samples < min_samples:
            return None

        # Return most common condition
        return results[0][0]

    def get_confidence_score(
        self,
        card_data: Dict,
        gpt_data: Dict
    ) -> float:
        """Calculate calibrated confidence score based on historical accuracy.

        Enhanced confidence calculation with field weighting and validation penalties.

        Args:
            card_data: Card data with corrections applied (may have validation flags)
            gpt_data: Original GPT extraction

        Returns:
            Confidence score 0.0-1.0
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Field weights (some fields are more error-prone)
        field_weights = {
            'name': 1.5,       # Most important
            'team': 1.2,
            'brand': 1.0,
            'number': 1.0,
            'condition': 0.8,  # GPT frequently overestimates
            'card_set': 0.8,   # GPT frequently includes redundant info
        }

        weighted_correct = 0
        total_weight = 0

        for field, weight in field_weights.items():
            gpt_value = gpt_data.get(field)
            if not gpt_value:
                continue

            # Check how often GPT gets this field wrong
            cursor.execute("""
                SELECT COUNT(*) as error_count
                FROM corrections
                WHERE field = ?
                AND original_value = ?
                AND corrected_value != ?
            """, (field, gpt_value, gpt_value))

            error_count = cursor.fetchone()[0]

            # Check total times we've seen this GPT value
            cursor.execute("""
                SELECT COUNT(*) as total_count
                FROM corrections
                WHERE field = ?
                AND original_value = ?
            """, (field, gpt_value))

            total_count = cursor.fetchone()[0]

            # Calculate field-specific accuracy
            if total_count > 0:
                accuracy = 1.0 - (error_count / total_count)
            else:
                # No history: default accuracy varies by field
                if field in ('condition', 'card_set'):
                    accuracy = 0.7  # Lower default for error-prone fields
                else:
                    accuracy = 0.8  # Standard default

            weighted_correct += accuracy * weight
            total_weight += weight

        conn.close()

        if total_weight == 0:
            base_confidence = 0.8
        else:
            base_confidence = weighted_correct / total_weight

        # Apply penalties from validation rule flags
        confidence = base_confidence

        # Vintage condition penalty (from validation rules)
        if card_data.get('_condition_suspicious'):
            confidence -= 0.15
            confidence = max(0.0, confidence)

        # Suspicious year penalty
        if card_data.get('_year_suspicious'):
            confidence -= 0.10
            confidence = max(0.0, confidence)

        # Boost for autocorrected fields (high confidence fixes)
        if card_data.get('_card_set_autocorrected'):
            confidence = min(1.0, confidence + 0.05)

        if card_data.get('_team_autocompleted'):
            confidence = min(1.0, confidence + 0.05)

        return round(confidence, 2)
