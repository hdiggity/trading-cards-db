"""
Simple price refresh using ChatGPT
"""

import json
import os
import re
import sys
from typing import Optional
from dotenv import load_dotenv
from openai import OpenAI
from sqlalchemy import func
from app.database import get_session
from app.models import Card, CardComplete
from app.grid_processor import VALUE_ESTIMATE_PROMPT, MODEL

load_dotenv()

def normalize_price(price_str):
    """Validate and normalize price to $xx.xx format"""
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

def get_client() -> Optional[OpenAI]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        return OpenAI(api_key=api_key)
    except Exception:
        return None

def refresh_prices(batch_size: int = 25, force_all: bool = False) -> dict:
    client = get_client()
    if not client:
        return {"error": "OPENAI_API_KEY not configured", "updated": 0, "total": 0, "batches": 0}

    updated = 0
    total = 0
    batches = 0

    with get_session() as session:
        if force_all:
            cards = session.query(Card).all()
        else:
            cards = session.query(Card).filter(
                (Card.value_estimate == None) |
                (Card.value_estimate == '') |
                (Card.value_estimate == '$1-5')
            ).all()

        total = len(cards)
        if total == 0:
            return {"updated": 0, "total": 0, "batches": 0}

        for i in range(0, len(cards), batch_size):
            batches += 1
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

            card_summaries = []
            for idx, card in enumerate(cards_data):
                summary = f"{idx}: {card.get('name', 'Unknown')} | {card.get('brand', '?')} {card.get('copyright_year', '?')} #{card.get('number', '?')} | {card.get('team', '?')} | {card.get('condition', '?')}"
                card_summaries.append(summary)

            cards_text = "\n".join(card_summaries)
            prompt = f"""{VALUE_ESTIMATE_PROMPT}

Cards to evaluate:
{cards_text}

Return only a JSON object with index as key and price as value (e.g., {{"0": "$5.00", "1": "$10.00"}})."""

            try:
                response = client.chat.completions.create(
                    model=MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    max_completion_tokens=500,
                    temperature=0.1
                )

                result = response.choices[0].message.content.strip()
                if result.startswith("```json"):
                    result = result[7:]
                if result.startswith("```"):
                    result = result[3:]
                if result.endswith("```"):
                    result = result[:-3]

                estimates = json.loads(result.strip())

                for idx_str, estimate in estimates.items():
                    card = card_map.get(idx_str)
                    if card and estimate:
                        normalized_price = normalize_price(estimate)
                        card.value_estimate = normalized_price

                        # Update all CardComplete records for this card
                        session.query(CardComplete).filter(
                            CardComplete.card_id == card.id
                        ).update({
                            "value_estimate": normalized_price,
                            "last_updated": func.now()
                        }, synchronize_session=False)

                        updated += 1

            except Exception as e:
                print(f"Batch pricing error: {e}", file=sys.stderr)

        session.commit()

    return {"updated": updated, "total": total, "batches": batches}
