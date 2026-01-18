#!/usr/bin/env python3
"""Migration script to add canonical names to existing cards.

Usage:
    python scripts/migrate_canonical_names.py [--dry-run] [--batch-size=50]
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.database import DB_PATH, get_session
from app.db_backup import backup_database
from app.player_canonical import CanonicalNameService


def migrate_canonical_names(dry_run=False, batch_size=50):
    """Migrate existing cards to add canonical names."""

    print("=" * 80)
    print("CANONICAL NAME MIGRATION")
    print("=" * 80)

    # Step 1: Backup database
    if not dry_run:
        print("\n[1/5] Creating database backup...")
        backup_path = backup_database(str(DB_PATH), "backups/pre_canonical_migration")
        print(f"✓ Backup created: {backup_path}")
    else:
        print("\n[1/5] DRY RUN - Skipping backup")

    # Step 2: Get all unique player names
    print("\n[2/5] Fetching unique player names from database...")
    with get_session() as session:
        # Get all unique player names from cards table
        result = session.execute(text("""
            SELECT DISTINCT name, sport
            FROM cards
            WHERE is_player = 1
            AND (canonical_name IS NULL OR canonical_name = '')
        """))
        unique_names = result.fetchall()

        print(f"✓ Found {len(unique_names)} unique player names to process")

    # Step 3: Batch lookup canonical names
    print(f"\n[3/5] Looking up canonical names (batch_size={batch_size})...")
    canonical_service = CanonicalNameService()

    lookup_results = {}
    failed_lookups = []

    for i, (name, sport) in enumerate(unique_names):
        if i % batch_size == 0:
            print(f"  Progress: {i}/{len(unique_names)}")

        canonical = canonical_service.get_canonical_name(name, sport or 'baseball')
        lookup_results[name] = canonical

        if canonical is None:
            failed_lookups.append(name)

    print(f"✓ Completed {len(lookup_results)} lookups")
    print(f"  - Successful: {len(lookup_results) - len(failed_lookups)}")
    print(f"  - Failed: {len(failed_lookups)}")

    if failed_lookups:
        print("\nFailed lookups (will use NULL canonical_name):")
        for name in failed_lookups[:10]:
            print(f"  - {name}")
        if len(failed_lookups) > 10:
            print(f"  ... and {len(failed_lookups) - 10} more")

    # Step 4: Update database
    print("\n[4/5] Updating database...")

    if dry_run:
        print("DRY RUN - Would update:")
        for name, canonical in list(lookup_results.items())[:5]:
            print(f"  '{name}' -> '{canonical}'")
        print(f"  ... and {len(lookup_results) - 5} more")
    else:
        updated_cards = 0
        updated_complete = 0

        with get_session() as session:
            # Update cards table
            for name, canonical in lookup_results.items():
                result = session.execute(
                    text("UPDATE cards SET canonical_name = :canonical WHERE name = :name AND is_player = 1"),
                    {"canonical": canonical, "name": name}
                )
                updated_cards += result.rowcount

            # Update cards_complete table
            for name, canonical in lookup_results.items():
                result = session.execute(
                    text("UPDATE cards_complete SET canonical_name = :canonical WHERE name = :name AND is_player = 1"),
                    {"canonical": canonical, "name": name}
                )
                updated_complete += result.rowcount

            session.commit()

        print(f"✓ Updated {updated_cards} cards")
        print(f"✓ Updated {updated_complete} cards_complete records")

    # Step 5: Identify and report duplicates
    print("\n[5/5] Identifying potential duplicates...")

    with get_session() as session:
        # Find cards with same canonical_name, brand, number, year
        result = session.execute(text("""
            SELECT
                canonical_name,
                brand,
                number,
                copyright_year,
                COUNT(*) as count,
                GROUP_CONCAT(name, ' | ') as original_names,
                GROUP_CONCAT(id, ',') as card_ids
            FROM cards
            WHERE canonical_name IS NOT NULL
            GROUP BY canonical_name, brand, number, copyright_year
            HAVING count > 1
            ORDER BY count DESC
        """))

        duplicates = result.fetchall()

        if duplicates:
            print(f"✓ Found {len(duplicates)} potential duplicate groups:")
            print("\nDuplicate groups (showing top 10):")
            for i, row in enumerate(duplicates[:10]):
                canonical, brand, number, year, count, names, ids = row
                print(f"\n  {i+1}. {canonical} - {brand} #{number} ({year})")
                print(f"     Count: {count} cards")
                print(f"     Original names: {names}")
                print(f"     Card IDs: {ids}")

            if len(duplicates) > 10:
                print(f"\n  ... and {len(duplicates) - 10} more duplicate groups")

            # Save duplicate report
            report_path = Path("logs/duplicate_analysis.json")
            report_path.parent.mkdir(parents=True, exist_ok=True)

            if not dry_run:
                duplicate_list = []
                for row in duplicates:
                    canonical, brand, number, year, count, names, ids = row
                    duplicate_list.append({
                        'canonical_name': canonical,
                        'brand': brand,
                        'number': number,
                        'copyright_year': year,
                        'count': count,
                        'original_names': names,
                        'card_ids': ids
                    })

                with open(report_path, 'w') as f:
                    json.dump(duplicate_list, f, indent=2)
                print(f"\n✓ Duplicate report saved to: {report_path}")
        else:
            print("✓ No duplicates found")

    print("\n" + "=" * 80)
    print("MIGRATION COMPLETE")
    print("=" * 80)

    if failed_lookups:
        print(f"\nWARNING: {len(failed_lookups)} names could not be resolved to canonical form")
        print("These cards will use NULL canonical_name and fall back to exact name matching")

    return {
        'total_names': len(unique_names),
        'successful_lookups': len(lookup_results) - len(failed_lookups),
        'failed_lookups': len(failed_lookups),
        'duplicates_found': len(duplicates) if duplicates else 0
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Migrate existing cards to add canonical names')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes without updating database')
    parser.add_argument('--batch-size', type=int, default=50, help='Number of lookups between progress updates')

    args = parser.parse_args()

    try:
        results = migrate_canonical_names(dry_run=args.dry_run, batch_size=args.batch_size)

        if args.dry_run:
            print("\nDRY RUN COMPLETE - No changes made to database")
            print("Run without --dry-run to apply changes")

        sys.exit(0)
    except Exception as e:
        print(f"\nERROR: Migration failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
