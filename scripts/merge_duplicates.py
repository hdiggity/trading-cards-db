#!/usr/bin/env python3
"""Interactive script to merge duplicate cards identified after canonical name
migration.

Usage:
    python scripts/merge_duplicates.py [--auto-merge] [--dry-run]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.database import DB_PATH, get_session
from app.db_backup import backup_database


def merge_duplicates(auto_merge=False, dry_run=False):
    """Merge duplicate cards based on canonical names.

    Strategy:
    - Keep card with most CardComplete records
    - Reassign all CardComplete records to kept card
    - Delete duplicate card entries
    """

    # Load duplicate report
    report_path = Path("logs/duplicate_analysis.json")
    if not report_path.exists():
        print("ERROR: No duplicate report found. Run migrate_canonical_names.py first.")
        sys.exit(1)

    with open(report_path) as f:
        duplicates = json.load(f)

    if not duplicates:
        print("No duplicates to merge")
        return

    print(f"Found {len(duplicates)} duplicate groups to review\n")

    # Backup database
    if not dry_run:
        print("Creating database backup...")
        backup_path = backup_database(str(DB_PATH), "backups/pre_merge")
        print(f"Backup created: {backup_path}\n")

    merged_count = 0
    skipped_count = 0

    for i, dup_group in enumerate(duplicates):
        card_ids = [int(x) for x in dup_group['card_ids'].split(',')]

        print(f"\n[{i+1}/{len(duplicates)}] Duplicate group:")
        print(f"  Canonical: {dup_group['canonical_name']}")
        print(f"  Original names: {dup_group['original_names']}")
        print(f"  Cards: {len(card_ids)}")

        if not auto_merge:
            choice = input("  Merge this group? [y/n/q]: ").lower()
            if choice == 'q':
                break
            if choice != 'y':
                skipped_count += 1
                continue

        # Merge logic
        if not dry_run:
            with get_session() as session:
                # Get all card records
                placeholders = ','.join(f':id{i}' for i in range(len(card_ids)))
                params = {f'id{i}': cid for i, cid in enumerate(card_ids)}
                cards = session.execute(
                    text(f"SELECT * FROM cards WHERE id IN ({placeholders})"),
                    params
                ).fetchall()

                if not cards:
                    print(f"  ERROR: Could not find cards with IDs {card_ids}")
                    continue

                # Find card with most complete records (highest quantity)
                card_quantities = {}
                for card in cards:
                    card_id = card[0]  # id is first column
                    quantity = card[13]  # quantity column
                    card_quantities[card_id] = quantity

                keep_id = max(card_quantities, key=card_quantities.get)
                delete_ids = [cid for cid in card_ids if cid != keep_id]

                print(f"  Keeping card ID {keep_id} (quantity: {card_quantities[keep_id]})")
                print(f"  Deleting card IDs: {delete_ids}")

                # Reassign CardComplete records
                for del_id in delete_ids:
                    session.execute(
                        text("UPDATE cards_complete SET card_id = :keep_id WHERE card_id = :del_id"),
                        {"keep_id": keep_id, "del_id": del_id}
                    )

                # Delete duplicate card entries
                del_placeholders = ','.join(f':del_id{i}' for i in range(len(delete_ids)))
                del_params = {f'del_id{i}': did for i, did in enumerate(delete_ids)}
                session.execute(
                    text(f"DELETE FROM cards WHERE id IN ({del_placeholders})"),
                    del_params
                )

                # Update quantity on kept card
                session.execute(
                    text("UPDATE cards SET quantity = (SELECT COUNT(*) FROM cards_complete WHERE card_id = :keep_id) WHERE id = :keep_id2"),
                    {"keep_id": keep_id, "keep_id2": keep_id}
                )

                session.commit()
                print(f"  ✓ Merged {len(delete_ids)} duplicates into card {keep_id}")
                merged_count += 1
        else:
            print(f"  [DRY RUN] Would merge {len(card_ids) - 1} duplicates")
            merged_count += 1

    print(f"\n{'DRY RUN ' if dry_run else ''}COMPLETE:")
    print(f"  Merged: {merged_count}")
    print(f"  Skipped: {skipped_count}")

    if not dry_run and merged_count > 0:
        print("\nNOTE: You may want to run a VACUUM on the database to reclaim space:")
        print(f"  sqlite3 {DB_PATH} 'VACUUM;'")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--auto-merge', action='store_true', help='Merge without prompts')
    parser.add_argument('--dry-run', action='store_true', help='Preview without changes')

    args = parser.parse_args()
    merge_duplicates(auto_merge=args.auto_merge, dry_run=args.dry_run)
