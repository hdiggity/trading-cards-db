"""Simplified single-pass GPT Vision extraction for 3x3 grid card backs."""

import base64
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Tuple

from PIL import Image
from pillow_heif import register_heif_opener

from .correction_tracker import CorrectionTracker
from .utils import client

register_heif_opener()
MODEL = os.getenv("OPENAI_MODEL", "gpt-5.2")

# Load Hall of Fame list
_hall_of_fame_cache = None

def load_hall_of_fame():
    """Load MLB Hall of Fame player names."""
    global _hall_of_fame_cache
    if _hall_of_fame_cache is None:
        hof_path = Path(__file__).parent / 'awards_data' / 'hall_of_fame.json'
        try:
            with open(hof_path, 'r', encoding='utf-8') as f:
                _hall_of_fame_cache = set(json.load(f))
        except Exception as e:
            print(f"Warning: Could not load Hall of Fame list: {e}", file=sys.stderr)
            _hall_of_fame_cache = set()
    return _hall_of_fame_cache

def is_hall_of_famer(name):
    """Check if a player name matches a Hall of Famer."""
    if not name or not isinstance(name, str):
        return False
    normalized_name = name.lower().strip()
    return normalized_name in load_hall_of_fame()

# Load award years caches
_rookie_years_cache = None
_mvp_years_cache = None
_cy_young_years_cache = None
_triple_crown_years_cache = None

def load_rookie_years():
    """Load MLB rookie year mappings."""
    global _rookie_years_cache
    if _rookie_years_cache is None:
        rookie_path = Path(__file__).parent / 'awards_data' / 'rookie_years.json'
        try:
            with open(rookie_path, 'r', encoding='utf-8') as f:
                _rookie_years_cache = json.load(f)
        except Exception as e:
            print(f"Warning: Could not load rookie years: {e}", file=sys.stderr)
            _rookie_years_cache = {}
    return _rookie_years_cache

def load_award_years(award_type):
    """Load award year mappings for MVP, Cy Young, or Triple Crown."""
    global _mvp_years_cache, _cy_young_years_cache, _triple_crown_years_cache

    if award_type == 'mvp':
        if _mvp_years_cache is None:
            path = Path(__file__).parent / 'awards_data' / 'mvp_years.json'
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    _mvp_years_cache = json.load(f)
            except Exception as e:
                print(f"Warning: Could not load MVP years: {e}", file=sys.stderr)
                _mvp_years_cache = {}
        return _mvp_years_cache
    elif award_type == 'cy_young':
        if _cy_young_years_cache is None:
            path = Path(__file__).parent / 'awards_data' / 'cy_young_years.json'
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    _cy_young_years_cache = json.load(f)
            except Exception as e:
                print(f"Warning: Could not load Cy Young years: {e}", file=sys.stderr)
                _cy_young_years_cache = {}
        return _cy_young_years_cache
    elif award_type == 'triple_crown':
        if _triple_crown_years_cache is None:
            path = Path(__file__).parent / 'awards_data' / 'triple_crown_years.json'
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    _triple_crown_years_cache = json.load(f)
            except Exception as e:
                print(f"Warning: Could not load Triple Crown years: {e}", file=sys.stderr)
                _triple_crown_years_cache = {}
        return _triple_crown_years_cache
    return {}

def normalize_name_for_matching(name):
    """Normalize a name for fuzzy matching (handles middle names, suffixes,
    accents)."""
    if not name or not isinstance(name, str):
        return ""

    # Remove accents and normalize to ASCII
    name = unicodedata.normalize('NFD', name)
    name = ''.join(char for char in name if unicodedata.category(char) != 'Mn')

    # Remove common suffixes
    name = re.sub(r'\s+(jr\.?|sr\.?|iii?|iv)$', '', name.lower().strip(), flags=re.IGNORECASE)

    # Split into parts
    parts = name.split()
    if len(parts) <= 2:
        return ' '.join(parts)

    # Return first + last name (skip middle names)
    return f"{parts[0]} {parts[-1]}"

def matches_player(card_name, award_name):
    """Check if card name matches an award winner name (handles variations)."""
    if not card_name or not award_name:
        return False

    card_normalized = normalize_name_for_matching(card_name)
    award_normalized = normalize_name_for_matching(award_name)

    # Exact match
    if card_normalized == award_normalized:
        return True

    # Also check if full card name matches (in case award has middle name)
    if card_name.lower().strip() == award_name.lower().strip():
        return True

    return False

def is_rookie_card(name, copyright_year):
    """Check if a card is a rookie card based on name and year."""
    if not name or not copyright_year:
        return False

    rookie_years = load_rookie_years()

    # Check against all rookie names
    for rookie_name, rookie_year in rookie_years.items():
        if matches_player(name, rookie_name):
            # Rookie cards are from the year AFTER the player's rookie season
            # E.g., if player was rookie in 2024, their 2025 card is the rookie card
            try:
                card_year = int(copyright_year)
                return card_year == rookie_year + 1
            except (ValueError, TypeError):
                return False

    return False

def has_award_in_year(name, copyright_year, award_type):
    """Check if a player won an award in the year before the copyright year."""
    if not name or not copyright_year:
        return False

    award_years = load_award_years(award_type)

    # Check against all award winners
    for winner_name, years in award_years.items():
        if matches_player(name, winner_name):
            # Award cards are from the year AFTER they won
            # E.g., if player won MVP in 2024, their 2025 card has "season mvp" feature
            try:
                card_year = int(copyright_year)
                # years can be a list (for multiple wins)
                if isinstance(years, list):
                    return (card_year - 1) in years
                else:
                    return card_year - 1 == years
            except (ValueError, TypeError):
                return False

    return False

# Shared prompt text for value estimation
VALUE_ESTIMATE_PROMPT = """Estimate the card's market value considering ALL factors: player name and reputation, copyright year, brand/manufacturer, card set, condition (most important for value), features (rookie, autograph, serial numbered, memorabilia, hall of fame, awards like season mvp/cy young season/triple crown season, etc.), and any special notes (error cards, variations, short prints). Popular players, older cards in good condition, and special features increase value. Format as $xx.xx (e.g., $0.50 for common cards, $2.00-$10.00 for solid players in good condition, $25.00-$100.00+ for rookie cards of stars or cards with multiple premium features)."""

# Initialize correction tracker
correction_tracker = CorrectionTracker(db_path="data/corrections.db")

def normalize_price(price_str):
    """Validate and normalize price to $xx.xx format."""
    if not price_str:
        return "$1.00"

    # Check if already in correct format
    if re.match(r'^\$\d+\.\d{2}$', str(price_str)):
        return str(price_str)

    # Extract all numbers from the string
    nums = re.findall(r'\d+\.?\d*', str(price_str))
    if not nums:
        return "$1.00"

    # Take first number or average if multiple
    if len(nums) == 1:
        val = float(nums[0])
    else:
        val = sum(float(n) for n in nums) / len(nums)

    # Round to common price points and format as $xx.xx
    if val < 1.5:
        return "$1.00"
    elif val < 2.5:
        return "$2.00"
    elif val < 4:
        return "$3.00"
    elif val < 7:
        return "$5.00"
    elif val < 15:
        return "$10.00"
    elif val < 30:
        return "$20.00"
    elif val < 75:
        return "$50.00"
    elif val < 150:
        return "$100.00"
    else:
        return f"${int(val)}.00"


def normalize_condition(condition_str):
    """Normalize condition to valid values: mint, near_mint, excellent, very_good, good, fair, poor, damaged."""
    if not condition_str:
        return "good"

    cond = str(condition_str).lower().strip()

    # Direct matches
    valid = ["mint", "near_mint", "excellent", "very_good", "good", "fair", "poor", "damaged"]
    if cond in valid:
        return cond

    # Handle variations
    cond_normalized = cond.replace("-", "_").replace(" ", "_")
    if cond_normalized in valid:
        return cond_normalized

    # Keyword matching for verbose descriptions
    if "mint" in cond and "near" not in cond:
        return "mint"
    if "near" in cond and "mint" in cond:
        return "near_mint"
    if "excellent" in cond or "exc" in cond:
        return "excellent"
    if "very" in cond and "good" in cond:
        return "very_good"
    if "fair" in cond:
        return "fair"
    if "poor" in cond:
        return "poor"
    if "damaged" in cond or "torn" in cond or "water" in cond:
        return "damaged"
    if "good" in cond:
        return "good"
    if "clean" in cond or "minor" in cond:
        return "very_good"
    if "wear" in cond or "worn" in cond:
        return "good"

    # Default
    return "good"


def normalize_features(features_str):
    """Normalize features to valid values only."""
    if not features_str:
        return "none"

    feat = str(features_str).lower().strip()

    if feat in ("none", "n/a", "null", "unknown", ""):
        return "none"

    # Valid feature keywords
    valid_features = [
        "rookie", "error", "autograph", "auto", "serial numbered", "memorabilia",
        "relic", "patch", "refractor", "parallel", "short print", "sp",
        "hall of fame", "hof", "season mvp", "cy young season", "triple crown season",
        "all-star", "gold", "silver", "chrome", "prizm", "checklist"
    ]

    # Parse comma-separated features
    parts = [p.strip() for p in feat.split(",")]
    normalized = []

    for part in parts:
        if not part or part in ("none", "n/a"):
            continue
        # Check if part contains a valid feature keyword
        for valid in valid_features:
            if valid in part:
                # Use the canonical form
                if valid == "auto":
                    normalized.append("autograph")
                elif valid == "hof":
                    normalized.append("hall of fame")
                elif valid == "sp":
                    normalized.append("short print")
                else:
                    normalized.append(valid)
                break
        # Skip verbose descriptions that don't match valid features

    if not normalized:
        return "none"

    return ",".join(sorted(set(normalized)))


def normalize_card_set(card_set_str, brand=None):
    """Normalize card_set - return 'n/a' for base cards, keep valid subset names with brand prefix."""
    if not card_set_str:
        return "n/a"

    cs = str(card_set_str).lower().strip()
    brand_lower = (brand or '').lower().strip()

    # Already n/a
    if cs in ("n/a", "na", "none", "null", "unknown", "base", "base set", ""):
        return "n/a"

    # Valid subset names to keep
    valid_subsets = [
        "traded", "update", "chrome", "heritage", "opening day", "archives",
        "all-star", "rookie cup", "future stars", "record breaker", "draft picks",
        "prospects", "mini", "tiffany", "gold", "silver", "platinum", "diamond",
        "refractor", "prizm", "optic", "select", "mosaic", "donruss", "panini"
    ]

    # Check if it's a valid subset
    for subset in valid_subsets:
        if subset in cs:
            # Return brand + subset (e.g., "topps traded" not just "traded")
            if brand_lower and brand_lower not in cs:
                return f"{brand_lower} {subset}"
            return subset

    # Filter out year+brand combinations like "2012 topps baseball", "1975 topps", etc.
    # These are not subsets, just descriptions of the base set
    if re.match(r'^\d{4}\s*(topps|donruss|fleer|upper deck|bowman|score|leaf)', cs):
        return "n/a"

    # Filter out generic descriptions
    if "baseball" in cs or "checklist" in cs or "base" in cs:
        return "n/a"

    # If it's short and doesn't look like a year+brand, keep it
    if len(cs) < 20 and not re.search(r'\d{4}', cs):
        # Add brand prefix if not already included
        if brand_lower and brand_lower not in cs:
            return f"{brand_lower} {cs}"
        return cs

    return "n/a"


def normalize_notes(notes_str):
    """Normalize notes - reject unhelpful patterns, abbreviate to most important info."""
    if not notes_str:
        return "none"

    n = str(notes_str).lower().strip()

    if len(n) < 3 or n in ("none", "n/a", "na", "null", "unknown", ""):
        return "none"

    # Keep patterns that indicate collector value
    keep_patterns = [
        "rookie", "rc", "sp", "ssp", "short print", "error", "variation", "var",
        "refractor", "chrome", "parallel", "insert", "chase", "limited", "serial",
        "numbered", "#/", "/99", "/50", "/25", "/10", "/5", "/1", "auto", "relic",
        "patch", "jersey", "bat", "game-used", "gem", "mint", "psa", "bgs", "sgc",
        "rare", "scarce", "tough", "key", "hof", "hall of fame", "mvp", "all-star",
        "first", "debut", "last", "final", "historic", "record", "milestone"
    ]

    # If note contains collector value keywords, keep it
    for pattern in keep_patterns:
        if pattern in n:
            return notes_str.strip()[:80] if len(notes_str) > 80 else notes_str.strip()

    # Reject if only generic descriptions or extraction metadata
    reject_patterns = [
        "back shows", "back reads", "back text", "standard card",
        "nothing special", "no special", "base card", "common card",
        "regular card", "standard issue",
        "number includes", "includes 't'", "includes t", "traded/transaction",
        "transaction card", "card number contains", "card number includes",
        "number starts with", "number ends with", "number format",
        "typical", "typical card", "regular issue", "standard format"
    ]

    for pattern in reject_patterns:
        if pattern in n:
            return "none"

    # Smart abbreviation to fit 80 chars while keeping important info
    if len(n) <= 80:
        return n

    # Common abbreviations for collectible card terminology
    abbreviations = [
        ("short print", "sp"),
        ("super short print", "ssp"),
        ("serial numbered", "s/n"),
        ("limited edition", "ltd"),
        ("variation", "var"),
        ("photo variation", "photo var"),
        ("error card", "error"),
        ("uncorrected error", "ue"),
        ("corrected error", "ce"),
        ("printing plate", "plate"),
        ("refractor", "ref"),
        ("parallel", "//"),
        ("numbered to", "#/"),
        ("out of", "/"),
        ("factory set", "fact set"),
        ("tiffany", "tiff"),
        ("glossy", "gloss"),
        ("printing", "print"),
        ("miscut", "miscut"),
        ("off-center", "oc"),
        ("diamond", "dia"),
        (" and ", " & "),
        ("variation", "var"),
        ("insert", "ins"),
        ("subset", "sub"),
    ]

    result = n
    for full, abbrev in abbreviations:
        result = result.replace(full, abbrev)

    # If still too long, truncate at sentence/phrase boundary
    if len(result) > 80:
        # Try to find natural break points
        for sep in ["; ", ", ", " - ", ": "]:
            if sep in result:
                parts = result.split(sep)
                truncated = ""
                for part in parts:
                    if len(truncated) + len(part) + len(sep) <= 77:
                        truncated = truncated + sep + part if truncated else part
                    else:
                        break
                if truncated and len(truncated) > 10:
                    result = truncated
                    break

    # Final truncation if still over limit
    if len(result) > 80:
        result = result[:77] + "..."

    return result


def normalize_team(team_str, card_data):
    """Normalize team - strip suffixes, keep only city + team name."""
    if not team_str:
        return None

    t = str(team_str).lower().strip()

    if t in ("n/a", "na", "null", "unknown", ""):
        return None

    # Known MLB team names (for detecting team names in parentheses)
    mlb_teams = {
        'angels', 'astros', 'athletics', 'blue jays', 'braves', 'brewers',
        'cardinals', 'cubs', 'diamondbacks', 'dodgers', 'giants', 'guardians',
        'indians', 'mariners', 'marlins', 'mets', 'nationals', 'orioles',
        'padres', 'phillies', 'pirates', 'rangers', 'rays', 'red sox',
        'reds', 'rockies', 'royals', 'tigers', 'twins', 'white sox', 'yankees',
        'expos', 'senators', 'pilots', 'browns', 'colt .45s', 'colts'
    }

    # Check if parentheses contain a team name (use it) vs descriptor (strip it)
    paren_match = re.search(r'\(([^)]+)\)\s*$', t)
    if paren_match:
        paren_content = paren_match.group(1).strip()
        # If parentheses contain a known team name, combine city with team name
        if any(team in paren_content for team in mlb_teams):
            city_part = re.sub(r'\s*\([^)]*\)\s*$', '', t).strip()
            city_part = re.sub(r'\s+(n\.?l\.?|a\.?l\.?)\s*$', '', city_part, flags=re.IGNORECASE).strip()
            if city_part:
                t = f"{city_part} {paren_content}"
            else:
                t = paren_content
        else:
            # Strip non-team parentheticals like (mlb), (news item), (trade)
            t = re.sub(r'\s*\([^)]*\)\s*$', '', t).strip()

    # Check if card is checklist or league leaders based on name/features
    name = (card_data.get('name') or '').lower()
    is_player = card_data.get('is_player_card', True)

    if not is_player:
        # Non-player cards that involve multiple teams
        if any(kw in name for kw in ['checklist', 'league leaders', 'leaders (']):
            return "multiple"

    return t if t else None


def normalize_name(name_str):
    """Normalize name - convert parentheses to semicolons for multiple names."""
    if not name_str:
        return None

    n = str(name_str).strip()

    # Convert patterns like "Name (Other Info)" to "name; other info"
    # But only for multi-name cards, not descriptive parentheses
    # Pattern: "league leaders (2012 national league runs batted in)" stays as-is
    # Pattern: "john doe (mike smith, bob jones)" becomes "john doe; mike smith; bob jones"

    # Check if parentheses contain names (commas inside = likely multiple names)
    match = re.match(r'^([^(]+)\(([^)]+)\)$', n)
    if match:
        main_part = match.group(1).strip()
        paren_part = match.group(2).strip()

        # If paren contains comma-separated items that look like names, convert
        if ',' in paren_part and not any(kw in paren_part.lower() for kw in ['league', 'year', 'game', 'season']):
            names = [main_part] + [p.strip() for p in paren_part.split(',')]
            return '; '.join(names).lower()

    return n.lower()


@dataclass
class GridCard:
    """Represents a card extracted from a grid with position info."""
    position: int  # 0-8 for 3x3 grid (top-left to bottom-right)
    row: int       # 0-2
    col: int       # 0-2
    data: Dict[str, Any]
    confidence: float = 0.0


class GridProcessor:
    """Simple single-pass GPT Vision processor for 3x3 grid card backs."""

    def process_3x3_grid(self, image_path: str, front_images_dir: Path = None, progress_callback=None) -> Tuple[List[GridCard], List[Dict]]:
        """Process a 3x3 grid of card backs with single-pass GPT Vision
        extraction.

        Args:
            image_path: Path to the 3x3 grid image
            front_images_dir: Ignored (no front matching)
            progress_callback: Optional callback(substep, detail) for progress updates

        Returns: (grid_cards, raw_data)
        """
        def report(substep, detail=""):
            if progress_callback:
                progress_callback(substep, detail)
            print(f"[{substep}] {detail}", file=sys.stderr) if detail else print(f"[{substep}]", file=sys.stderr)

        report("gpt_extraction", f"Sending to GPT Vision: {image_path}")

        # Get example features from database
        feature_examples = self._get_feature_examples()
        if feature_examples:
            f" Examples from database: {', '.join(feature_examples)}."

        # Load and encode image
        img = Image.open(image_path)
        max_size = 4000
        if max(img.size) > max_size:
            ratio = max_size / max(img.size)
            img = img.resize((int(img.size[0] * ratio), int(img.size[1] * ratio)), Image.LANCZOS)
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=95)
        img_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

        # Single-pass extraction prompt
        prompt = """Grid of trading card backs, left-to-right top-to-bottom.

Extract for each card:

1. name (full name including last name)
2. number
3. team (full team name with city AND mascot, e.g. "chicago cubs" not just "chicago" - use most recent team only)
4. copyright_year
5. brand
6. card_set
7. sport
8. condition (grade relative to card's age - yellowing, vintage print quality, old card stock are normal for pre-1990 cards, not damage)
9. is_player_card: true/false
10. features
11. notes (collector value: rookie card, serial #/print run, error, variation, short print, insert/chase card, refractor, autograph, relic, or "none" if standard base card)
12. value_estimate

IMPORTANT: Never return null or empty strings for name, number, brand, or sport fields.
If you cannot determine a value, use your best guess based on the card image.
For sport, default to "baseball" if unclear.

Return JSON with "cards" array."""

        # Define structured output schema
        response_schema = {
            "type": "json_schema",
            "json_schema": {
                "name": "card_grid_extraction",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "cards": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "grid_position": {"type": "integer"},
                                    "name": {"type": "string"},
                                    "number": {"type": ["string", "null"]},
                                    "team": {"type": ["string", "null"]},
                                    "copyright_year": {"type": ["string", "null"]},
                                    "brand": {"type": ["string", "null"]},
                                    "card_set": {"type": ["string", "null"]},
                                    "sport": {"type": "string"},
                                    "condition": {"type": ["string", "null"]},
                                    "is_player_card": {"type": "boolean"},
                                    "features": {"type": "string"},
                                    "notes": {"type": "string"},
                                    "value_estimate": {"type": "string"}
                                },
                                "required": [
                                    "grid_position", "name", "number", "team",
                                    "copyright_year", "brand", "card_set", "sport",
                                    "condition", "is_player_card", "features",
                                    "notes", "value_estimate"
                                ],
                                "additionalProperties": False
                            }
                        }
                    },
                    "required": ["cards"],
                    "additionalProperties": False
                }
            }
        }

        # Call GPT Vision API with structured outputs
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are a trading card expert. Extract data accurately from card backs."},
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                ]}
            ],
            response_format=response_schema,
            max_completion_tokens=2000,
            temperature=0.1
        )

        result_text = response.choices[0].message.content.strip()

        # Parse structured output
        result_json = json.loads(result_text)
        raw_data = result_json.get("cards", [])

        # Ensure exactly 9 cards
        if len(raw_data) != 9:
            print(f"Warning: Expected 9 cards, got {len(raw_data)}", file=sys.stderr)
            while len(raw_data) < 9:
                raw_data.append(self._create_default_card(len(raw_data)))
            raw_data = raw_data[:9]

        # Add grid metadata
        for i, card in enumerate(raw_data):
            card.setdefault('grid_position', i)
            card.setdefault('_grid_metadata', {"position": i, "row": i // 3, "col": i % 3})

        # Validate required fields - flag blanks for manual review
        required_fields = ['name', 'number', 'brand', 'sport']
        for card in raw_data:
            for field in required_fields:
                value = card.get(field)
                if not value or (isinstance(value, str) and not value.strip()):
                    if field == 'sport':
                        card[field] = 'baseball'  # Default sport
                    else:
                        card[field] = 'unknown'
                    card['_blank_field_warning'] = card.get('_blank_field_warning', [])
                    card['_blank_field_warning'].append(field)

        # Store original GPT extraction before any modifications
        # This preserves what GPT actually extracted for correction tracking
        for card in raw_data:
            card['_original_extraction'] = {
                'name': card.get('name'),
                'brand': card.get('brand'),
                'team': card.get('team'),
                'card_set': card.get('card_set'),
                'copyright_year': card.get('copyright_year'),
                'number': card.get('number'),
                'condition': card.get('condition'),
                'sport': card.get('sport'),
                'is_player': card.get('is_player_card'),
                'features': card.get('features'),
                'value_estimate': card.get('value_estimate'),
                'notes': card.get('notes')
            }

        report("post_processing", "Starting post-processing")

        # Initialize canonical name service (used after normalization)
        from app.player_canonical import CanonicalNameService
        canonical_service = CanonicalNameService()

        report("feature_detection", "Detecting special features")

        # Auto-add Hall of Fame feature for recognized players
        for card in raw_data:
            if card.get('is_player_card', True) and card.get('sport') == 'baseball':
                if is_hall_of_famer(card.get('name')):
                    existing_features = card.get('features', 'none')
                    if existing_features == 'none':
                        card['features'] = 'hall of fame'
                    elif 'hall of fame' not in existing_features:
                        card['features'] = f"{existing_features},hall of fame"

        # Auto-add rookie, MVP, Cy Young, and Triple Crown features
        def add_feature(card, feature_name):
            """Helper to add a feature to a card."""
            existing = card.get('features', 'none')
            if existing == 'none':
                card['features'] = feature_name
            elif feature_name not in existing:
                card['features'] = f"{existing},{feature_name}"

        for card in raw_data:
            if card.get('is_player_card', True) and card.get('sport') == 'baseball':
                name = card.get('name')
                year = card.get('copyright_year')

                # Check for rookie card
                if is_rookie_card(name, year):
                    add_feature(card, 'rookie')

                # Check for season MVP
                if has_award_in_year(name, year, 'mvp'):
                    add_feature(card, 'season mvp')

                # Check for Cy Young season
                if has_award_in_year(name, year, 'cy_young'):
                    add_feature(card, 'cy young season')

                # Check for Triple Crown season
                if has_award_in_year(name, year, 'triple_crown'):
                    add_feature(card, 'triple crown season')

        # Apply validation rules to fix known error patterns
        for card in raw_data:
            card.update(self._apply_validation_rules(card))

        # Note: Appearance validation system removed - GPT-5.2 extraction trusted directly

        # Store original GPT data for confidence calculation
        original_gpt_data = [card.copy() for card in raw_data]

        # ML prediction step: check for retraining and apply ML corrections
        report("ml_prediction", "Generating ML predictions")
        try:
            from .ml_engine import get_ml_engine
            ml_engine = get_ml_engine()

            # Check if models need retraining (runs automatically if criteria met)
            ml_engine.retrain_if_needed()

            # Apply ML predictions to all cards
            for i, card in enumerate(raw_data):
                raw_data[i] = ml_engine.predict_all_fields(card, original_gpt_data[i])
        except Exception as e:
            print(f"ML prediction step failed: {e}", file=sys.stderr)

        report("learned_corrections", "Applying learned corrections")

        # Apply learned corrections from previous manual fixes
        for i, card in enumerate(raw_data):
            raw_data[i] = correction_tracker.apply_learned_corrections(card)

        # Apply learned condition predictions
        for i, card in enumerate(raw_data):
            predicted_condition = correction_tracker.predict_condition(card)
            if predicted_condition:
                raw_data[i]['condition'] = predicted_condition
                raw_data[i]['_condition_predicted'] = True

        report("normalization", "Final normalization pass")

        # Final normalization pass (AFTER learned corrections to ensure consistency)
        for card in raw_data:
            for key in ("sport", "brand", "card_set", "notes"):
                if key in card and card[key] is not None and isinstance(card[key], str):
                    card[key] = card[key].lower().strip()
            if 'name' in card:
                card['name'] = normalize_name(card['name'])
            if 'team' in card:
                card['team'] = normalize_team(card['team'], card)
            if 'condition' in card:
                card['condition'] = normalize_condition(card['condition'])
            if 'features' in card:
                card['features'] = normalize_features(card['features'])
            if 'card_set' in card:
                card['card_set'] = normalize_card_set(card['card_set'], card.get('brand'))
            if 'notes' in card:
                card['notes'] = normalize_notes(card['notes'])
            if 'value_estimate' in card:
                card['value_estimate'] = normalize_price(card['value_estimate'])

        # Add canonical names for player cards using MLB Stats API
        # (after normalization so sport field is lowercase)
        report("canonical_names", "Looking up canonical names")

        for card in raw_data:
            if card.get('is_player_card', True) and card.get('sport') == 'baseball':
                player_name = card.get('name')
                if player_name:
                    canonical = canonical_service.get_canonical_name(player_name, 'baseball')
                    card['canonical_name'] = canonical

                    # Track if we couldn't get canonical name
                    if canonical is None:
                        card['_canonical_lookup_failed'] = True
            else:
                # Non-player cards don't need canonical names
                card['canonical_name'] = None

        report("name_standardization", "Applying name standardization")

        # Apply name standardization - use canonical_name if available
        # (e.g., "johnny lee bench" -> "johnny bench")
        for card in raw_data:
            if card.get('name') and card.get('sport') == 'baseball':
                # Prefer canonical_name (already looked up), otherwise try get_standard_name
                canonical = card.get('canonical_name')
                if canonical and canonical != card['name']:
                    card['name'] = canonical
                else:
                    standard = canonical_service.get_standard_name(card['name'])
                    if standard:
                        card['name'] = standard

        # Validate rare features - if too many cards have "autograph", it's likely a false positive
        autograph_count = sum(1 for card in raw_data if 'autograph' in (card.get('features') or ''))
        if autograph_count > 2:
            print(f"Warning: {autograph_count}/9 cards detected as autograph - removing as likely false positive", file=sys.stderr)
            for card in raw_data:
                features = card.get('features', 'none')
                if 'autograph' in features:
                    # Remove autograph from features
                    parts = [f.strip() for f in features.split(',') if f.strip() and 'autograph' not in f.strip()]
                    card['features'] = ','.join(parts) if parts else 'none'

        report("finalizing", "Creating card objects")

        # Create GridCard objects
        grid_cards = []
        for i, card_data in enumerate(raw_data):
            # Calculate real confidence based on historical accuracy
            confidence = correction_tracker.get_confidence_score(
                card_data,
                original_gpt_data[i]
            )

            grid_card = GridCard(
                position=i,
                row=i // 3,
                col=i % 3,
                data=card_data,
                confidence=confidence
            )
            grid_cards.append(grid_card)

        print(f"Extraction completed: {len(grid_cards)} cards processed", file=sys.stderr)
        return grid_cards, raw_data

    def _apply_validation_rules(self, card: Dict) -> Dict:
        """Apply rule-based validation to fix known error patterns.

        Rules applied:
        1. Card set cleanup: Remove redundant year+brand patterns
        2. Team name completion: Add city prefix from learned corrections
        3. Condition confidence marker: Flag suspicious vintage condition assessments
        4. Copyright year validation: Flag unlikely year values

        Returns dict with corrections to apply (updated fields only).
        """
        corrections = {}

        # Rule 1: Card Set Cleanup
        # Pattern: "{year} {brand}" should be "n/a" for base sets
        card_set = (card.get('card_set') or '').strip()
        brand = (card.get('brand') or '').strip()
        year = (card.get('copyright_year') or '').strip()

        if card_set and brand and year:
            # Check if card_set is just "{year} {brand}"
            if card_set == f"{year} {brand}":
                corrections['card_set'] = 'n/a'
                card['_card_set_autocorrected'] = True

        # Rule 2: Team Name Completion
        # Use learned corrections to add city prefixes or team mascots
        team = (card.get('team') or '').strip().lower()
        if team and team not in ('n/a', 'unknown', 'none', 'multiple'):
            # Team mascot to full name (mascot only -> city + mascot)
            team_completions = {
                'brewers': 'milwaukee brewers',
                'indians': 'cleveland indians',
                'guardians': 'cleveland guardians',
                'padres': 'san diego padres',
                'rangers': 'texas rangers',
                'red sox': 'boston red sox',
                'mets': 'new york mets',
                'reds': 'cincinnati reds',
                'cubs': 'chicago cubs',
                'white sox': 'chicago white sox',
                'yankees': 'new york yankees',
                'dodgers': 'los angeles dodgers',
                'giants': 'san francisco giants',
                'athletics': 'oakland athletics',
                "a's": 'oakland athletics',
                'orioles': 'baltimore orioles',
                'angels': 'los angeles angels',
                'astros': 'houston astros',
                'braves': 'atlanta braves',
                'cardinals': 'st. louis cardinals',
                'phillies': 'philadelphia phillies',
                'pirates': 'pittsburgh pirates',
                'royals': 'kansas city royals',
                'tigers': 'detroit tigers',
                'twins': 'minnesota twins',
                'mariners': 'seattle mariners',
                'blue jays': 'toronto blue jays',
                'rays': 'tampa bay rays',
                'marlins': 'miami marlins',
                'diamondbacks': 'arizona diamondbacks',
                'rockies': 'colorado rockies',
                'nationals': 'washington nationals',
                'expos': 'montreal expos',
            }

            # City-only to full name (for cities with only one team)
            city_completions = {
                'boston': 'boston red sox',
                'cleveland': 'cleveland guardians',
                'cincinnati': 'cincinnati reds',
                'detroit': 'detroit tigers',
                'houston': 'houston astros',
                'kansas city': 'kansas city royals',
                'milwaukee': 'milwaukee brewers',
                'minnesota': 'minnesota twins',
                'oakland': 'oakland athletics',
                'philadelphia': 'philadelphia phillies',
                'pittsburgh': 'pittsburgh pirates',
                'san diego': 'san diego padres',
                'seattle': 'seattle mariners',
                'st. louis': 'st. louis cardinals',
                'st louis': 'st. louis cardinals',
                'texas': 'texas rangers',
                'toronto': 'toronto blue jays',
                'tampa bay': 'tampa bay rays',
                'miami': 'miami marlins',
                'arizona': 'arizona diamondbacks',
                'colorado': 'colorado rockies',
                'washington': 'washington nationals',
                'montreal': 'montreal expos',
                'atlanta': 'atlanta braves',
                'baltimore': 'baltimore orioles',
            }

            if team in team_completions:
                corrections['team'] = team_completions[team]
                card['_team_autocompleted'] = True
            elif team in city_completions:
                corrections['team'] = city_completions[team]
                card['_team_autocompleted'] = True

        # Rule 3: Condition - no automatic adjustments
        # Vintage cards should be graded relative to their age, not penalized

        # Rule 4: Copyright Year Cross-Validation
        # Flag years that seem unlikely (too far from brand patterns)
        try:
            year_int = int(year) if year and year.isdigit() else None
            if year_int:
                # Flag suspiciously old or new years
                if year_int < 1950 or year_int > 2025:
                    card['_year_suspicious'] = True
        except (ValueError, AttributeError):
            pass

        return corrections

    def _get_feature_examples(self) -> List[str]:
        """Get example features from the database to help GPT understand
        feature types."""
        try:
            from .database import get_session
            from .models import Card

            with get_session() as session:
                # Get all features and split them
                features_raw = session.query(Card.features).filter(
                    Card.features.isnot(None)
                ).limit(100).all()

                all_features = set()
                for (features_str,) in features_raw:
                    if features_str and features_str != 'none':
                        for feature in features_str.split(','):
                            all_features.add(feature.strip())

                # Return up to 10 most common examples
                return sorted(list(all_features))[:10]
        except Exception as e:
            print(f"Could not fetch feature examples: {e}", file=sys.stderr)
            return []

    def _create_default_card(self, position: int) -> Dict:
        """Create a default card entry for missing data."""
        return {
            "grid_position": position,
            "name": "unidentified",
            "sport": "baseball",
            "brand": "unknown",
            "number": None,
            "copyright_year": "unknown",
            "team": "unknown",
            "card_set": "n/a",
            "condition": "very_good",
            "is_player_card": True,
            "features": "none",
            "notes": "none"
        }


def save_grid_cards_to_verification(
    grid_cards: List[GridCard],
    out_dir: Path,
    filename_stem: str = None,
    include_tcdb_verification: bool = False,  # Ignored
    save_cropped_backs: bool = True,
    original_image_path: str = None
):
    """Save grid cards to verification with cropped back images."""
    out_dir.mkdir(exist_ok=True)

    # Convert GridCard objects to dicts for JSON serialization
    cards_data = []
    for grid_card in grid_cards:
        card_dict = grid_card.data.copy()

        # Add grid metadata
        meta = {
            'position': grid_card.position,
            'row': grid_card.row,
            'col': grid_card.col,
            'confidence': grid_card.confidence
        }

        # Add cropped back path for UI
        if filename_stem is not None:
            meta['cropped_back_alias'] = f"pending_verification_cropped_backs/{filename_stem}_pos{grid_card.position}.png"

        card_dict['_grid_metadata'] = meta
        cards_data.append(card_dict)

    # Save cropped individual back images (needed for UI verification)
    cropped_dir = out_dir / "pending_verification_cropped_backs"
    if save_cropped_backs and original_image_path:
        try:
            cropped_dir.mkdir(exist_ok=True)
            _extract_and_save_individual_backs(original_image_path, grid_cards, cropped_dir, filename_stem)
        except Exception as e:
            print(f"Failed to save cropped backs: {e}", file=sys.stderr)

    # Save JSON file
    filename = out_dir / (
        f"{filename_stem}.json" if filename_stem else f"grid_{len(cards_data)}_cards.json"
    )

    with open(filename, "w") as f:
        json.dump(cards_data, f, indent=2)

    print(f"Saved {len(cards_data)} grid cards to {filename}")
    return filename.stem


def _extract_and_save_individual_backs(image_path: str, grid_cards: List[GridCard],
                                     output_dir: Path, filename_stem: str):
    """Extract and save individual card backs from 3x3 grid."""
    try:
        # Load original image
        img = Image.open(image_path)
        width, height = img.size

        # Calculate grid dimensions (3x3)
        card_width = width // 3
        card_height = height // 3

        # Add padding to avoid overcropping (5% on each side)
        pad_x = int(card_width * 0.05)
        pad_y = int(card_height * 0.05)

        for grid_card in grid_cards:
            # Calculate crop coordinates with padding (undercrop)
            col = grid_card.col
            row = grid_card.row

            left = max(0, col * card_width - pad_x)
            top = max(0, row * card_height - pad_y)
            right = min(width, (col + 1) * card_width + pad_x)
            bottom = min(height, (row + 1) * card_height + pad_y)

            # Crop individual card
            cropped_card = img.crop((left, top, right, bottom))

            # Generate simple filename
            crop_filename = f"{filename_stem}_pos{grid_card.position}.png"

            # Save cropped image
            crop_path = output_dir / crop_filename
            cropped_card.save(crop_path, "PNG")

            print(f"Saved cropped back: {crop_filename}", file=sys.stderr)

    except Exception as e:
        print(f"Error extracting individual backs: {e}", file=sys.stderr)


def reprocess_grid_image(image_path: str) -> List[Dict]:
    """Reprocess a 3x3 grid image with single-pass extraction.

    Args:
        image_path: Path to the grid image file

    Returns:
        List of card dictionaries with grid_metadata
    """
    print(f"Reprocessing grid image: {image_path}", file=sys.stderr)

    # Use GridProcessor to extract cards
    gp = GridProcessor()
    grid_cards, raw_data = gp.process_3x3_grid(image_path)

    # Save cropped back images for UI verification
    img_path = Path(image_path)
    filename_stem = img_path.stem
    cropped_dir = Path("cards/pending_verification/pending_verification_cropped_backs")
    cropped_dir.mkdir(parents=True, exist_ok=True)

    try:
        _extract_and_save_individual_backs(image_path, grid_cards, cropped_dir, filename_stem)
    except Exception as e:
        print(f"Warning: Failed to save cropped backs during reprocessing: {e}", file=sys.stderr)

    # Convert GridCard objects to plain dicts
    cards = []
    for gc in grid_cards:
        card = gc.data.copy() if isinstance(gc.data, dict) else dict(gc.data)
        card.setdefault('grid_position', gc.position)
        card.setdefault('_grid_metadata', {
            "position": gc.position,
            "row": gc.row,
            "col": gc.col,
            "confidence": getattr(gc, 'confidence', 0.0)
        })
        cards.append(card)

    print(f"Reprocessing complete: {len(cards)} cards extracted", file=sys.stderr)
    return cards
