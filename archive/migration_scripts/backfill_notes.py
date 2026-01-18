"""Backfill notes field for all cards in the database using GPT-5.2 Vision.

This script analyzes each card's back image and generates notes about
special characteristics like rookie status, rarity, print variations,
and unique features.
"""

import base64
import os
import sys
from io import BytesIO
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import CardComplete
from app.utils import client

load_dotenv()

PROJECT_ROOT = Path(__file__).parent
DB_PATH = PROJECT_ROOT / "cards" / "verified" / "trading_cards.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"
CROPPED_BACKS_DIR = PROJECT_ROOT / "cards" / "verified" / "verified_cropped_backs"

MODEL = os.getenv("OPENAI_MODEL", "gpt-5.2")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)


def encode_image(image_path):
    """Encode image to base64 for GPT Vision API."""
    img = Image.open(image_path)
    max_size = 2000
    if max(img.size) > max_size:
        ratio = max_size / max(img.size)
        img = img.resize(
            (int(img.size[0] * ratio), int(img.size[1] * ratio)), Image.LANCZOS
        )
    buffer = BytesIO()
    img.save(buffer, format="PNG", quality=95)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def generate_notes_for_card(card_data, image_path):
    """Generate notes about special characteristics of a card using GPT Vision.

    Args:
        card_data: Dict with card fields (name, brand, number, copyright_year, etc.)
        image_path: Path to the cropped card back image

    Returns:
        String with notes about the card, or None if nothing special
    """
    try:
        img_b64 = encode_image(image_path)
    except Exception as e:
        print(f"Error encoding image {image_path}: {e}", file=sys.stderr)
        return None

    prompt = f"""You are analyzing the back of a baseball card to identify special characteristics.

Card Information:
- Name: {card_data.get('name', 'Unknown')}
- Brand: {card_data.get('brand', 'Unknown')}
- Card Number: {card_data.get('number', 'Unknown')}
- Year: {card_data.get('copyright_year', 'Unknown')}
- Team: {card_data.get('team', 'Unknown')}
- Card Set: {card_data.get('card_set', 'n/a')}

Analyze this card back image and identify any special characteristics that make this card notable or valuable. Focus on:

1. Rookie Card Status: Is this a rookie card? Look for "ROOKIE" text, RC designation, or first-year indicators
2. Print Variations: Is this a special print run? (e.g., OPC/O-Pee-Chee, Venezuelan back, Mexican back, test issue, promotional)
3. Rarity Indicators: Short print, limited edition, special production run, scarcity information
4. Manufacturing Details: Error cards (misspellings, wrong stats, photo variations), printing anomalies
5. Historical Significance: Notable subsets, commemorative issues, special series

Provide a concise note (1-2 sentences maximum) about what makes this card special or unique. If there are no special characteristics beyond being a standard base card, return "none".

Do NOT include:
- General condition assessment (that's in a separate field)
- Player statistics or career achievements
- Generic descriptions like "standard base card back"

Return ONLY the note text, nothing else. Be specific and factual."""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are a trading card expert specializing in identifying rare and notable card variations.",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                        },
                    ],
                },
            ],
            max_completion_tokens=200,
            temperature=0.1,
        )

        notes = response.choices[0].message.content.strip()

        # Normalize empty responses
        if notes.lower() in ["none", "n/a", "no special characteristics", ""]:
            return "none"

        return notes

    except Exception as e:
        print(f"Error calling GPT API for card {card_data.get('name')}: {e}", file=sys.stderr)
        return None


def backfill_notes(skip_existing=True, limit=None):
    """Backfill notes for all cards in the database.

    Args:
        skip_existing: If True, skip cards that already have notes
        limit: Optional limit on number of cards to process (for testing)
    """
    session = SessionLocal()

    try:
        query = session.query(CardComplete)

        if skip_existing:
            query = query.filter(
                (CardComplete.notes is None) |
                (CardComplete.notes == "") |
                (CardComplete.notes == "none")
            )

        cards = query.all()
        total_cards = len(cards)

        if limit:
            cards = cards[:limit]
            print(f"Processing {len(cards)} of {total_cards} cards (limit: {limit})")
        else:
            print(f"Processing {total_cards} cards")

        processed = 0
        updated = 0
        skipped = 0
        errors = 0

        for card in cards:
            processed += 1

            if not card.cropped_back_file:
                print(f"[{processed}/{len(cards)}] Skipping {card.name} - no cropped back file", file=sys.stderr)
                skipped += 1
                continue

            image_path = CROPPED_BACKS_DIR / card.cropped_back_file

            if not image_path.exists():
                print(f"[{processed}/{len(cards)}] Skipping {card.name} - image not found: {image_path}", file=sys.stderr)
                skipped += 1
                continue

            print(f"[{processed}/{len(cards)}] Processing {card.name} ({card.brand} #{card.number})...", end=" ")

            card_data = {
                "name": card.name,
                "brand": card.brand,
                "number": card.number,
                "copyright_year": card.copyright_year,
                "team": card.team,
                "card_set": card.card_set,
            }

            notes = generate_notes_for_card(card_data, image_path)

            if notes is None:
                print("ERROR")
                errors += 1
                continue

            card.notes = notes
            session.commit()

            if notes == "none":
                print("no special characteristics")
            else:
                print(f"updated: {notes[:60]}{'...' if len(notes) > 60 else ''}")

            updated += 1

        print("\nBackfill complete!")
        print(f"Total processed: {processed}")
        print(f"Updated: {updated}")
        print(f"Skipped: {skipped}")
        print(f"Errors: {errors}")

    finally:
        session.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Backfill notes for trading cards")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all cards, including those with existing notes",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of cards to process (for testing)",
    )

    args = parser.parse_args()

    skip_existing = not args.all

    if args.all:
        print("Processing ALL cards (will overwrite existing notes)")
    else:
        print("Processing only cards without notes")

    backfill_notes(skip_existing=skip_existing, limit=args.limit)
