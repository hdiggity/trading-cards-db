"""
Simplified single-pass GPT Vision extraction for 3x3 grid card backs
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass
from PIL import Image
import base64
from io import BytesIO
from pillow_heif import register_heif_opener

from .utils import client
import os

register_heif_opener()
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

@dataclass
class GridCard:
    """Represents a card extracted from a grid with position info"""
    position: int  # 0-8 for 3x3 grid (top-left to bottom-right)
    row: int       # 0-2
    col: int       # 0-2
    data: Dict[str, Any]
    confidence: float = 0.0


class GridProcessor:
    """Simple single-pass GPT Vision processor for 3x3 grid card backs"""

    def process_3x3_grid(self, image_path: str, front_images_dir: Path = None) -> Tuple[List[GridCard], List[Dict]]:
        """
        Process a 3x3 grid of card backs with single-pass GPT Vision extraction

        Args:
            image_path: Path to the 3x3 grid image
            front_images_dir: Ignored (no front matching)

        Returns: (grid_cards, raw_data)
        """
        print(f"Processing 3x3 grid with single-pass GPT Vision: {image_path}", file=sys.stderr)

        # Load and encode image
        img = Image.open(image_path)
        max_size = 2400
        if max(img.size) > max_size:
            ratio = max_size / max(img.size)
            img = img.resize((int(img.size[0] * ratio), int(img.size[1] * ratio)), Image.LANCZOS)
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=95)
        img_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

        # Single-pass extraction prompt
        prompt = """This is a 3x3 grid of baseball card BACKS (9 cards total, arranged left-to-right, top-to-bottom).

Extract data for each card (position 0-8) in this order:

1. name: Player's full name (typically in ALL CAPS or bold near top)
2. number: Card number (look for # symbol)
3. team: Team name
4. copyright_year: Copyright year (© symbol, usually at bottom)
5. brand: Card brand (usually Topps)
6. card_set: Card set name (use 'n/a' if not a special subset)
7. sport: Sport type (baseball, basketball, etc.)
8. condition: Condition assessment (mint, near_mint, excellent, very_good, good, fair, poor, damaged)
9. is_player_card: true/false
10. features: Special features or 'none'

Return ONLY a JSON array with exactly 9 objects:
[{
  "grid_position": 0,
  "name": "PLAYER NAME",
  "number": "123",
  "team": "team name",
  "copyright_year": "1984",
  "brand": "topps",
  "card_set": "n/a",
  "sport": "baseball",
  "condition": "very_good",
  "is_player_card": true,
  "features": "none"
}, ...]"""

        # Call GPT Vision API
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are a trading card expert. Extract data accurately from card backs."},
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                ]}
            ],
            max_tokens=2000,
            temperature=0.1
        )

        result_text = response.choices[0].message.content.strip()

        # Clean markdown if present
        if result_text.startswith("```"):
            result_text = result_text.split("```")[1]
            if result_text.startswith("json"):
                result_text = result_text[4:]
            result_text = result_text.strip()
        if result_text.endswith("```"):
            result_text = result_text[:-3].strip()

        raw_data = json.loads(result_text)

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

        # Lowercase field values for consistency
        for card in raw_data:
            for key in ("name", "sport", "brand", "team", "card_set", "condition"):
                if key in card and card[key] is not None and isinstance(card[key], str):
                    card[key] = card[key].lower().strip()

        # Create GridCard objects
        grid_cards = []
        for i, card_data in enumerate(raw_data):
            grid_card = GridCard(
                position=i,
                row=i // 3,
                col=i % 3,
                data=card_data,
                confidence=0.8  # Fixed confidence for single-pass
            )
            grid_cards.append(grid_card)

        print(f"Extraction completed: {len(grid_cards)} cards processed", file=sys.stderr)
        return grid_cards, raw_data

    def _create_default_card(self, position: int) -> Dict:
        """Create a default card entry for missing data"""
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
            "features": "none"
        }


def save_grid_cards_to_verification(
    grid_cards: List[GridCard],
    out_dir: Path,
    filename_stem: str = None,
    include_tcdb_verification: bool = False,  # Ignored
    save_cropped_backs: bool = True,
    original_image_path: str = None
):
    """Save grid cards to verification with cropped back images"""
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
            _extract_and_save_individual_backs(original_image_path, grid_cards, cropped_dir, filename_stem)
        except Exception as e:
            print(f"Failed to save cropped backs: {e}", file=sys.stderr)

    print(f"Saved {len(cards_data)} grid cards to {filename}")
    return filename.stem


def _extract_and_save_individual_backs(image_path: str, grid_cards: List[GridCard],
                                     output_dir: Path, filename_stem: str):
    """Extract and save individual card backs from 3x3 grid"""
    try:
        # Load original image
        img = Image.open(image_path)
        width, height = img.size

        # Calculate grid dimensions (3x3)
        card_width = width // 3
        card_height = height // 3

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
    """Reprocess a 3x3 grid image with single-pass extraction

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
            "confidence": getattr(gc, 'confidence', 0.8)
        })
        cards.append(card)

    print(f"Reprocessing complete: {len(cards)} cards extracted", file=sys.stderr)
    return cards
