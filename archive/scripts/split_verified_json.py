#!/usr/bin/env python3
"""
Split existing verified grouped JSON files into one file per card.

Targets both `images/verified` and `images/verified_images` directories.
For a grouped file named `<base>.json`, this creates `<base>__cN.json`
containing a one-element array for each card N. Existing per-card files
are left untouched.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def split_grouped_json(dir_path: Path) -> int:
    if not dir_path.exists():
        return 0
    count = 0
    for jf in dir_path.glob("*.json"):
        # Skip per-card files
        if "__c" in jf.stem:
            continue
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
        except Exception:
            continue

        if not isinstance(data, list) or not data:
            # Not a grouped list; nothing to split
            continue

        base = jf.stem
        for idx, card in enumerate(data, start=1):
            per = dir_path / f"{base}__c{idx}.json"
            if per.exists():
                continue
            try:
                per.write_text(json.dumps([card], indent=2), encoding="utf-8")
                count += 1
            except Exception:
                # best-effort; keep going
                pass
    return count


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    dirs = [root / "images" / "verified", root / "images" / "verified_images"]
    total = 0
    for d in dirs:
        total += split_grouped_json(d)
    print(f"Created {total} per-card JSON file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

