#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
from pathlib import Path

from app.per_card_export import write_per_card_file


ROOT = Path(__file__).resolve().parents[1]
VERIFIED = ROOT / "images" / "verified"
VERIFIED_IMAGES_SUB = VERIFIED / "images"
VERIFIED_IMAGES_OLD = ROOT / "images" / "verified_images"  # legacy location
LEGACY = VERIFIED / "legacy"


def to_obj(card: dict):
    class Obj:
        pass

    o = Obj()
    for k in [
        "name",
        "sport",
        "brand",
        "number",
        "copyright_year",
        "team",
        "card_set",
        "condition",
        "features",
        "quantity",
        "value_estimate",
    ]:
        setattr(o, k, card.get(k))
    return o


def migrate_dir(src: Path) -> int:
    if not src.exists():
        return 0
    count = 0
    for p in src.glob("*.json"):
        text = p.read_text(encoding="utf-8")
        try:
            data = json.loads(text)
        except Exception:
            continue

        if isinstance(data, list) and data:
            # Per-card or grouped
            if "__c" in p.stem and len(data) == 1:
                # Per-card file; re-export to standardized filename (drop 'unique__' prefix if present)
                write_per_card_file(to_obj(data[0]), VERIFIED)
                try:
                    p.unlink()
                except Exception:
                    pass
                count += 1
            else:
                # Grouped: archive to legacy and export each card
                LEGACY.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.move(str(p), str(LEGACY / p.name))
                except Exception:
                    pass
                for card in data:
                    write_per_card_file(to_obj(card), VERIFIED)
                count += len(data)
        else:
            # Not a list; ignore
            pass
    return count


def main() -> int:
    VERIFIED.mkdir(parents=True, exist_ok=True)
    (VERIFIED / "images").mkdir(parents=True, exist_ok=True)
    LEGACY.mkdir(parents=True, exist_ok=True)
    total = migrate_dir(VERIFIED)
    # Migrate from old external verified_images folder
    total += migrate_dir(VERIFIED_IMAGES_OLD)
    # Move any image files (*.heic, *.jpg, etc.) in verified root into subfolder
    for ext in (".heic", ".HEIC", ".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"):
        for p in VERIFIED.glob(f"*{ext}"):
            dest = VERIFIED_IMAGES_SUB / p.name
            try:
                dest.write_bytes(p.read_bytes())
                p.unlink()
            except Exception:
                pass
    # If old verified_images exists and is empty after migration, remove it
    try:
        if VERIFIED_IMAGES_OLD.exists() and not any(VERIFIED_IMAGES_OLD.iterdir()):
            VERIFIED_IMAGES_OLD.rmdir()
    except Exception:
        pass
    print(f"Standardized {total} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
