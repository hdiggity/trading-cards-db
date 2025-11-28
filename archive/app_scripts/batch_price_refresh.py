"""
Token-efficient batch price refresh for trading cards.

Batches multiple cards into a single GPT call to minimize API token usage.
Uses gpt-4o-mini for cost efficiency.

Run:
  python -m app.scripts.batch_price_refresh [--batch-size 25] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

from app.database import get_session, engine
from app.models import Card


load_dotenv()


def get_client() -> Optional[OpenAI]:
    """Get OpenAI client if API key is available."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        return OpenAI(api_key=api_key)
    except Exception:
        return None


def batch_estimate_prices(cards_data: list[dict], client: OpenAI) -> dict:
    """
    Get price estimates for multiple cards in a single API call.
    Returns a dict mapping card index to price estimate.
    """
    if not cards_data:
        return {}

    # Build compact card list for the prompt
    card_summaries = []
    for i, card in enumerate(cards_data):
        summary = f"{i}: {card.get('name', 'Unknown')} | {card.get('brand', '?')} {card.get('copyright_year', '?')} #{card.get('number', '?')} | {card.get('team', '?')} | {card.get('condition', '?')} | features: {card.get('features', 'none')}"
        card_summaries.append(summary)

    cards_text = "\n".join(card_summaries)

    prompt = f"""You are a trading card price appraiser. Give CONSERVATIVE single-number estimates.

Cards to price:
{cards_text}

Return ONLY a JSON object with card index as key and single price as value.
Example: {{"0": "$1", "1": "$3", "2": "$15"}}

IMPORTANT: Most common cards are worth $1-3. Be conservative:
- Common base cards (1980s-2000s): $1
- Minor stars: $2-3
- Hall of Famers base: $3-5
- Rookies of stars: $5-10
- Only true premium cards (autographs, key rookies): $15+"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a professional trading card appraiser. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=500,
            temperature=0.1
        )

        response_text = response.choices[0].message.content.strip()

        # Clean JSON markers
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]

        return json.loads(response_text.strip())

    except Exception as e:
        print(f"Batch pricing error: {e}")
        return {}


def refresh_prices(batch_size: int = 25, dry_run: bool = False, force_all: bool = False) -> dict:
    """
    Refresh price estimates for cards in the database.

    Args:
        batch_size: Number of cards to price in each API call (default 25)
        dry_run: If True, don't persist changes
        force_all: If True, refresh ALL cards even if they have estimates

    Returns:
        Dict with updated/skipped/total counts
    """
    client = get_client()
    if not client:
        return {"error": "OPENAI_API_KEY not configured", "updated": 0, "skipped": 0, "total": 0}

    updated = 0
    skipped = 0
    total = 0
    batches_processed = 0

    with get_session() as session:
        if force_all:
            cards = session.query(Card).all()
        else:
            # Only cards without estimates or with placeholder estimates
            cards = session.query(Card).filter(
                (Card.value_estimate == None) |
                (Card.value_estimate == '') |
                (Card.value_estimate == '$1-5')
            ).all()

        total = len(cards)

        if total == 0:
            return {"updated": 0, "skipped": 0, "total": 0, "batches": 0, "dry_run": dry_run}

        # Process in batches
        for i in range(0, len(cards), batch_size):
            batch = cards[i:i + batch_size]
            cards_data = []
            card_map = {}

            for j, card in enumerate(batch):
                cards_data.append({
                    'name': card.name,
                    'brand': card.brand,
                    'copyright_year': card.copyright_year,
                    'number': card.number,
                    'team': card.team,
                    'condition': card.condition,
                    'features': card.features,
                    'sport': card.sport
                })
                card_map[str(j)] = card

            # Get batch estimates
            estimates = batch_estimate_prices(cards_data, client)
            batches_processed += 1

            # Apply estimates
            for idx_str, estimate in estimates.items():
                card = card_map.get(idx_str)
                if card and estimate:
                    card.value_estimate = estimate
                    updated += 1

            # Cards not in response keep their old value
            for idx_str, card in card_map.items():
                if idx_str not in estimates:
                    skipped += 1

        if dry_run:
            session.rollback()
        else:
            session.commit()

    return {
        "updated": updated,
        "skipped": skipped,
        "total": total,
        "batches": batches_processed,
        "dry_run": dry_run
    }


def main():
    parser = argparse.ArgumentParser(description="Batch refresh price estimates for cards")
    parser.add_argument("--batch-size", type=int, default=25, help="Cards per API call (default 25)")
    parser.add_argument("--dry-run", action="store_true", help="Do not persist changes")
    parser.add_argument("--force-all", action="store_true", help="Refresh all cards, not just missing estimates")
    args = parser.parse_args()

    result = refresh_prices(
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        force_all=args.force_all
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
