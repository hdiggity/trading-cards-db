"""Canonical name service for resolving player name variations.

Handles lookups via MLB Stats API with local normalization fallback to support:
- Nickname variations (Mike -> Michael) [API]
- Middle name differences (Michael Trout -> Michael Nelson Trout) [API]
- Suffix variations (Ken Griffey -> Ken Griffey Jr.) [Normalization]
- Historical players not in MLB Stats API [Normalization]
"""

import re
import sqlite3
import sys
import time
import unicodedata
from pathlib import Path
from typing import Dict, Optional

import statsapi  # MLB-StatsAPI package


class CanonicalNameService:
    """Service for resolving player names to canonical forms using MLB Stats
    API."""

    def __init__(self, cache_db_path: str = "data/canonical_names.db"):
        self.cache_db_path = cache_db_path
        self._init_cache_db()
        self.rate_limit_delay = 0.1  # 100ms between API calls
        self.last_api_call = 0

    @staticmethod
    def normalize_name_for_matching(name):
        """Normalize a name for matching (handles middle names, accents,
        parentheses).

        IMPORTANT:
        - Keeps Jr/Sr/III/IV suffixes as they indicate different players.
        - Removes parentheses and everything inside them (e.g., "rogelio moret (torres)" -> "rogelio moret")
        This is the fallback for when MLB Stats API doesn't have the player (vintage cards).
        """
        if not name or not isinstance(name, str):
            return ""

        # Remove parentheses and everything inside them
        # e.g., "rogelio moret (torres)" -> "rogelio moret"
        if '(' in name:
            name = name.split('(')[0].strip()

        # Remove accents and normalize to ASCII
        name = unicodedata.normalize('NFD', name)
        name = ''.join(char for char in name if unicodedata.category(char) != 'Mn')

        name = name.lower().strip()

        # Split into parts
        parts = name.split()
        if len(parts) <= 2:
            return ' '.join(parts)

        # Check if last part is a suffix (jr, sr, iii, iv)
        suffix_pattern = r'^(jr\.?|sr\.?|iii?|iv)$'
        has_suffix = bool(re.match(suffix_pattern, parts[-1], flags=re.IGNORECASE))

        if has_suffix:
            # Keep first + last + suffix (remove middle names)
            # e.g., "ken griffey wilson jr" -> "ken griffey jr"
            if len(parts) > 3:
                return f"{parts[0]} {parts[-2]} {parts[-1]}"
            else:
                return ' '.join(parts)
        else:
            # No suffix - keep first + last (remove middle names)
            # e.g., "michael nelson trout" -> "michael trout"
            return f"{parts[0]} {parts[-1]}"

    def _init_cache_db(self):
        """Initialize canonical names cache database."""
        Path(self.cache_db_path).parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self.cache_db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS canonical_names (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                input_name TEXT NOT NULL,
                canonical_name TEXT,
                mlb_player_id INTEGER,
                confidence_score REAL,
                sport TEXT DEFAULT 'baseball',
                lookup_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                api_response_json TEXT,
                UNIQUE(input_name, sport)
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_input_name
            ON canonical_names(input_name)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_canonical_name
            ON canonical_names(canonical_name)
        """)

        conn.commit()
        conn.close()

    def get_canonical_name(
        self, player_name: str, sport: str = "baseball", force_refresh: bool = False
    ) -> Optional[str]:
        """Get canonical name for a player, using cache or API lookup.

        Args:
            player_name: Player name as extracted from card
            sport: Sport type (default: baseball)
            force_refresh: Bypass cache and force API lookup

        Returns:
            Canonical name or None if lookup fails or not a player card
        """
        if not player_name or not isinstance(player_name, str):
            return None

        # Normalize input
        normalized_input = player_name.lower().strip()

        # CRITICAL: Don't normalize non-player cards
        # Team checklists, multiple players, etc. should return None
        if (',' in normalized_input or
            'team' in normalized_input or
            'checklist' in normalized_input or
            'leader' in normalized_input):
            return None

        # Check cache first (unless force_refresh)
        if not force_refresh:
            cached = self._get_from_cache(normalized_input, sport)
            if cached is not None:
                return cached

        # API lookup
        canonical = self._lookup_via_api(normalized_input, sport)

        # Store in cache (even if None, to avoid repeated failed lookups)
        self._store_in_cache(normalized_input, canonical, sport)

        return canonical

    def _get_from_cache(self, input_name: str, sport: str) -> Optional[str]:
        """Retrieve canonical name from cache."""
        conn = sqlite3.connect(self.cache_db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT canonical_name, lookup_date
            FROM canonical_names
            WHERE input_name = ? AND sport = ?
            ORDER BY lookup_date DESC
            LIMIT 1
        """,
            (input_name, sport),
        )

        result = cursor.fetchone()
        conn.close()

        if result:
            # Cache is valid (no TTL expiration for player names - they don't change)
            return result[0]

        return None

    def _lookup_via_api(self, player_name: str, sport: str) -> Optional[str]:
        """Lookup canonical name via MLB Stats API with normalization fallback.

        For modern players: Returns full name from MLB Stats API
        For vintage/historical players: Falls back to normalization (removes middle names, suffixes)
        """
        if sport != "baseball":
            # Only baseball supported currently
            # Fall back to normalization for other sports
            return self.normalize_name_for_matching(player_name)

        try:
            # Rate limiting
            elapsed = time.time() - self.last_api_call
            if elapsed < self.rate_limit_delay:
                time.sleep(self.rate_limit_delay - elapsed)

            # MLB Stats API player search
            players = statsapi.lookup_player(player_name)
            self.last_api_call = time.time()

            if not players:
                # Player not found in API (likely vintage/historical player)
                # Use normalization as fallback
                return self.normalize_name_for_matching(player_name)

            # Take first result (highest confidence match)
            best_match = players[0]

            # Extract canonical full name
            full_name = best_match.get("fullName", "").lower().strip()

            if full_name:
                return full_name

            # API returned results but no fullName - use normalization
            return self.normalize_name_for_matching(player_name)

        except Exception as e:
            print(f"API lookup failed for {player_name}: {e}, using normalization fallback", file=sys.stderr)
            # Fall back to normalization on API errors
            return self.normalize_name_for_matching(player_name)

    def _store_in_cache(
        self,
        input_name: str,
        canonical_name: Optional[str],
        sport: str,
        mlb_id: Optional[int] = None,
        confidence: float = 1.0,
    ):
        """Store lookup result in cache."""
        conn = sqlite3.connect(self.cache_db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT OR REPLACE INTO canonical_names
            (input_name, canonical_name, mlb_player_id, confidence_score, sport)
            VALUES (?, ?, ?, ?, ?)
        """,
            (input_name, canonical_name, mlb_id, confidence, sport),
        )

        conn.commit()
        conn.close()

    def batch_lookup(
        self,
        player_names: list[str],
        sport: str = "baseball",
        progress_callback=None,
    ) -> Dict[str, Optional[str]]:
        """Batch lookup for multiple player names (useful for migration).

        Args:
            player_names: List of player names to lookup
            sport: Sport type
            progress_callback: Optional callback(current, total, player_name)

        Returns:
            Dict mapping input name -> canonical name
        """
        results = {}
        total = len(player_names)

        for i, name in enumerate(player_names):
            canonical = self.get_canonical_name(name, sport)
            results[name] = canonical

            if progress_callback:
                progress_callback(i + 1, total, name)

        return results
