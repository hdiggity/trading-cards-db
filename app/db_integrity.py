"""Database Integrity and Validation System.

Prevents issues like:
- WAL data loss
- Missing/orphaned files
- Duplicate cards
- Invalid field values
- Path mismatches
"""

import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "cards" / "verified" / "trading_cards.db"
BACKUP_DIR = PROJECT_ROOT / "backups"
VERIFIED_BULK_BACK_DIR = PROJECT_ROOT / "cards" / "verified" / "verified_bulk_back"
VERIFIED_CROPPED_BACKS_DIR = PROJECT_ROOT / "cards" / "verified" / "verified_cropped_backs"
LOGS_DIR = PROJECT_ROOT / "logs"
INTEGRITY_LOG = LOGS_DIR / "integrity.log"


def log_integrity(message, level="INFO"):
    """Log integrity check messages."""
    timestamp = datetime.now().isoformat()
    log_entry = f"[{timestamp}] [{level}] {message}\n"

    LOGS_DIR.mkdir(exist_ok=True)
    with open(INTEGRITY_LOG, "a") as f:
        f.write(log_entry)

    if level == "ERROR":
        print(f"INTEGRITY ERROR: {message}")
    elif level == "WARNING":
        print(f"INTEGRITY WARNING: {message}")


def backup_database(reason="integrity_check"):
    """Create timestamped backup before any modifications."""
    if not DB_PATH.exists():
        return None

    BACKUP_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"trading_cards_{reason}_{timestamp}.db"

    # Force checkpoint before backup to ensure all data is in main file
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        conn.close()
    except:
        pass

    shutil.copy(DB_PATH, backup_path)
    log_integrity(f"Backup created: {backup_path}")
    return backup_path


def check_wal_status():
    """Check and fix WAL file issues."""
    issues = []

    wal_file = Path(str(DB_PATH) + "-wal")
    Path(str(DB_PATH) + "-shm")

    if wal_file.exists() and wal_file.stat().st_size > 0:
        issues.append(f"WAL file has uncommitted data ({wal_file.stat().st_size} bytes)")

        # Force checkpoint
        try:
            conn = sqlite3.connect(DB_PATH)
            result = conn.execute("PRAGMA wal_checkpoint(TRUNCATE);").fetchone()
            conn.close()
            log_integrity(f"WAL checkpoint forced: {result}")
        except Exception as e:
            log_integrity(f"WAL checkpoint failed: {e}", "ERROR")

    # Verify journal mode is DELETE (not WAL)
    try:
        conn = sqlite3.connect(DB_PATH)
        mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        if mode.lower() == "wal":
            issues.append("Database still using WAL mode, switching to DELETE")
            conn.execute("PRAGMA journal_mode=DELETE;")
        conn.close()
    except Exception as e:
        log_integrity(f"Journal mode check failed: {e}", "ERROR")

    return issues


def check_card_counts():
    """Verify each source file has exactly 9 cards."""
    issues = []

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT source_file, COUNT(*) as cnt
        FROM cards_complete
        GROUP BY source_file
        HAVING cnt != 9
    """)

    bad_counts = cursor.fetchall()
    for source_file, count in bad_counts:
        issues.append(f"{source_file} has {count} cards (expected 9)")

    conn.close()
    return issues


def check_duplicates():
    """Check for duplicate cards (same source_file + grid_position)."""
    issues = []

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT source_file, grid_position, COUNT(*) as cnt
        FROM cards_complete
        GROUP BY source_file, grid_position
        HAVING cnt > 1
    """)

    duplicates = cursor.fetchall()
    for source_file, pos, count in duplicates:
        issues.append(f"Duplicate: {source_file} pos {pos} ({count} entries)")

    conn.close()
    return issues


def check_cropped_back_files():
    """Verify all cropped_back_file paths point to existing files."""
    issues = []

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT id, source_file, grid_position, cropped_back_file FROM cards_complete")

    for card_id, source_file, pos, cropped_file in cursor.fetchall():
        if not cropped_file:
            issues.append(f"Card {card_id} ({source_file} pos {pos}) has no cropped_back_file")
            continue

        full_path = VERIFIED_CROPPED_BACKS_DIR / cropped_file
        if not full_path.exists():
            issues.append(f"Card {card_id}: cropped file not found: {cropped_file}")

    conn.close()
    return issues


def check_field_values():
    """Check for invalid field values."""
    issues = []

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # cards_complete.quantity should be NULL
    cursor.execute("SELECT COUNT(*) FROM cards_complete WHERE quantity IS NOT NULL")
    count = cursor.fetchone()[0]
    if count > 0:
        issues.append(f"{count} cards_complete records have non-NULL quantity")

    # cards.quantity should be >= 1
    cursor.execute("SELECT COUNT(*) FROM cards WHERE quantity IS NULL OR quantity < 1")
    count = cursor.fetchone()[0]
    if count > 0:
        issues.append(f"{count} cards records have invalid quantity")

    # notes should not be NULL or empty
    cursor.execute("SELECT COUNT(*) FROM cards_complete WHERE notes IS NULL OR notes = ''")
    count = cursor.fetchone()[0]
    if count > 0:
        issues.append(f"{count} cards_complete records have NULL/empty notes")

    cursor.execute("SELECT COUNT(*) FROM cards WHERE notes IS NULL OR notes = ''")
    count = cursor.fetchone()[0]
    if count > 0:
        issues.append(f"{count} cards records have NULL/empty notes")

    conn.close()
    return issues


def check_date_sync():
    """Verify cards.date_added is synced with
    cards_complete.verification_date."""
    issues = []

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Find cards where date_added doesn't match any verification_date
    cursor.execute("""
        SELECT c.name, c.date_added
        FROM cards c
        WHERE c.date_added IS NULL
        OR c.date_added NOT IN (
            SELECT verification_date FROM cards_complete
            WHERE name = c.name AND brand = c.brand
        )
        LIMIT 10
    """)

    mismatched = cursor.fetchall()
    if mismatched:
        issues.append(f"{len(mismatched)} cards have date_added not matching verification_date")

    conn.close()
    return issues


def fix_field_values():
    """Auto-fix common field value issues."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Fix cards_complete.quantity
    cursor.execute("UPDATE cards_complete SET quantity = NULL WHERE quantity IS NOT NULL")
    log_integrity(f"Set {cursor.rowcount} cards_complete.quantity to NULL")

    # Fix cards.quantity
    cursor.execute("UPDATE cards SET quantity = 1 WHERE quantity IS NULL OR quantity < 1")
    log_integrity(f"Fixed {cursor.rowcount} cards.quantity values")

    # Fix notes
    cursor.execute("UPDATE cards_complete SET notes = 'none' WHERE notes IS NULL OR notes = ''")
    log_integrity(f"Fixed {cursor.rowcount} cards_complete.notes values")

    cursor.execute("UPDATE cards SET notes = 'none' WHERE notes IS NULL OR notes = ''")
    log_integrity(f"Fixed {cursor.rowcount} cards.notes values")

    conn.commit()
    conn.close()


def fix_cropped_back_paths():
    """Auto-fix cropped_back_file paths to match actual files on disk."""
    import re

    # Build map of actual files
    file_map = {}
    for fname in os.listdir(VERIFIED_CROPPED_BACKS_DIR):
        match = re.search(r'(.+)_pos(\d+)', fname)
        if match:
            base = match.group(1)
            pos = match.group(2)
            file_map[(base, pos)] = fname

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT id, source_file, grid_position, cropped_back_file FROM cards_complete")
    updates = 0

    for card_id, source_file, grid_pos, current_path in cursor.fetchall():
        base = os.path.splitext(source_file)[0]
        key = (base, str(grid_pos))

        if key in file_map:
            correct_path = file_map[key]
            if correct_path != current_path:
                cursor.execute(
                    "UPDATE cards_complete SET cropped_back_file = ? WHERE id = ?",
                    (correct_path, card_id)
                )
                updates += 1

    conn.commit()
    conn.close()

    if updates:
        log_integrity(f"Fixed {updates} cropped_back_file paths")

    return updates


def sync_date_added():
    """Sync cards.date_added with earliest verification_date from
    cards_complete."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE cards SET date_added = (
            SELECT MIN(verification_date)
            FROM cards_complete
            WHERE cards_complete.name = cards.name
            AND cards_complete.brand = cards.brand
            AND cards_complete.number = cards.number
        )
    """)

    log_integrity(f"Synced date_added for {cursor.rowcount} cards")
    conn.commit()
    conn.close()


def run_full_check(auto_fix=False):
    """Run all integrity checks and optionally auto-fix issues."""
    log_integrity("Starting full integrity check")

    all_issues = []

    # Check WAL status first
    issues = check_wal_status()
    all_issues.extend(issues)

    # Check card counts
    issues = check_card_counts()
    all_issues.extend(issues)

    # Check duplicates
    issues = check_duplicates()
    all_issues.extend(issues)

    # Check cropped back files
    issues = check_cropped_back_files()
    all_issues.extend(issues)

    # Check field values
    issues = check_field_values()
    all_issues.extend(issues)

    # Check date sync
    issues = check_date_sync()
    all_issues.extend(issues)

    if all_issues:
        log_integrity(f"Found {len(all_issues)} issues", "WARNING")
        for issue in all_issues:
            log_integrity(f"  - {issue}", "WARNING")

        if auto_fix:
            log_integrity("Auto-fixing issues...")
            backup_database("pre_autofix")
            fix_field_values()
            fix_cropped_back_paths()
            sync_date_added()
            log_integrity("Auto-fix complete")
    else:
        log_integrity("No issues found")

    return all_issues


def verify_after_import(source_file, expected_cards=9):
    """Verify database state after importing cards from a source file."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT COUNT(*) FROM cards_complete WHERE source_file = ?",
        (source_file,)
    )
    count = cursor.fetchone()[0]

    if count != expected_cards:
        log_integrity(
            f"Import verification failed: {source_file} has {count} cards (expected {expected_cards})",
            "ERROR"
        )
        conn.close()
        return False

    # Verify all grid positions present
    cursor.execute(
        "SELECT grid_position FROM cards_complete WHERE source_file = ?",
        (source_file,)
    )
    positions = set(int(row[0]) for row in cursor.fetchall())
    expected_positions = set(range(expected_cards))

    if positions != expected_positions:
        missing = expected_positions - positions
        log_integrity(
            f"Import verification failed: {source_file} missing positions {missing}",
            "ERROR"
        )
        conn.close()
        return False

    conn.close()
    log_integrity(f"Import verified: {source_file} has {count} cards")
    return True


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--fix":
        issues = run_full_check(auto_fix=True)
    else:
        issues = run_full_check(auto_fix=False)

    if issues:
        print(f"\nFound {len(issues)} issues. Run with --fix to auto-repair.")
        sys.exit(1)
    else:
        print("\nDatabase integrity check passed.")
        sys.exit(0)
