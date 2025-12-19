"""
Script to lowercase text fields in pending verification JSON files.
Run this once to fix pending cards that were processed before lowercase enforcement.
"""

import json
import sys
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent.parent.parent
PENDING_DIR = BASE_DIR / "cards" / "pending_verification"

def lowercase_json_files():
    """Lowercase all text fields in pending verification JSON files."""

    if not PENDING_DIR.exists():
        print(f"No pending verification directory found at {PENDING_DIR}")
        return

    text_fields = ['name', 'sport', 'brand', 'team', 'card_set', 'features', 'condition', 'notes']
    json_files = list(PENDING_DIR.glob("*.json"))

    if not json_files:
        print("No pending verification JSON files found.")
        return

    print(f"Processing {len(json_files)} JSON files...")

    for json_file in json_files:
        try:
            with open(json_file, 'r') as f:
                data = json.load(f)

            if not isinstance(data, list):
                print(f"  Skipping {json_file.name} (not a list)")
                continue

            modified = False
            for card in data:
                for field in text_fields:
                    if field in card and isinstance(card[field], str):
                        original = card[field]
                        lowered = original.lower()
                        if lowered != original:
                            card[field] = lowered
                            modified = True
                            print(f"  {json_file.name}: {field} '{original}' -> '{lowered}'")

            if modified:
                with open(json_file, 'w') as f:
                    json.dump(data, f, indent=2)
                print(f"  ✓ Updated {json_file.name}")

        except Exception as e:
            print(f"  ✗ Error processing {json_file.name}: {e}")

    print("\n✓ Migration complete! All pending verification JSON files are now lowercase.")


if __name__ == "__main__":
    try:
        lowercase_json_files()
    except Exception as e:
        print(f"✗ Migration failed: {e}")
        sys.exit(1)
