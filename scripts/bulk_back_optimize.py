#!/usr/bin/env python3
"""Optimize HEIC/JPEG images of 3x3 card grids for ChatGPT extraction.

Batch processes all HEIC and JPEG files from Downloads folder, replacing them
with optimized PNG files (better format for GPT-5.2 Vision).

Applies gentle, non-destructive enhancements to improve readability
without introducing artifacts that confuse GPT-5.2 Vision.

WARNING: Original HEIC/JPEG files are DELETED and replaced with PNG!

Usage:
    python bulk_back_analysis.py
    python bulk_back_analysis.py --strength medium
    python bulk_back_analysis.py --downloads ~/Desktop
"""

import argparse
import sys
from pathlib import Path

import pillow_heif
from PIL import Image, ImageEnhance, ImageFilter, ImageOps


def load_image(input_path: str) -> Image.Image:
    """Load HEIC or JPEG image and convert to PIL Image."""
    # Check file size first
    file_size = Path(input_path).stat().st_size
    if file_size < 1024:  # Less than 1KB
        raise ValueError(f"File size too small: {file_size} bytes")

    if input_path.lower().endswith(".heic"):
        # Register HEIF opener for HEIC files
        pillow_heif.register_heif_opener()

    # Use PIL to open image (works for HEIC, JPEG, PNG, etc.)
    image = Image.open(input_path)

    # CRITICAL: Apply EXIF orientation to prevent unwanted rotation
    # Phone cameras often store orientation in EXIF metadata
    # This corrects the image to its proper orientation then strips EXIF data
    # so the output PNG is always correctly oriented
    image = ImageOps.exif_transpose(image)

    # Convert to RGB if needed
    if image.mode != "RGB":
        image = image.convert("RGB")

    return image


def optimize_for_chatgpt(image: Image.Image, strength: str = "light") -> Image.Image:
    """Apply gentle enhancements optimized for ChatGPT/GPT-5.2 Vision.

    Args:
        image: Input PIL Image
        strength: 'light', 'medium', or 'strong'

    Returns:
        Enhanced PIL Image
    """
    # Strength presets
    presets = {
        "light": {
            "resize_max": 3200,
            "sharpen_factor": 1.1,
            "contrast_factor": 1.05,
            "brightness_factor": 1.02,
            "denoise": False,
        },
        "medium": {
            "resize_max": 3200,
            "sharpen_factor": 1.3,
            "contrast_factor": 1.1,
            "brightness_factor": 1.05,
            "denoise": True,
        },
        "strong": {
            "resize_max": 3200,
            "sharpen_factor": 1.5,
            "contrast_factor": 1.15,
            "brightness_factor": 1.08,
            "denoise": True,
        },
    }

    config = presets.get(strength, presets["light"])

    # Step 1: Resize to optimal resolution for GPT-5.2 Vision
    max_size = config["resize_max"]
    if max(image.size) > max_size:
        ratio = max_size / max(image.size)
        new_size = (int(image.size[0] * ratio), int(image.size[1] * ratio))
        image = image.resize(new_size, Image.Resampling.LANCZOS)

    # Step 2: Gentle noise reduction (optional, helps with phone camera images)
    if config["denoise"]:
        image = image.filter(ImageFilter.MedianFilter(size=3))

    # Step 3: Slight brightness adjustment (helps with underexposed cards)
    if config["brightness_factor"] != 1.0:
        enhancer = ImageEnhance.Brightness(image)
        image = enhancer.enhance(config["brightness_factor"])

    # Step 4: Gentle contrast enhancement (improves text readability)
    if config["contrast_factor"] != 1.0:
        enhancer = ImageEnhance.Contrast(image)
        image = enhancer.enhance(config["contrast_factor"])

    # Step 5: Gentle sharpening (improves text clarity)
    if config["sharpen_factor"] != 1.0:
        enhancer = ImageEnhance.Sharpness(image)
        image = enhancer.enhance(config["sharpen_factor"])

    return image


def process_single_file(
    input_path: Path, output_dir: Path, strength: str = "light", quality: int = 95
):
    """Process a single HEIC or JPEG file and replace with optimized PNG."""
    try:
        # Load image
        image = load_image(str(input_path))

        # Apply optimizations
        optimized = optimize_for_chatgpt(image, strength=strength)

        # Replace original with PNG (same name, different extension)
        output_filename = input_path.stem + ".png"
        output_path = output_dir / output_filename

        # Save as PNG (better for GPT-5.2 Vision)
        optimized.save(
            str(output_path),
            format="PNG",
            optimize=True,
            compress_level=9 - (quality // 10)
        )

        # Delete original file
        input_path.unlink()

        print(f"✓ {output_filename}")
        return True

    except Exception as e:
        print(f"✗ {input_path.name}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Batch optimize HEIC/JPEG images: replaces with optimized PNG in same directory"
    )
    parser.add_argument(
        "--downloads",
        default=Path.home() / "Downloads",
        type=Path,
        help="Directory to scan for HEIC/JPEG files (default: ~/Downloads)",
    )
    parser.add_argument(
        "--strength",
        choices=["light", "medium", "strong"],
        default="light",
        help="Enhancement strength (default: light)",
    )
    parser.add_argument(
        "--quality",
        type=int,
        default=95,
        help="PNG compression quality 0-100 (default: 95)",
    )

    args = parser.parse_args()

    # Setup paths
    downloads_dir = args.downloads

    # Validate downloads directory
    if not downloads_dir.exists():
        print(f"Error: Directory not found: {downloads_dir}")
        sys.exit(1)

    # Find all HEIC and JPEG files
    image_files = (
        list(downloads_dir.glob("*.HEIC")) +
        list(downloads_dir.glob("*.heic")) +
        list(downloads_dir.glob("*.JPEG")) +
        list(downloads_dir.glob("*.jpeg")) +
        list(downloads_dir.glob("*.JPG")) +
        list(downloads_dir.glob("*.jpg"))
    )

    if not image_files:
        print(f"\nNo HEIC or JPEG files found in {downloads_dir}")
        sys.exit(0)

    # Filter out corrupted files
    files_to_process = []
    corrupted_count = 0
    for image_file in image_files:
        # Check if file is corrupted (0 bytes or too small)
        file_size = image_file.stat().st_size
        if file_size == 0:
            print(f"✗ {image_file.name} (corrupted: 0 bytes - skipping)")
            corrupted_count += 1
            continue
        elif file_size < 1024:
            print(f"✗ {image_file.name} (corrupted: {file_size} bytes - skipping)")
            corrupted_count += 1
            continue

        files_to_process.append(image_file)

    if not files_to_process:
        print(f"\nAll {len(image_files)} image files were corrupted (skipped)")
        sys.exit(0)

    print(f"\nProcessing {len(files_to_process)} image file(s) ({args.strength} strength)...")
    if corrupted_count > 0:
        print(f"Skipped {corrupted_count} corrupted file(s)")
    print()

    # Process all files (output to same directory)
    success_count = 0
    for image_file in files_to_process:
        if process_single_file(image_file, downloads_dir, args.strength, args.quality):
            success_count += 1

    # Summary
    print(f"\nDone: {success_count}/{len(files_to_process)} files optimized")


if __name__ == "__main__":
    main()
