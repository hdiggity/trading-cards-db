#!/usr/bin/env python3
"""Database Integrity Check Script.

Run this script periodically or after any issues to verify database integrity.

Usage:
    python scripts/check_integrity.py          # Check only
    python scripts/check_integrity.py --fix    # Check and auto-fix
"""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db_integrity import backup_database, run_full_check


def main():
    auto_fix = "--fix" in sys.argv

    print("=" * 60)
    print("Trading Cards Database Integrity Check")
    print("=" * 60)

    if auto_fix:
        print("\nAuto-fix mode enabled. Creating backup first...")
        backup_path = backup_database("pre_integrity_fix")
        print(f"Backup created: {backup_path}")

    print("\nRunning integrity checks...")
    issues = run_full_check(auto_fix=auto_fix)

    print("\n" + "=" * 60)
    if issues:
        print(f"RESULT: {len(issues)} issues found")
        if not auto_fix:
            print("\nRun with --fix to auto-repair issues.")
        sys.exit(1)
    else:
        print("RESULT: All checks passed!")
        sys.exit(0)


if __name__ == "__main__":
    main()
