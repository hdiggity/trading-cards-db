#!/usr/bin/env python3
"""Backfill originals directory with files from verified directories.

For any file in verified_bulk_back or verified_cropped_backs that
doesn't have a corresponding file in originals/, copy it there.
"""

import shutil
from pathlib import Path

VERIFIED_DIR = Path("cards/verified")
ORIGINALS_DIR = VERIFIED_DIR / "originals"

SUBDIRS = ["verified_bulk_back", "verified_cropped_backs"]


def get_basename(filename):
    """Get filename without extension."""
    return Path(filename).stem


def backfill_subdir(subdir):
    """Backfill originals for a subdirectory."""
    verified_path = VERIFIED_DIR / subdir
    originals_path = ORIGINALS_DIR / subdir

    if not verified_path.exists():
        print(f"  {subdir}: verified directory not found")
        return 0

    originals_path.mkdir(parents=True, exist_ok=True)

    # Get basenames of files in originals
    originals_basenames = {get_basename(f.name) for f in originals_path.iterdir() if f.is_file()}

    copied = 0
    for verified_file in verified_path.iterdir():
        if not verified_file.is_file():
            continue

        basename = get_basename(verified_file.name)
        if basename not in originals_basenames:
            dest = originals_path / verified_file.name
            shutil.copy2(str(verified_file), str(dest))
            print(f"  Copied: {verified_file.name}")
            copied += 1

    return copied


def main():
    print("Backfilling originals directory...")

    total_copied = 0
    for subdir in SUBDIRS:
        print(f"\n{subdir}:")
        copied = backfill_subdir(subdir)
        total_copied += copied
        if copied == 0:
            print("  All files already have originals")
        else:
            print(f"  Copied {copied} files")

    print(f"\nTotal: {total_copied} files copied to originals/")


if __name__ == "__main__":
    main()
