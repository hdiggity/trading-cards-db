"""Simple price refresh using ChatGPT."""

import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI
from sqlalchemy import func

from app.database import get_session
from app.grid_processor import MODEL
from app.models import Card, CardComplete

load_dotenv()

# Progress file for UI status tracking
PROGRESS_FILE = Path(__file__).parent.parent.parent / "logs" / "price_refresh_status.json"

def write_progress(data: dict):
    """Write progress to status file for UI polling."""
    try:
        PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
        PROGRESS_FILE.write_text(json.dumps(data, indent=2))
    except Exception:
        pass

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

    # Format as $xx.xx without rounding to common price points
    return f"${val:.2f}"

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
        write_progress({"active": False, "error": "OPENAI_API_KEY not configured"})
        return {"error": "OPENAI_API_KEY not configured", "updated": 0, "total": 0, "batches": 0}

    updated = 0
    total = 0
    batches = 0
    total_batches = 0

    with get_session() as session:
        if force_all:
            cards = session.query(Card).all()
        else:
            cards = session.query(Card).filter(
                (Card.value_estimate is None) |
                (Card.value_estimate == '') |
                (Card.value_estimate == '$1-5')
            ).all()

        total = len(cards)
        if total == 0:
            write_progress({"active": False, "progress": 100, "updated": 0, "total": 0})
            return {"updated": 0, "total": 0, "batches": 0}

        total_batches = (total + batch_size - 1) // batch_size

        # Write initial progress
        write_progress({
            "active": True,
            "progress": 0,
            "current": 0,
            "total": total,
            "currentBatch": 0,
            "totalBatches": total_batches,
            "updated": 0
        })

        for i in range(0, len(cards), batch_size):
            # Check for cancellation
            try:
                if PROGRESS_FILE.exists():
                    status = json.loads(PROGRESS_FILE.read_text())
                    if status.get("cancelled"):
                        write_progress({"active": False, "cancelled": True, "updated": updated, "total": total})
                        return {"updated": updated, "total": total, "batches": batches, "cancelled": True}
            except Exception:
                pass

            batches += 1
            batch = cards[i:i + batch_size]

            # Update progress
            progress = min(99, int((i / total) * 100))
            write_progress({
                "active": True,
                "progress": progress,
                "current": i,
                "total": total,
                "currentBatch": batches,
                "totalBatches": total_batches,
                "updated": updated
            })
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

            # Compact format: idx:name,brand,year,#num,cond
            card_summaries = []
            for idx, card in enumerate(cards_data):
                summary = f"{idx}:{card.get('name', '?')},{card.get('brand', '?')},{card.get('copyright_year', '?')},#{card.get('number', '?')},{card.get('condition', '?')}"
                card_summaries.append(summary)

            cards_text = "\n".join(card_summaries)
            prompt = f"""Price these cards (format: idx:name,brand,year,#num,condition). Return JSON {{idx: "$X.XX"}}

{cards_text}"""

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

    # Write final progress
    write_progress({
        "active": False,
        "progress": 100,
        "current": total,
        "total": total,
        "currentBatch": batches,
        "totalBatches": total_batches,
        "updated": updated
    })

    return {"updated": updated, "total": total, "batches": batches}
