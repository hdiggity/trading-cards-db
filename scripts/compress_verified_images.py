#!/usr/bin/env python3
"""High-quality image compression for verified trading card images.

This script compresses images while maintaining visual quality:
- PNG files: Convert to high-quality JPEG (95% quality) or optimize PNG
- JPEG files: Re-optimize with quality=92

Original files are backed up to cards/verified/originals/ (not tracked by git)
"""

import os
import shutil
import sys
from pathlib import Path

from PIL import Image
from pillow_heif import register_heif_opener

# Register HEIF/HEIC support
register_heif_opener()

# Compression settings
JPEG_QUALITY = 95  # 95% quality - visually lossless
JPEG_OPTIMIZE = True
JPEG_PROGRESSIVE = True  # Progressive JPEGs load faster
PNG_OPTIMIZE_LEVEL = 6  # 0-9, higher = smaller but slower

# Backup directory for originals (add to .gitignore)
BACKUP_DIR = Path("cards/verified/originals")


def get_file_size_mb(filepath):
    """Get file size in MB."""
    return os.path.getsize(filepath) / (1024 * 1024)


def backup_original(filepath):
    """Backup original file before compression."""
    filepath = Path(filepath)

    # Create backup directory structure
    relative_path = filepath.relative_to("cards/verified")
    backup_path = BACKUP_DIR / relative_path
    backup_path.parent.mkdir(parents=True, exist_ok=True)

    # Only backup if not already backed up
    if not backup_path.exists():
        shutil.copy2(filepath, backup_path)
        return True
    return False


def compress_png_or_heic(filepath, source_format='PNG'):
    """Compress PNG/HEIC file by converting to high-quality JPEG.

    For trading card scans, JPEG at 95% quality is visually identical to
    PNG/HEIC but 80-90% smaller in file size.
    """
    filepath = Path(filepath)
    original_size = get_file_size_mb(filepath)

    # Backup original
    backed_up = backup_original(filepath)

    # Open and convert
    with Image.open(filepath) as img:
        # Convert to RGB if needed (remove alpha channel)
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # Save as JPEG with high quality
        output_path = filepath.with_suffix('.jpeg')
        img.save(
            output_path,
            'JPEG',
            quality=JPEG_QUALITY,
            optimize=JPEG_OPTIMIZE,
            progressive=JPEG_PROGRESSIVE
        )

    # Remove original file
    if output_path != filepath:
        filepath.unlink()

    new_size = get_file_size_mb(output_path)
    reduction = ((original_size - new_size) / original_size) * 100

    print(f"  {source_format}→JPEG: {filepath.name}")
    print(f"    {original_size:.2f}MB → {new_size:.2f}MB ({reduction:.1f}% smaller)")
    if backed_up:
        print(f"    Original backed up to: {BACKUP_DIR / filepath.relative_to('cards/verified')}")

    return output_path


def compress_jpeg(filepath):
    """Re-optimize JPEG file with high quality settings."""
    filepath = Path(filepath)
    original_size = get_file_size_mb(filepath)

    # Backup original
    backed_up = backup_original(filepath)

    # Open and re-save with optimization
    with Image.open(filepath) as img:
        # Preserve EXIF data
        exif = img.info.get('exif', None)

        # Save to temporary file first
        temp_path = filepath.with_suffix('.tmp.jpg')
        save_kwargs = {
            'quality': JPEG_QUALITY,
            'optimize': JPEG_OPTIMIZE,
            'progressive': JPEG_PROGRESSIVE
        }
        if exif:
            save_kwargs['exif'] = exif

        img.save(temp_path, 'JPEG', **save_kwargs)

    # Replace original only if new file is smaller
    new_size = get_file_size_mb(temp_path)
    if new_size < original_size:
        temp_path.replace(filepath)
        reduction = ((original_size - new_size) / original_size) * 100
        print(f"  Optimized: {filepath.name}")
        print(f"    {original_size:.2f}MB → {new_size:.2f}MB ({reduction:.1f}% smaller)")
        if backed_up:
            print(f"    Original backed up to: {BACKUP_DIR / filepath.relative_to('cards/verified')}")
    else:
        # New file not smaller, keep original
        temp_path.unlink()
        print(f"  Skipped: {filepath.name} (already optimized)")

    return filepath


def compress_image(filepath):
    """Compress image based on file type."""
    filepath = Path(filepath)

    if not filepath.exists():
        print(f"Error: File not found: {filepath}")
        return None

    ext = filepath.suffix.lower()

    if ext in ('.png',):
        return compress_png_or_heic(filepath, 'PNG')
    elif ext in ('.heic', '.heif'):
        return compress_png_or_heic(filepath, 'HEIC')
    elif ext in ('.jpg', '.jpeg'):
        return compress_jpeg(filepath)
    else:
        print(f"Unsupported file type: {ext}")
        return None


def main():
    if len(sys.argv) < 2:
        print("Usage: compress_verified_images.py <image_file>")
        sys.exit(1)

    image_path = sys.argv[1]

    # Ensure backup dir exists and is in .gitignore
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    gitignore_path = Path("cards/verified/.gitignore")
    gitignore_path.parent.mkdir(parents=True, exist_ok=True)

    # Add originals/ to .gitignore if not present
    if gitignore_path.exists():
        content = gitignore_path.read_text()
        if 'originals/' not in content:
            with open(gitignore_path, 'a') as f:
                f.write('\n# Original uncompressed images (backup)\noriginals/\n')
    else:
        gitignore_path.write_text('# Original uncompressed images (backup)\noriginals/\n')

    # Compress the image
    result = compress_image(image_path)

    if result:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
