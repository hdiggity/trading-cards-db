from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict

from app.models import Card


VERIFIED_DIR = Path("images/verified")


def _slug(value: str | None) -> str:
    if not value:
        return "na"
    s = str(value).strip().lower()
    # Replace non-alphanum with single underscore, collapse repeats
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "na"


def card_unique_components(card: Card) -> Dict[str, str]:
    return {
        "sport": _slug(getattr(card, "sport", None)),
        "name": _slug(getattr(card, "name", None)),
        "brand": _slug(getattr(card, "brand", None)),
        "year": _slug(getattr(card, "copyright_year", None)),
        "number": _slug(getattr(card, "number", None)),
    }


def per_card_filename(card: Card) -> str:
    c = card_unique_components(card)
    # Stable, readable filename based on identity fields (no prefix)
    return f"{c['sport']}__{c['name']}__{c['brand']}__{c['year']}__{c['number']}.json"


def write_per_card_file(card: Card, out_dir: Path | None = None) -> Path:
    """Write a one-element JSON array for this card to verified folder.

    File name is deterministic per unique card identity so it overwrites/updates.
    Returns the path written.
    """
    out = Path(out_dir) if out_dir else VERIFIED_DIR
    out.mkdir(parents=True, exist_ok=True)

    fname = per_card_filename(card)
    path = out / fname

    # Choose a compact, UI-friendly schema
    payload = [{
        "name": getattr(card, "name", None),
        "sport": getattr(card, "sport", None),
        "brand": getattr(card, "brand", None),
        "number": getattr(card, "number", None),
        "copyright_year": getattr(card, "copyright_year", None),
        "team": getattr(card, "team", None),
        "card_set": getattr(card, "card_set", None),
        "condition": getattr(card, "condition", None),
        "features": getattr(card, "features", None),
        "quantity": getattr(card, "quantity", None),
        "value_estimate": getattr(card, "value_estimate", None),
    }]

    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
