"""Correction tracking and learning system for GPT extraction errors.

Tracks manual corrections made during verification and learns patterns
to automatically fix common extraction errors in future runs.

Includes condition prediction based on card metadata and manual
corrections.

Learning system for field corrections and automatic quality improvement.
Enhanced with ML tracking for unsupervised correction learning.

Visual context learning: For fields like copyright_year, corrections are
only applied when visual context (brand + card_set pattern) matches,
preventing false corrections across different card designs.
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class CorrectionTracker:
    """Tracks and learns from manual corrections to improve extraction
    accuracy."""

    def __init__(self, db_path: str = "data/corrections.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize corrections database with schema migrations."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Check if table exists and what schema it has
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='corrections'")
        table_exists = cursor.fetchone() is not None

        if not table_exists:
            # Create new table with full schema including ML columns
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
                    ml_prediction TEXT,
                    ml_confidence REAL,
                    correction_source TEXT DEFAULT 'user',
                    design_signature TEXT,
                    correction_reason TEXT,
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

            cursor.execute("""
                CREATE INDEX idx_corrections_created_at
                ON corrections(created_at)
            """)
        else:
            # Run migrations for existing databases
            self._run_migrations(cursor)

        # Create ML training metadata table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ml_training_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                last_train_time TIMESTAMP,
                corrections_count_at_train INTEGER,
                model_version TEXT,
                accuracy_stats TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()
        conn.close()

    def _run_migrations(self, cursor):
        """Run schema migrations for existing databases."""
        # Get existing columns
        cursor.execute("PRAGMA table_info(corrections)")
        existing_columns = {row[1] for row in cursor.fetchall()}

        # Add ML tracking columns if missing
        new_columns = [
            ("ml_prediction", "TEXT"),
            ("ml_confidence", "REAL"),
            ("correction_source", "TEXT DEFAULT 'user'"),
            ("design_signature", "TEXT"),  # brand|card_set pattern for visual context
            ("correction_reason", "TEXT"),  # optional user-provided reason
        ]

        for col_name, col_type in new_columns:
            if col_name not in existing_columns:
                try:
                    cursor.execute(f"ALTER TABLE corrections ADD COLUMN {col_name} {col_type}")
                except sqlite3.OperationalError:
                    pass  # Column already exists

        # Add index on created_at if not exists
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='index' AND name='idx_corrections_created_at'
        """)
        if cursor.fetchone() is None:
            try:
                cursor.execute("""
                    CREATE INDEX idx_corrections_created_at
                    ON corrections(created_at)
                """)
            except sqlite3.OperationalError:
                pass

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
        card_set: Optional[str] = None,
        ml_prediction: Optional[str] = None,
        ml_confidence: Optional[float] = None,
        correction_source: str = 'user',
        correction_reason: Optional[str] = None
    ):
        """Log a manual correction for learning.

        Args:
            field_name: Name of the field being corrected
            gpt_value: Original value from GPT extraction
            corrected_value: User's corrected value
            card_name: Name of the card (for context)
            image_filename: Source image filename
            brand: Card brand
            sport: Card sport
            copyright_year: Card copyright year
            card_set: Card set name
            ml_prediction: ML predicted value if ML override was applied
            ml_confidence: ML confidence score if ML override was applied
            correction_source: 'user' or 'ml_override' indicating if user
                               corrected an ML prediction
            correction_reason: Optional user-provided reason for the correction
        """
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

        # Build design signature for visual context matching
        # This helps prevent false corrections across different card designs
        design_parts = []
        if brand:
            design_parts.append(brand.lower().strip())
        if card_set and card_set.lower() not in ('n/a', 'base', 'base set', ''):
            design_parts.append(card_set.lower().strip())
        design_signature = "|".join(design_parts) if design_parts else None

        # Use actual database schema column names including ML columns
        cursor.execute("""
            INSERT INTO corrections (
                field, original_value, corrected_value,
                brand, year, sport, card_set, context,
                ml_prediction, ml_confidence, correction_source,
                design_signature, correction_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (field_name, gpt_value, corrected_value,
              brand, copyright_year, sport, card_set, context,
              ml_prediction, ml_confidence, correction_source,
              design_signature, correction_reason))

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
        confidence_threshold: int = 4
    ) -> Dict:
        """Apply learned corrections to extracted card data.

        Args:
            card_data: Dictionary of card fields from GPT
            confidence_threshold: Minimum correction occurrences to apply (default 4 to trust GPT more)

        Returns:
            Card data with learned corrections applied
        """
        corrected_data = card_data.copy()
        corrections_applied = []

        # Fields to check for corrections (name excluded - use canonical_names system instead)
        # copyright_year excluded - year printed on card should always be trusted
        correctable_fields = [
            'team', 'brand', 'sport', 'condition',
            'card_set'
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
            # For team field, only apply SAFE corrections (city additions, not player-specific)
            for pattern_gpt, pattern_corrected, count in patterns:
                if gpt_value.lower() == pattern_gpt.lower():
                    # For team field, skip player-specific corrections
                    if field == 'team':
                        # Only apply if it's a city addition (corrected ends with original)
                        is_city_addition = pattern_corrected.lower().strip().endswith(
                            pattern_gpt.lower().strip()
                        )
                        if not is_city_addition:
                            # Skip this player-specific team correction
                            continue

                    corrected_data[field] = pattern_corrected
                    corrections_applied.append({
                        'field': field,
                        'original': gpt_value,
                        'corrected': pattern_corrected,
                        'confidence': count
                    })
                    break

            # Apply team name corrections (city addition) - handles nickname to full name
            if field == 'team':
                new_team = self._apply_team_corrections(gpt_value, patterns)
                if new_team != gpt_value and new_team != corrected_data.get(field, gpt_value):
                    corrected_data[field] = new_team
                    corrections_applied.append({
                        'field': 'team',
                        'original': gpt_value,
                        'corrected': new_team,
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
        """Apply team name corrections (e.g., add missing city).

        Only applies SAFE corrections:
        - City prefix additions (e.g., "cubs" -> "chicago cubs")
        - NOT player-specific team changes (e.g., "milwaukee brewers" -> "chicago white sox")

        Player-specific team corrections are not generalizable and should not be applied
        to other players.
        """
        if not gpt_value:
            return gpt_value

        gpt_lower = gpt_value.lower().strip()

        # Check if city is missing (common GPT error)
        # Pattern: "cubs" should be "chicago cubs"
        for pattern_gpt, pattern_corrected, count in patterns:
            if not pattern_gpt or not pattern_corrected:
                continue

            pattern_gpt_lower = pattern_gpt.lower().strip()
            pattern_corrected_lower = pattern_corrected.lower().strip()

            # Only apply if this is a SAFE correction (city prefix addition)
            # Safe: corrected value ends with original value (e.g., "cubs" -> "chicago cubs")
            # Unsafe: completely different team (e.g., "milwaukee brewers" -> "chicago white sox")
            is_city_addition = pattern_corrected_lower.endswith(pattern_gpt_lower)

            if not is_city_addition:
                # Skip player-specific team changes - these are not generalizable
                continue

            # If GPT value matches the team name part exactly
            if gpt_lower == pattern_gpt_lower:
                return pattern_corrected

            # If GPT value is just the team nickname and we have a city addition for it
            if pattern_corrected_lower.endswith(gpt_lower):
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

        # ML confidence boost/penalty (Phase 6 enhancement)
        ml_boost = 0.0
        ml_trackable_fields = [
            'name', 'brand', 'team', 'card_set', 'copyright_year',
            'number', 'condition', 'sport', 'features', 'notes'
        ]

        for field in ml_trackable_fields:
            if card_data.get(f'_ml_{field}_applied'):
                ml_confidence = card_data.get(f'_ml_{field}_confidence', 0)
                if ml_confidence >= 0.92:
                    ml_boost += 0.03  # High-confidence ML override

        # Cap ML boost at 0.10
        ml_boost = min(ml_boost, 0.10)
        confidence += ml_boost

        return round(max(0.0, min(1.0, confidence)), 2)

    def get_training_data(
        self,
        field: str,
        min_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Export corrections for ML training.

        Args:
            field: Field name to get training data for
            min_date: Only include corrections after this date

        Returns:
            List of dicts with original_value, corrected_value, and context
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        if min_date:
            cursor.execute("""
                SELECT original_value, corrected_value, brand, year, sport,
                       card_set, context, correction_source
                FROM corrections
                WHERE field = ?
                AND original_value IS NOT NULL
                AND corrected_value IS NOT NULL
                AND created_at >= ?
                ORDER BY created_at DESC
            """, (field, min_date.isoformat()))
        else:
            cursor.execute("""
                SELECT original_value, corrected_value, brand, year, sport,
                       card_set, context, correction_source
                FROM corrections
                WHERE field = ?
                AND original_value IS NOT NULL
                AND corrected_value IS NOT NULL
                ORDER BY created_at DESC
            """, (field,))

        rows = cursor.fetchall()
        conn.close()

        training_data = []
        for row in rows:
            training_data.append({
                'original_value': row[0],
                'corrected_value': row[1],
                'brand': row[2],
                'year': row[3],
                'sport': row[4],
                'card_set': row[5],
                'context': row[6],
                'correction_source': row[7] or 'user'
            })

        return training_data

    def log_ml_prediction(
        self,
        field: str,
        gpt_value: str,
        ml_prediction: str,
        confidence: float
    ):
        """Track ML prediction for accuracy monitoring (not a correction).

        This logs predictions that were applied but not yet verified.
        Used for calculating ML accuracy stats.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Store in a separate predictions table for tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ml_predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                field TEXT NOT NULL,
                gpt_value TEXT,
                ml_prediction TEXT,
                confidence REAL,
                was_correct INTEGER DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            INSERT INTO ml_predictions (field, gpt_value, ml_prediction, confidence)
            VALUES (?, ?, ?, ?)
        """, (field, gpt_value, ml_prediction, confidence))

        conn.commit()
        conn.close()

    def get_ml_accuracy_stats(
        self,
        field: str,
        window_days: int = 7
    ) -> Dict[str, Any]:
        """Get rolling accuracy metrics for ML predictions on a field.

        Args:
            field: Field name to get stats for
            window_days: Number of days to look back

        Returns:
            Dict with total_predictions, correct_count, accuracy, etc.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cutoff = (datetime.now() - timedelta(days=window_days)).isoformat()

        # Count ML overrides that were later corrected by users
        cursor.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN correction_source = 'ml_override' THEN 1 ELSE 0 END) as ml_overrides
            FROM corrections
            WHERE field = ?
            AND created_at >= ?
        """, (field, cutoff))

        row = cursor.fetchone()
        total_corrections = row[0] or 0
        ml_overrides_corrected = row[1] or 0

        # Get total ML predictions made (from ml_predictions table if exists)
        try:
            cursor.execute("""
                SELECT COUNT(*) FROM ml_predictions
                WHERE field = ?
                AND created_at >= ?
            """, (field, cutoff))
            total_ml_predictions = cursor.fetchone()[0] or 0
        except sqlite3.OperationalError:
            total_ml_predictions = 0

        conn.close()

        # Calculate accuracy (predictions that weren't corrected)
        if total_ml_predictions > 0:
            accuracy = 1.0 - (ml_overrides_corrected / total_ml_predictions)
        else:
            accuracy = None  # Not enough data

        return {
            'field': field,
            'window_days': window_days,
            'total_corrections': total_corrections,
            'ml_overrides_corrected': ml_overrides_corrected,
            'total_ml_predictions': total_ml_predictions,
            'accuracy': accuracy
        }

    def should_retrain(self) -> Tuple[bool, str]:
        """Check if ML models should be retrained based on criteria.

        Criteria:
        1. Volume: 50+ new corrections since last train
        2. Time: 24+ hours since last train with any new corrections
        3. Accuracy: Rolling 20-correction accuracy drops below 70%

        Returns:
            Tuple of (should_retrain, reason)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get last training metadata
        cursor.execute("""
            SELECT last_train_time, corrections_count_at_train
            FROM ml_training_metadata
            ORDER BY created_at DESC
            LIMIT 1
        """)
        row = cursor.fetchone()

        if row is None:
            # Never trained before
            cursor.execute("SELECT COUNT(*) FROM corrections")
            total = cursor.fetchone()[0]
            conn.close()
            if total >= 10:  # Minimum to start training
                return (True, "initial_training")
            return (False, "insufficient_data")

        last_train_time = datetime.fromisoformat(row[0]) if row[0] else None
        corrections_at_train = row[1] or 0

        # Get current correction count
        cursor.execute("SELECT COUNT(*) FROM corrections")
        current_count = cursor.fetchone()[0]
        new_corrections = current_count - corrections_at_train

        conn.close()

        # Criterion 1: Volume threshold
        if new_corrections >= 50:
            return (True, f"volume_threshold:{new_corrections}")

        # Criterion 2: Time threshold with any new data
        if last_train_time:
            hours_since_train = (datetime.now() - last_train_time).total_seconds() / 3600
            if hours_since_train >= 24 and new_corrections > 0:
                return (True, f"time_threshold:{hours_since_train:.1f}h")

        # Criterion 3: Accuracy drop (check key fields)
        key_fields = ['condition', 'team', 'brand', 'name']
        for field in key_fields:
            stats = self.get_ml_accuracy_stats(field, window_days=7)
            if stats['accuracy'] is not None and stats['accuracy'] < 0.70:
                if stats['total_ml_predictions'] >= 20:  # Need enough samples
                    return (True, f"accuracy_drop:{field}:{stats['accuracy']:.2f}")

        return (False, "no_criteria_met")

    def record_training_metadata(
        self,
        model_version: str,
        accuracy_stats: Dict[str, Any]
    ):
        """Record metadata about a training run."""
        import json

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM corrections")
        current_count = cursor.fetchone()[0]

        cursor.execute("""
            INSERT INTO ml_training_metadata
            (last_train_time, corrections_count_at_train, model_version, accuracy_stats)
            VALUES (?, ?, ?, ?)
        """, (
            datetime.now().isoformat(),
            current_count,
            model_version,
            json.dumps(accuracy_stats)
        ))

        conn.commit()
        conn.close()

    def get_total_corrections_count(self) -> int:
        """Get total number of corrections in database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM corrections")
        count = cursor.fetchone()[0]
        conn.close()
        return count

    def get_design_aware_year_correction(
        self,
        gpt_year: str,
        brand: Optional[str] = None,
        card_set: Optional[str] = None,
        min_occurrences: int = 3
    ) -> Optional[Tuple[str, int, str]]:
        """Get year correction only if design signature matches.

        This prevents false corrections like:
        - Batch A: 1982 Topps cards that look like 1983 -> correct to 1983
        - Batch B: Actual 1982 Topps cards -> DON'T apply correction

        The key insight is that year corrections should only apply when
        the card DESIGN (brand + set pattern) matches, not just the year.

        Args:
            gpt_year: Year extracted by GPT
            brand: Card brand
            card_set: Card set name
            min_occurrences: Minimum corrections to trust pattern

        Returns:
            Tuple of (corrected_year, occurrence_count, design_signature) or None
        """
        if not gpt_year:
            return None

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Build current card's design signature
        design_parts = []
        if brand:
            design_parts.append(brand.lower().strip())
        if card_set and card_set.lower() not in ('n/a', 'base', 'base set', ''):
            design_parts.append(card_set.lower().strip())
        current_signature = "|".join(design_parts) if design_parts else None

        # Look for year corrections with matching design signature
        if current_signature:
            cursor.execute("""
                SELECT corrected_value, COUNT(*) as cnt, design_signature
                FROM corrections
                WHERE field = 'copyright_year'
                AND original_value = ?
                AND design_signature = ?
                GROUP BY corrected_value, design_signature
                HAVING cnt >= ?
                ORDER BY cnt DESC
                LIMIT 1
            """, (gpt_year, current_signature, min_occurrences))
        else:
            # No design signature available, require higher threshold
            cursor.execute("""
                SELECT corrected_value, COUNT(*) as cnt, design_signature
                FROM corrections
                WHERE field = 'copyright_year'
                AND original_value = ?
                AND design_signature IS NULL
                GROUP BY corrected_value
                HAVING cnt >= ?
                ORDER BY cnt DESC
                LIMIT 1
            """, (gpt_year, min_occurrences * 2))

        result = cursor.fetchone()
        conn.close()

        if result:
            return (result[0], result[1], result[2])
        return None

    def get_design_signatures_for_year(
        self,
        year: str
    ) -> List[Dict]:
        """Get all design signatures associated with year corrections.

        Useful for understanding which card designs have been corrected
        from a particular year.

        Args:
            year: The original GPT-extracted year

        Returns:
            List of dicts with design_signature, corrected_year, count
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                design_signature,
                corrected_value,
                COUNT(*) as cnt,
                GROUP_CONCAT(DISTINCT correction_reason) as reasons
            FROM corrections
            WHERE field = 'copyright_year'
            AND original_value = ?
            AND design_signature IS NOT NULL
            GROUP BY design_signature, corrected_value
            ORDER BY cnt DESC
        """, (year,))

        results = []
        for row in cursor.fetchall():
            results.append({
                'design_signature': row[0],
                'corrected_year': row[1],
                'count': row[2],
                'reasons': row[3]
            })

        conn.close()
        return results
