"""Single-pass GPT Vision extraction for dynamic grid card backs (NxM
grids)."""

import base64
import json
import os
import re
import sys
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

# Shared prompt text for value estimation
VALUE_ESTIMATE_PROMPT = "How much is this card probably worth? Format as $xx.xx (e.g., $1.00, $5.00, $10.00)"

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

@dataclass
class GridDimensions:
    """Container for grid dimensions and calculated properties."""
    rows: int
    cols: int

    @property
    def total_cards(self) -> int:
        return self.rows * self.cols

    @property
    def grid_string(self) -> str:
        return f"{self.rows}x{self.cols}"

    def position_to_row_col(self, position: int) -> Tuple[int, int]:
        """Convert linear position to (row, col)."""
        return (position // self.cols, position % self.cols)

    def row_col_to_position(self, row: int, col: int) -> int:
        """Convert row, col to linear position."""
        return row * self.cols + col

    @classmethod
    def from_string(cls, grid_string: str) -> 'GridDimensions':
        """Parse '3x3' format into GridDimensions."""
        rows, cols = map(int, grid_string.split('x'))
        return cls(rows=rows, cols=cols)


@dataclass
class GridCard:
    """Represents a card extracted from a grid with position info."""
    position: int  # Position in grid (top-left to bottom-right)
    row: int       # Row index
    col: int       # Column index
    data: Dict[str, Any]
    confidence: float = 0.0


class GridProcessor:
    """Single-pass GPT Vision processor for dynamic grid card backs."""

    def __init__(self, default_dimensions: GridDimensions = None):
        """Initialize processor with optional default dimensions.

        Args:
            default_dimensions: Default grid dimensions (if None, loads from config)
        """
        if default_dimensions is None:
            from .config import get_config
            config = get_config()
            default_dimensions = GridDimensions(
                rows=config.default_grid_rows,
                cols=config.default_grid_cols
            )
        self.default_dimensions = default_dimensions

    def process_grid(self, image_path: str, grid_dimensions: GridDimensions = None, front_images_dir: Path = None) -> Tuple[List[GridCard], List[Dict]]:
        """Process a grid of card backs with single-pass GPT Vision extraction.

        Args:
            image_path: Path to the grid image
            grid_dimensions: Optional grid dimensions (defaults to constructor default)
            front_images_dir: Ignored (no front matching)

        Returns: (grid_cards, raw_data)
        """
        if grid_dimensions is None:
            grid_dimensions = self.default_dimensions

        print(f"Processing {grid_dimensions.grid_string} grid with single-pass GPT Vision: {image_path}", file=sys.stderr)

        # Load and encode image
        img = Image.open(image_path)
        max_size = 4000
        if max(img.size) > max_size:
            ratio = max_size / max(img.size)
            img = img.resize((int(img.size[0] * ratio), int(img.size[1] * ratio)), Image.LANCZOS)
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=95)
        img_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

        # Build dynamic prompt and schema based on grid dimensions
        prompt = self._build_extraction_prompt(grid_dimensions)
        response_schema = self._build_response_schema(grid_dimensions)

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

        # Ensure exactly the expected number of cards
        expected_count = grid_dimensions.total_cards
        if len(raw_data) != expected_count:
            print(f"Warning: Expected {expected_count} cards, got {len(raw_data)}", file=sys.stderr)
            while len(raw_data) < expected_count:
                raw_data.append(self._create_default_card(len(raw_data)))
            raw_data = raw_data[:expected_count]

        # Add grid metadata with dynamic position calculation
        for i, card in enumerate(raw_data):
            row, col = grid_dimensions.position_to_row_col(i)
            card.setdefault('grid_position', i)
            card.setdefault('_grid_metadata', {
                "position": i,
                "row": row,
                "col": col,
                "grid_dimensions": grid_dimensions.grid_string
            })

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
                'sport': card.get('sport')
            }

        # Lowercase field values for consistency and normalize prices
        for card in raw_data:
            for key in ("name", "sport", "brand", "team", "card_set", "condition", "notes"):
                if key in card and card[key] is not None and isinstance(card[key], str):
                    card[key] = card[key].lower().strip()
            # Normalize price estimate
            if 'value_estimate' in card:
                card['value_estimate'] = normalize_price(card['value_estimate'])

        # Store original GPT data for confidence calculation
        original_gpt_data = [card.copy() for card in raw_data]

        # Apply learned corrections from previous manual fixes
        for i, card in enumerate(raw_data):
            raw_data[i] = correction_tracker.apply_learned_corrections(card)

        # Apply learned condition predictions
        for i, card in enumerate(raw_data):
            predicted_condition = correction_tracker.predict_condition(card)
            if predicted_condition:
                raw_data[i]['condition'] = predicted_condition
                raw_data[i]['_condition_predicted'] = True

        # Create GridCard objects with dynamic dimensions
        grid_cards = []
        for i, card_data in enumerate(raw_data):
            row, col = grid_dimensions.position_to_row_col(i)

            # Calculate real confidence based on historical accuracy
            confidence = correction_tracker.get_confidence_score(
                card_data,
                original_gpt_data[i]
            )

            grid_card = GridCard(
                position=i,
                row=row,
                col=col,
                data=card_data,
                confidence=confidence
            )
            grid_cards.append(grid_card)

        print(f"Extraction completed: {len(grid_cards)} cards processed", file=sys.stderr)
        return grid_cards, raw_data

    def _build_extraction_prompt(self, grid_dimensions: GridDimensions) -> str:
        """Build dynamic extraction prompt based on grid dimensions."""
        # Get example features from database
        feature_examples = self._get_feature_examples()
        feature_examples_text = ""
        if feature_examples:
            feature_examples_text = f" Examples from database: {', '.join(feature_examples)}."

        total = grid_dimensions.total_cards
        max_pos = total - 1

        prompt = f"""This is a {grid_dimensions.grid_string} grid of baseball card BACKS ({total} cards total, arranged left-to-right, top-to-bottom).

Extract data for each card (position 0-{max_pos}) in this order:

1. name: Player's full name in all lowercase
2. number: Card number
3. team: Team name (including city)
4. copyright_year: Copyright year, usually at bottom
5. brand: Card brand (Topps, etc.)
6. card_set: ONLY named special subsets like "Traded", etc. Use 'n/a' for regular base cards. DO NOT use descriptive text about card back type (Mexican, Venezuelan, OPC, chewing gum, etc.)
7. sport: Sport type (baseball, basketball, etc.)
8. condition: Physical condition of EACH INDIVIDUAL CARD. Assess each card separately - they can have different conditions. Look for: corners (sharp vs rounded/damaged), edges (clean vs worn/chipped), surface (clean vs scratched/stained/creased), centering (well-centered vs off-center). Use: mint (perfect), near_mint (minor wear), excellent (light wear on corners/edges), very_good (moderate wear, no creases), good (heavy wear or minor creases), fair (major creases/stains), poor (severe damage), damaged (torn/water damaged)
9. is_player_card: true/false
10. features: ONLY special features like "rookie", "error", "autograph", "serial numbered", "memorabilia", etc.{feature_examples_text} Use 'none' if no special features.
11. notes: ONLY unique card-specific facts like print variations, manufacturing errors, or rarity information (e.g., "short print", "error card - misspelled name", "photo variation"). DO NOT include condition details (that goes in condition field), player stats, or achievements. Use 'none' if no unique aspects.
12. value_estimate: {VALUE_ESTIMATE_PROMPT}

IMPORTANT: Each card can have a DIFFERENT condition - examine each one individually for wear, damage, creasing, and surface issues.

Return structured JSON with a "cards" array containing exactly {total} card objects (position 0-{max_pos})."""

        return prompt

    def _build_response_schema(self, grid_dimensions: GridDimensions) -> dict:
        """Build dynamic JSON schema expecting exact number of cards."""
        total = grid_dimensions.total_cards

        return {
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
                            },
                            "minItems": total,
                            "maxItems": total
                        }
                    },
                    "required": ["cards"],
                    "additionalProperties": False
                }
            }
        }

    def process_3x3_grid(self, image_path: str, front_images_dir: Path = None) -> Tuple[List[GridCard], List[Dict]]:
        """Backward compatibility wrapper for 3x3 grids."""
        return self.process_grid(
            image_path,
            GridDimensions(rows=3, cols=3),
            front_images_dir
        )

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

    # Save JSON file
    filename = out_dir / (
        f"{filename_stem}.json" if filename_stem else f"grid_{len(cards_data)}_cards.json"
    )

    with open(filename, "w") as f:
        json.dump(cards_data, f, indent=2)

    # Save cropped individual back images
    if save_cropped_backs and original_image_path:
        try:
            cropped_dir = out_dir / "pending_verification_cropped_backs"
            cropped_dir.mkdir(exist_ok=True)

            # Extract grid dimensions from first card's metadata
            grid_dim_str = grid_cards[0].data.get('_grid_metadata', {}).get('grid_dimensions', '3x3')
            grid_dims = GridDimensions.from_string(grid_dim_str)

            _extract_and_save_individual_backs(original_image_path, grid_cards, cropped_dir, filename_stem, grid_dims)
        except Exception as e:
            print(f"Failed to save cropped backs: {e}", file=sys.stderr)

    print(f"Saved {len(cards_data)} grid cards to {filename}")
    return filename.stem


def _extract_and_save_individual_backs(image_path: str, grid_cards: List[GridCard],
                                     output_dir: Path, filename_stem: str,
                                     grid_dimensions: GridDimensions):
    """Extract and save individual card backs from grid with dynamic
    dimensions."""
    try:
        # Load original image
        img = Image.open(image_path)
        width, height = img.size

        # Calculate card dimensions based on grid
        card_width = width // grid_dimensions.cols
        card_height = height // grid_dimensions.rows

        for grid_card in grid_cards:
            # Calculate crop coordinates
            col = grid_card.col
            row = grid_card.row

            left = col * card_width
            top = row * card_height
            right = left + card_width
            bottom = top + card_height

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
