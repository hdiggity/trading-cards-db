#!/usr/bin/env python3
"""Image compression for verified trading card images.

Flow:
1. Original uncompressed image is MOVED to cards/verified/originals/ (gitignored)
2. Compressed JPEG copy is created in the original location (tracked by git)

This keeps originals safe while only committing compressed versions.
"""

import os
import shutil
import sys
from pathlib import Path

from PIL import Image
from pillow_heif import register_heif_opener

register_heif_opener()

# Compression settings
JPEG_QUALITY = 85  # Good balance of quality and size
JPEG_OPTIMIZE = True
JPEG_PROGRESSIVE = True

# Originals directory (gitignored)
ORIGINALS_DIR = Path("cards/verified/originals")


def get_file_size_mb(filepath):
    """Get file size in MB."""
    return os.path.getsize(filepath) / (1024 * 1024)


def move_to_originals(filepath):
    """Move original file to originals directory."""
    filepath = Path(filepath)

    # Create originals directory structure matching source
    relative_path = filepath.relative_to("cards/verified")
    originals_path = ORIGINALS_DIR / relative_path
    originals_path.parent.mkdir(parents=True, exist_ok=True)

    # Move original (don't overwrite if exists)
    if not originals_path.exists():
        shutil.move(str(filepath), str(originals_path))
        return originals_path
    else:
        # Original already exists, just delete the duplicate
        filepath.unlink()
        return originals_path


def copy_to_originals(filepath):
    """Copy file to originals directory (for jpg/jpeg files that stay in
    place)."""
    filepath = Path(filepath)

    # Create originals directory structure matching source
    relative_path = filepath.relative_to("cards/verified")
    originals_path = ORIGINALS_DIR / relative_path
    originals_path.parent.mkdir(parents=True, exist_ok=True)

    # Copy original (don't overwrite if exists)
    if not originals_path.exists():
        shutil.copy2(str(filepath), str(originals_path))
    return originals_path


def compress_image(filepath):
    """Compress image: copy original to originals/, create compressed copy for git."""
    filepath = Path(filepath)

    if not filepath.exists():
        print(f"  Skipped (not found): {filepath}")
        return None

    original_size = get_file_size_mb(filepath)
    ext = filepath.suffix.lower()

    # Output will always be .jpg in the same location
    output_path = filepath.with_suffix('.jpg')

    # For jpg/jpeg files, copy to originals first before compressing
    if ext in ('.jpg', '.jpeg'):
        copy_to_originals(filepath)
        print(f"  {filepath.name} -> originals/ (copy)")

    # Open image
    with Image.open(filepath) as img:
        # Convert to RGB if needed
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            if img.mode in ('RGBA', 'LA'):
                background.paste(img, mask=img.split()[-1])
            else:
                background.paste(img)
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # Save compressed copy
        img.save(
            output_path,
            'JPEG',
            quality=JPEG_QUALITY,
            optimize=JPEG_OPTIMIZE,
            progressive=JPEG_PROGRESSIVE
        )

    new_size = get_file_size_mb(output_path)

    # Move original to originals/ (for non-jpg files)
    if filepath != output_path:
        move_to_originals(filepath)
        print(f"  {filepath.name} -> originals/")

    reduction = ((original_size - new_size) / original_size) * 100 if original_size > 0 else 0
    print(f"  Compressed: {output_path.name} ({original_size:.2f}MB -> {new_size:.2f}MB, {reduction:.0f}% smaller)")

    return output_path


def main():
    if len(sys.argv) < 2:
        print("Usage: compress_verified_images.py <image_file>")
        sys.exit(1)

    image_path = sys.argv[1]

    # Ensure originals dir exists
    ORIGINALS_DIR.mkdir(parents=True, exist_ok=True)

    # Compress the image
    result = compress_image(image_path)

    if result:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
