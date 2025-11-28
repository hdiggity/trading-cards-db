#!/usr/bin/env python3
"""
Export one JSON file per unique card in the database to images/verified.
Filename is deterministic from (sport,name,brand,year,number).
Re-runnable: files are overwritten with current DB content.
"""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from app.database import get_session
from app.models import Card
from app.per_card_export import write_per_card_file, card_unique_components


def main() -> int:
    out = Path("images/verified")
    out.mkdir(parents=True, exist_ok=True)

    # Track seen keys to ensure uniqueness
    seen: set[tuple] = set()
    count = 0
    with get_session() as session:
        rows = session.query(Card).all()
        for card in rows:
            comps = card_unique_components(card)
            key = (comps["sport"], comps["name"], comps["brand"], comps["year"], comps["number"])
            if key in seen:
                continue
            seen.add(key)
            write_per_card_file(card, out)
            count += 1

    print(f"Exported {count} unique card file(s) to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

