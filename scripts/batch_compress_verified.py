#!/usr/bin/env python3
"""Batch compress all existing verified trading card images.

This is a one-time script to compress all existing images in:
- cards/verified/verified_bulk_back/
- cards/verified/verified_cropped_backs/

The pre-commit hook handles new images automatically going forward.
"""

import subprocess
import sys
from pathlib import Path

# Directories to process
VERIFIED_DIRS = [
    "cards/verified/verified_bulk_back",
    "cards/verified/verified_cropped_backs"
]

COMPRESSION_SCRIPT = "scripts/compress_verified_images.py"


def find_images(directory):
    """Find all image files in directory."""
    image_extensions = ('.png', '.jpg', '.jpeg', '.PNG', '.JPG', '.JPEG')
    directory = Path(directory)

    if not directory.exists():
        return []

    images = []
    for ext in image_extensions:
        images.extend(directory.glob(f"*{ext}"))

    return sorted(images)


def main():
    # Check for --yes flag
    auto_yes = '--yes' in sys.argv or '-y' in sys.argv

    print("=" * 70)
    print("BATCH COMPRESSION OF VERIFIED IMAGES")
    print("=" * 70)
    print()

    # Find all images
    all_images = []
    for directory in VERIFIED_DIRS:
        images = find_images(directory)
        if images:
            print(f"Found {len(images)} images in {directory}")
            all_images.extend(images)

    if not all_images:
        print("No images found to compress!")
        return

    print()
    print(f"Total: {len(all_images)} images")
    print()

    # Calculate total size before
    total_before = sum(img.stat().st_size for img in all_images) / (1024 * 1024)
    print(f"Total size before: {total_before:.1f} MB")
    print()

    # Confirm (skip if --yes flag provided)
    if not auto_yes:
        try:
            response = input(f"Compress all {len(all_images)} images? (y/N): ").strip().lower()
            if response != 'y':
                print("Aborted.")
                return
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return

    print()
    print("=" * 70)
    print("COMPRESSING...")
    print("=" * 70)
    print()

    # Process each image
    success_count = 0
    error_count = 0

    for i, image in enumerate(all_images, 1):
        print(f"[{i}/{len(all_images)}]")
        try:
            result = subprocess.run(
                [sys.executable, COMPRESSION_SCRIPT, str(image)],
                capture_output=True,
                text=True,
                check=True
            )
            print(result.stdout)
            success_count += 1
        except subprocess.CalledProcessError as e:
            print(f"  ERROR: Failed to compress {image.name}")
            print(f"  {e.stderr}")
            error_count += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            error_count += 1
        print()

    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Successfully compressed: {success_count}")
    print(f"Errors: {error_count}")

    # Calculate total size after
    # Need to check for both original extensions and new .jpg extensions
    all_current_images = []
    for directory in VERIFIED_DIRS:
        all_current_images.extend(find_images(directory))

    total_after = sum(img.stat().st_size for img in all_current_images) / (1024 * 1024)
    reduction = ((total_before - total_after) / total_before) * 100

    print(f"Total size before: {total_before:.1f} MB")
    print(f"Total size after: {total_after:.1f} MB")
    print(f"Total reduction: {reduction:.1f}%")
    print()
    print("Originals backed up to: cards/verified/originals/")


if __name__ == '__main__':
    main()
