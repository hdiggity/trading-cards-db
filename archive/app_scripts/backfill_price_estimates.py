"""
Backfill value_estimate ("price estimate") for existing cards.

Strategy:
- If a card has last_price, set value_estimate to "$<last_price>" formatted.
- Else derive a simple heuristic based on features/condition/era.

This script is conservative and offline (no API calls).
Run:
  python -m app.scripts.backfill_price_estimates [--dry-run]
"""

from __future__ import annotations

import argparse
from typing import Optional

from app.database import get_session, engine
from app.models import Card
import os
from app.value_estimator import add_value_estimation


def fmt_price(value: Optional[float]) -> Optional[str]:
    if value is None:
        return None
    try:
        return f"${float(value):.2f}"
    except Exception:
        return None


def heuristic_estimate(card: Card) -> str:
    """Very simple heuristic when no last_price is available.
    Returns a single conservative value like "$1".
    """
    features = (card.features or "").lower()
    condition = (card.condition or "").lower().replace("_", " ")
    year = None
    try:
        year = int(str(card.copyright_year)) if card.copyright_year else None
    except Exception:
        year = None

    # Base value - most common cards are worth very little
    value = 1

    if "autograph" in features:
        value = 25
    elif "rookie" in features:
        value = 3
    elif "hall of fame" in features or "hof" in features:
        value = 2

    # Vintage bump (pre-1980)
    if year and year <= 1979:
        value = max(value, 2)

    # Condition adjustment
    if condition in {"poor", "fair"}:
        value = max(1, int(value * 0.5))
    elif condition in {"near mint", "mint", "gem mint"}:
        value = int(value * 1.5)

    return f"${value}"


def backfill(dry_run: bool = False) -> dict:
    updated, skipped, total = 0, 0, 0
    # Ensure column exists (SQLite simple migration)
    with engine.connect() as conn:
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(cards)").fetchall()]
        if "value_estimate" not in cols:
            conn.exec_driver_sql("ALTER TABLE cards ADD COLUMN value_estimate VARCHAR")
        if "matched_front_file" not in cols:
            conn.exec_driver_sql("ALTER TABLE cards ADD COLUMN matched_front_file VARCHAR")
        if "notes" not in cols:
            conn.exec_driver_sql("ALTER TABLE cards ADD COLUMN notes VARCHAR")
    with get_session() as session:
        cards = session.query(Card).all()
        total = len(cards)
        use_gpt = os.getenv("VALUE_ESTIMATE_MODE", "heuristic").lower() == "gpt"
        for card in cards:
            if card.value_estimate and str(card.value_estimate).strip():
                skipped += 1
                continue

            if use_gpt:
                # Use the same function as extraction for consistency
                updated = add_value_estimation({
                    'name': card.name,
                    'sport': card.sport,
                    'brand': card.brand,
                    'number': card.number,
                    'copyright_year': card.copyright_year,
                    'team': card.team,
                    'card_set': card.card_set,
                    'condition': card.condition,
                    'is_player_card': card.is_player_card,
                    'features': card.features,
                })
                card.value_estimate = updated.get('value_estimate')
            else:
                estimate = fmt_price(card.last_price) or heuristic_estimate(card)
                card.value_estimate = estimate
            updated += 1

        if dry_run:
            session.rollback()
        else:
            session.commit()

    return {"updated": updated, "skipped": skipped, "total": total, "dry_run": dry_run}


def main():
    parser = argparse.ArgumentParser(description="Backfill price estimates for cards")
    parser.add_argument("--dry-run", action="store_true", help="Do not persist changes")
    args = parser.parse_args()

    result = backfill(dry_run=args.dry_run)
    print(result)


if __name__ == "__main__":
    main()
