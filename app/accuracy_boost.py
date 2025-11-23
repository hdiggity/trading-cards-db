"""Advanced accuracy enhancement system for card extraction.

Implements:
- Phase 1: Multi-image extraction with result merging
- Phase 2: Player database integration (Retrosheet)
- Phase 3: Learning system (correction tracking and prompt injection)
- Phase 4: Card checklist validation
"""

import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Lazy imports for optional dependencies
CV2_AVAILABLE = False
try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    pass


# -----------------------------------------------------------------------------
# Phase 1: Multi-image extraction with result merging
# -----------------------------------------------------------------------------

def create_image_variants(image_path: str) -> List[Tuple[str, bytes, str]]:
    """Create multiple image variants for extraction.

    Returns list of (variant_name, encoded_bytes, mime_type) tuples.
    """
    from app.utils import convert_image_to_supported_format

    variants = []

    # Variant 1: Enhanced original
    try:
        encoded, mime = convert_image_to_supported_format(image_path, apply_preprocessing=True)
        variants.append(("enhanced", encoded, mime))
    except Exception as e:
        print(f"Failed to create enhanced variant: {e}", file=sys.stderr)

    # Variant 2: High contrast grayscale
    if CV2_AVAILABLE:
        try:
            from app.image_enhancement import create_high_contrast_version
            from PIL import Image
            from io import BytesIO
            import base64

            img = cv2.imread(image_path)
            if img is not None:
                hc = create_high_contrast_version(img)
                # Convert to PIL and encode
                pil_img = Image.fromarray(cv2.cvtColor(hc, cv2.COLOR_BGR2RGB))
                buffer = BytesIO()
                pil_img.save(buffer, format="JPEG", quality=95)
                encoded_hc = base64.b64encode(buffer.getvalue()).decode("utf-8")
                variants.append(("high_contrast", encoded_hc, "image/jpeg"))
        except Exception as e:
            print(f"Failed to create high-contrast variant: {e}", file=sys.stderr)

    # Variant 3: Original without preprocessing (sometimes cleaner)
    try:
        encoded_orig, mime_orig = convert_image_to_supported_format(image_path, apply_preprocessing=False)
        variants.append(("original", encoded_orig, mime_orig))
    except Exception as e:
        print(f"Failed to create original variant: {e}", file=sys.stderr)

    return variants


def merge_extraction_results(results: List[Dict[str, Any]], confidences: List[Dict[str, float]]) -> Dict[str, Any]:
    """Merge multiple extraction results, taking highest confidence values.

    For each field, picks the value from the result with highest confidence for that field.
    """
    if not results:
        return {}
    if len(results) == 1:
        return results[0]

    merged = {}
    fields = set()
    for r in results:
        fields.update(r.keys())

    # Fields that shouldn't be merged (metadata)
    skip_fields = {'_confidence', '_overall_confidence', '_variant', 'grid_position', 'position'}

    for field in fields:
        if field in skip_fields:
            continue

        # Find best value for this field
        best_value = None
        best_conf = -1

        for i, result in enumerate(results):
            if field not in result:
                continue
            value = result[field]
            if value in (None, "", "unknown", "unidentified", "n/a"):
                continue

            # Get confidence for this field from this result
            conf = 0.5  # default
            if i < len(confidences) and field in confidences[i]:
                conf = confidences[i].get(field, 0.5)

            if conf > best_conf:
                best_conf = conf
                best_value = value

        # If no good value found, take first non-empty
        if best_value is None:
            for result in results:
                if field in result and result[field] not in (None, ""):
                    best_value = result[field]
                    break

        if best_value is not None:
            merged[field] = best_value

    return merged


def extract_with_multi_image(image_path: str, prompt: str, parse_func) -> Tuple[List[Dict], Dict]:
    """Extract card data using multiple image variants and merge results.

    Args:
        image_path: Path to the image
        prompt: System prompt to use
        parse_func: Function to parse GPT response into list of cards

    Returns:
        (merged_cards, metadata) where metadata includes per-variant results
    """
    from app.utils import llm_chat

    variants = create_image_variants(image_path)
    if not variants:
        return [], {"error": "No image variants created"}

    all_results = []
    all_confidences = []
    metadata = {"variants_used": [], "per_variant_results": {}}

    for variant_name, encoded, mime in variants:
        try:
            messages = [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{encoded}"}
                        }
                    ]
                }
            ]

            response = llm_chat(
                messages=messages,
                max_tokens=4000,
                temperature=0.1,
            )

            raw_text = response.choices[0].message.content.strip()
            cards = parse_func(raw_text)

            # Extract confidence scores if available
            conf_scores = []
            for card in cards:
                conf = card.get('_confidence', {})
                conf_scores.append(conf)

            all_results.append(cards)
            all_confidences.append(conf_scores)
            metadata["variants_used"].append(variant_name)
            metadata["per_variant_results"][variant_name] = len(cards)

            print(f"  Variant '{variant_name}': extracted {len(cards)} cards", file=sys.stderr)

        except Exception as e:
            print(f"  Variant '{variant_name}' failed: {e}", file=sys.stderr)
            metadata["per_variant_results"][variant_name] = f"error: {str(e)}"

    # Merge results per card position
    if not all_results:
        return [], metadata

    # Assume all variants return same number of cards
    num_cards = max(len(r) for r in all_results)
    merged_cards = []

    for card_idx in range(num_cards):
        card_variants = []
        conf_variants = []

        for result_idx, cards in enumerate(all_results):
            if card_idx < len(cards):
                card_variants.append(cards[card_idx])
                if result_idx < len(all_confidences) and card_idx < len(all_confidences[result_idx]):
                    conf_variants.append(all_confidences[result_idx][card_idx])
                else:
                    conf_variants.append({})

        merged = merge_extraction_results(card_variants, conf_variants)
        merged['_multi_image_sources'] = len(card_variants)
        merged_cards.append(merged)

    metadata["total_merged_cards"] = len(merged_cards)
    return merged_cards, metadata


# -----------------------------------------------------------------------------
# Phase 2: Player database integration
# -----------------------------------------------------------------------------

PLAYER_DB_PATH = Path(__file__).parent.parent / "data" / "players.db"


def init_player_database():
    """Initialize the player database if it doesn't exist."""
    PLAYER_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(PLAYER_DB_PATH))
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            name_normalized TEXT NOT NULL,
            first_year INTEGER,
            last_year INTEGER,
            teams TEXT,
            sport TEXT DEFAULT 'baseball',
            source TEXT DEFAULT 'manual'
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_players_name_normalized
        ON players(name_normalized)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_players_years
        ON players(first_year, last_year)
    """)

    conn.commit()
    conn.close()
    print(f"Player database initialized at {PLAYER_DB_PATH}", file=sys.stderr)


def normalize_player_name(name: str) -> str:
    """Normalize a player name for matching."""
    if not name:
        return ""
    # Lowercase, remove punctuation, normalize whitespace
    normalized = name.lower()
    normalized = re.sub(r"['\.\-]", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def add_player_to_database(name: str, first_year: int = None, last_year: int = None,
                          teams: str = None, sport: str = "baseball", source: str = "manual"):
    """Add a player to the database."""
    init_player_database()

    conn = sqlite3.connect(str(PLAYER_DB_PATH))
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO players (name, name_normalized, first_year, last_year, teams, sport, source)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (name, normalize_player_name(name), first_year, last_year, teams, sport, source))

    conn.commit()
    conn.close()


def lookup_player(name: str, year: int = None, team: str = None, sport: str = "baseball") -> Optional[Dict]:
    """Look up a player in the database.

    Returns player info if found, None otherwise.
    """
    if not PLAYER_DB_PATH.exists():
        return None

    normalized = normalize_player_name(name)
    if not normalized:
        return None

    conn = sqlite3.connect(str(PLAYER_DB_PATH))
    cursor = conn.cursor()

    # Try exact match first
    cursor.execute("""
        SELECT name, first_year, last_year, teams, sport
        FROM players
        WHERE name_normalized = ? AND sport = ?
    """, (normalized, sport))

    row = cursor.fetchone()

    # If no exact match, try partial match
    if not row:
        cursor.execute("""
            SELECT name, first_year, last_year, teams, sport
            FROM players
            WHERE name_normalized LIKE ? AND sport = ?
            ORDER BY LENGTH(name_normalized) ASC
            LIMIT 1
        """, (f"%{normalized}%", sport))
        row = cursor.fetchone()

    conn.close()

    if row:
        player_name, first_year_db, last_year_db, teams_db, sport_db = row

        # Validate year if provided
        if year and first_year_db and last_year_db:
            if not (first_year_db <= year <= last_year_db + 1):  # +1 for cards released year after
                return None

        return {
            "name": player_name,
            "first_year": first_year_db,
            "last_year": last_year_db,
            "teams": teams_db,
            "sport": sport_db,
            "match_type": "database"
        }

    return None


def validate_player_name(card: Dict) -> Dict:
    """Validate and potentially correct player name using database."""
    name = card.get("name", "")
    year = card.get("copyright_year")
    team = card.get("team")
    sport = card.get("sport", "baseball")

    # Skip non-player cards
    if not card.get("is_player_card", True):
        return card

    # Skip already-unknown names
    if name in ("unknown", "unidentified", "n/a", ""):
        return card

    # Try year as int
    year_int = None
    if year:
        try:
            year_int = int(str(year))
        except (ValueError, TypeError):
            pass

    # Look up in database
    player = lookup_player(name, year_int, team, sport)

    if player:
        card["_player_validated"] = True
        card["_player_match"] = player["match_type"]
        # Use canonical name from database
        if player["name"] != name:
            card["name"] = player["name"]
            card["_name_corrected_from"] = name
        # Fill in team if unknown and we have team info from database
        current_team = card.get("team", "")
        if current_team in ("unknown", "unidentified", "n/a", "") and player.get("teams"):
            # Teams field may contain multiple teams comma-separated
            # Try to use the most relevant one based on year
            teams_str = player["teams"]
            if teams_str:
                teams_list = [t.strip() for t in teams_str.split(",")]
                if len(teams_list) == 1:
                    card["team"] = teams_list[0]
                    card["_team_from_player_db"] = True
                elif len(teams_list) > 1:
                    # For now, use the first team (could be improved with year logic)
                    card["team"] = teams_list[0]
                    card["_team_from_player_db"] = True
                    card["_team_options"] = teams_list
    else:
        card["_player_validated"] = False

    return card


def bulk_import_players_from_csv(csv_path: str, sport: str = "baseball"):
    """Import players from a CSV file.

    Expected columns: name, first_year, last_year, teams (comma-separated)
    """
    import csv

    init_player_database()

    conn = sqlite3.connect(str(PLAYER_DB_PATH))
    cursor = conn.cursor()

    count = 0
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get('name', '').strip()
            if not name:
                continue

            first_year = int(row['first_year']) if row.get('first_year') else None
            last_year = int(row['last_year']) if row.get('last_year') else None
            teams = row.get('teams', '').strip()

            cursor.execute("""
                INSERT OR IGNORE INTO players
                (name, name_normalized, first_year, last_year, teams, sport, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (name, normalize_player_name(name), first_year, last_year, teams, sport, "csv_import"))
            count += 1

    conn.commit()
    conn.close()
    print(f"Imported {count} players from {csv_path}", file=sys.stderr)


# -----------------------------------------------------------------------------
# Phase 3: Learning system - correction tracking
# -----------------------------------------------------------------------------

CORRECTIONS_DB_PATH = Path(__file__).parent.parent / "data" / "corrections.db"


def init_corrections_database():
    """Initialize the corrections tracking database."""
    CORRECTIONS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(CORRECTIONS_DB_PATH))
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS corrections (
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
        CREATE INDEX IF NOT EXISTS idx_corrections_field
        ON corrections(field)
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS learned_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_type TEXT NOT NULL,
            pattern_key TEXT NOT NULL,
            pattern_value TEXT NOT NULL,
            confidence REAL DEFAULT 0.5,
            occurrence_count INTEGER DEFAULT 1,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def record_correction(field: str, original: str, corrected: str, context: Dict = None):
    """Record a user correction for learning."""
    init_corrections_database()

    if original == corrected:
        return  # No actual change

    conn = sqlite3.connect(str(CORRECTIONS_DB_PATH))
    cursor = conn.cursor()

    ctx = context or {}
    cursor.execute("""
        INSERT INTO corrections (field, original_value, corrected_value, brand, year, sport, card_set, context)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        field,
        str(original) if original else None,
        str(corrected) if corrected else None,
        ctx.get("brand"),
        ctx.get("copyright_year"),
        ctx.get("sport"),
        ctx.get("card_set"),
        json.dumps(ctx) if ctx else None
    ))

    conn.commit()
    conn.close()

    # Update learned patterns
    _update_learned_pattern(field, original, corrected, ctx)


def _update_learned_pattern(field: str, original: str, corrected: str, context: Dict):
    """Update learned patterns based on correction."""
    conn = sqlite3.connect(str(CORRECTIONS_DB_PATH))
    cursor = conn.cursor()

    # Create pattern key from field + original value
    pattern_key = f"{field}:{original}"

    # Check if pattern exists
    cursor.execute("""
        SELECT id, occurrence_count FROM learned_patterns
        WHERE pattern_type = 'correction' AND pattern_key = ? AND pattern_value = ?
    """, (pattern_key, corrected))

    row = cursor.fetchone()
    if row:
        # Update existing
        cursor.execute("""
            UPDATE learned_patterns
            SET occurrence_count = occurrence_count + 1,
                confidence = MIN(0.99, confidence + 0.1),
                last_seen = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (row[0],))
    else:
        # Insert new
        cursor.execute("""
            INSERT INTO learned_patterns (pattern_type, pattern_key, pattern_value, confidence)
            VALUES ('correction', ?, ?, 0.5)
        """, (pattern_key, corrected))

    conn.commit()
    conn.close()


def get_learned_corrections(min_confidence: float = 0.6, min_occurrences: int = 2) -> Dict[str, str]:
    """Get high-confidence learned corrections.

    Returns dict of {pattern_key: corrected_value}
    """
    if not CORRECTIONS_DB_PATH.exists():
        return {}

    conn = sqlite3.connect(str(CORRECTIONS_DB_PATH))
    cursor = conn.cursor()

    cursor.execute("""
        SELECT pattern_key, pattern_value
        FROM learned_patterns
        WHERE pattern_type = 'correction'
          AND confidence >= ?
          AND occurrence_count >= ?
        ORDER BY confidence DESC
    """, (min_confidence, min_occurrences))

    corrections = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()

    return corrections


def apply_learned_corrections(card: Dict) -> Dict:
    """Apply learned corrections to a card."""
    corrections = get_learned_corrections()
    if not corrections:
        return card

    modified = card.copy()
    applied = []

    for field in ["name", "brand", "team", "card_set", "copyright_year"]:
        if field not in card:
            continue
        value = card[field]
        if value in (None, ""):
            continue

        pattern_key = f"{field}:{value}"
        if pattern_key in corrections:
            modified[field] = corrections[pattern_key]
            applied.append(f"{field}: {value} -> {corrections[pattern_key]}")

    if applied:
        modified["_learned_corrections_applied"] = applied

    return modified


def generate_prompt_enhancements_from_learning() -> str:
    """Generate prompt enhancements based on learned patterns."""
    if not CORRECTIONS_DB_PATH.exists():
        return ""

    conn = sqlite3.connect(str(CORRECTIONS_DB_PATH))
    cursor = conn.cursor()

    # Get most common correction patterns
    cursor.execute("""
        SELECT field, original_value, corrected_value, COUNT(*) as cnt
        FROM corrections
        WHERE original_value IS NOT NULL AND corrected_value IS NOT NULL
        GROUP BY field, original_value, corrected_value
        HAVING cnt >= 2
        ORDER BY cnt DESC
        LIMIT 10
    """)

    patterns = cursor.fetchall()
    conn.close()

    if not patterns:
        return ""

    lines = ["\n\nLEARNED CORRECTIONS (apply these automatically):"]
    for field, orig, corrected, count in patterns:
        lines.append(f"- {field}: '{orig}' should be '{corrected}' (seen {count}x)")

    return "\n".join(lines)


# -----------------------------------------------------------------------------
# Phase 4: Card checklist validation
# -----------------------------------------------------------------------------

CHECKLISTS_DB_PATH = Path(__file__).parent.parent / "data" / "checklists.db"


def init_checklists_database():
    """Initialize the card checklists database."""
    CHECKLISTS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(CHECKLISTS_DB_PATH))
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS card_sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            year INTEGER NOT NULL,
            brand TEXT NOT NULL,
            set_name TEXT NOT NULL,
            sport TEXT DEFAULT 'baseball',
            total_cards INTEGER,
            source TEXT
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sets_lookup
        ON card_sets(year, brand, sport)
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS set_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            set_id INTEGER NOT NULL,
            card_number TEXT NOT NULL,
            player_name TEXT,
            team TEXT,
            FOREIGN KEY (set_id) REFERENCES card_sets(id)
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_set_cards_number
        ON set_cards(set_id, card_number)
    """)

    conn.commit()
    conn.close()


def add_set_to_checklist(year: int, brand: str, set_name: str, total_cards: int,
                         sport: str = "baseball", source: str = "manual") -> int:
    """Add a card set to the checklists database. Returns set_id."""
    init_checklists_database()

    conn = sqlite3.connect(str(CHECKLISTS_DB_PATH))
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO card_sets (year, brand, set_name, sport, total_cards, source)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (year, brand.lower(), set_name, sport, total_cards, source))

    set_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return set_id


def add_card_to_checklist(set_id: int, card_number: str, player_name: str = None, team: str = None):
    """Add a card to a set's checklist."""
    conn = sqlite3.connect(str(CHECKLISTS_DB_PATH))
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO set_cards (set_id, card_number, player_name, team)
        VALUES (?, ?, ?, ?)
    """, (set_id, str(card_number), player_name, team))

    conn.commit()
    conn.close()


def get_set_info(year: int, brand: str, sport: str = "baseball") -> Optional[Dict]:
    """Get set information for validation."""
    if not CHECKLISTS_DB_PATH.exists():
        return None

    conn = sqlite3.connect(str(CHECKLISTS_DB_PATH))
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, year, brand, set_name, total_cards
        FROM card_sets
        WHERE year = ? AND brand = ? AND sport = ?
        LIMIT 1
    """, (year, brand.lower(), sport))

    row = cursor.fetchone()
    conn.close()

    if row:
        return {
            "set_id": row[0],
            "year": row[1],
            "brand": row[2],
            "set_name": row[3],
            "total_cards": row[4]
        }
    return None


def validate_card_number(card: Dict) -> Dict:
    """Validate card number against known checklists."""
    year = card.get("copyright_year")
    brand = card.get("brand")
    number = card.get("number")
    sport = card.get("sport", "baseball")

    if not all([year, brand, number]):
        return card

    # Parse year
    try:
        year_int = int(str(year))
    except (ValueError, TypeError):
        return card

    # Parse card number
    try:
        num_int = int(str(number).replace("#", "").strip())
    except (ValueError, TypeError):
        return card  # Non-numeric card number, can't validate

    set_info = get_set_info(year_int, brand, sport)

    if set_info:
        card["_checklist_validated"] = True
        card["_set_name"] = set_info["set_name"]

        if set_info["total_cards"]:
            if num_int > set_info["total_cards"]:
                card["_card_number_warning"] = f"Card #{num_int} exceeds set size ({set_info['total_cards']} cards)"
                card["_checklist_valid"] = False
            else:
                card["_checklist_valid"] = True
    else:
        card["_checklist_validated"] = False

    return card


def seed_common_checklists():
    """Seed database with common vintage Topps set sizes."""
    init_checklists_database()

    # Common Topps baseball set sizes
    topps_sets = [
        (1970, "topps", "1970 Topps", 720),
        (1971, "topps", "1971 Topps", 752),
        (1972, "topps", "1972 Topps", 787),
        (1973, "topps", "1973 Topps", 660),
        (1974, "topps", "1974 Topps", 660),
        (1975, "topps", "1975 Topps", 660),
        (1976, "topps", "1976 Topps", 660),
        (1977, "topps", "1977 Topps", 660),
        (1978, "topps", "1978 Topps", 726),
        (1979, "topps", "1979 Topps", 726),
        (1980, "topps", "1980 Topps", 726),
        (1981, "topps", "1981 Topps", 726),
        (1982, "topps", "1982 Topps", 792),
        (1983, "topps", "1983 Topps", 792),
        (1984, "topps", "1984 Topps", 792),
        (1985, "topps", "1985 Topps", 792),
        (1986, "topps", "1986 Topps", 792),
        (1987, "topps", "1987 Topps", 792),
        (1988, "topps", "1988 Topps", 792),
        (1989, "topps", "1989 Topps", 792),
        (1990, "topps", "1990 Topps", 792),
    ]

    for year, brand, name, total in topps_sets:
        # Check if already exists
        if not get_set_info(year, brand):
            add_set_to_checklist(year, brand, name, total, source="seed")

    print("Seeded common Topps checklists", file=sys.stderr)


# -----------------------------------------------------------------------------
# Combined enhancement function
# -----------------------------------------------------------------------------

def enhance_card_accuracy(card: Dict) -> Dict:
    """Apply all accuracy enhancements to a card.

    Runs:
    1. Learned corrections
    2. Player database validation
    3. Checklist validation
    """
    # Phase 3: Apply learned corrections
    card = apply_learned_corrections(card)

    # Phase 2: Validate player name
    card = validate_player_name(card)

    # Phase 4: Validate card number
    card = validate_card_number(card)

    return card


def enhance_cards_batch(cards: List[Dict]) -> List[Dict]:
    """Apply all accuracy enhancements to a batch of cards."""
    return [enhance_card_accuracy(card) for card in cards]
