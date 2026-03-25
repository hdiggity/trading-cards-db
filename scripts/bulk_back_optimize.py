#!/usr/bin/env python3
"""Optimize card grid images for Claude Vision text extraction.

Applies targeted enhancements to maximize legibility of printed text on
trading card backs: stats, player names, year, brand, set info.

Can be used as a module (optimize_for_vision) or run as a CLI tool to
batch-process files in a directory.

Usage:
    python scripts/bulk_back_optimize.py
    python scripts/bulk_back_optimize.py --dir ~/Downloads --strength medium
"""

import argparse
import sys
from pathlib import Path

import pillow_heif
from PIL import Image, ImageEnhance, ImageFilter, ImageOps


def optimize_for_vision(image: Image.Image, strength: str = "medium") -> Image.Image:
    """Prepare a card grid image for Claude Vision text extraction.

    Optimizes for readability of small printed text (stats, names, years)
    without introducing artifacts that confuse vision models.

    Args:
        image: Input PIL Image (any mode).
        strength: 'light', 'medium', or 'strong'.

    Returns:
        Optimized RGB PIL Image.
    """
    presets = {
        "light": {
            "max_px": 3840,
            "unsharp_radius": 1.5,
            "unsharp_percent": 120,
            "unsharp_threshold": 3,
            "contrast": 1.08,
            "brightness": 1.03,
            "color": 1.05,
            "denoise": False,
        },
        "medium": {
            "max_px": 4096,
            "unsharp_radius": 2.0,
            "unsharp_percent": 160,
            "unsharp_threshold": 2,
            "contrast": 1.15,
            "brightness": 1.05,
            "color": 1.1,
            "denoise": True,
        },
        "strong": {
            "max_px": 4096,
            "unsharp_radius": 2.5,
            "unsharp_percent": 200,
            "unsharp_threshold": 1,
            "contrast": 1.22,
            "brightness": 1.07,
            "color": 1.15,
            "denoise": True,
        },
    }

    cfg = presets.get(strength, presets["medium"])

    # Correct EXIF orientation before anything else
    image = ImageOps.exif_transpose(image)

    if image.mode != "RGB":
        image = image.convert("RGB")

    # Upscale small images so text is large enough for vision model
    # (many phone photos are already 3000+ px, but some are smaller)
    min_long_edge = 2400
    long_edge = max(image.size)
    if long_edge < min_long_edge:
        scale = min_long_edge / long_edge
        new_size = (int(image.size[0] * scale), int(image.size[1] * scale))
        image = image.resize(new_size, Image.Resampling.LANCZOS)

    # Cap at max resolution (Claude Vision handles up to ~8000px but 4096 is ideal)
    if max(image.size) > cfg["max_px"]:
        ratio = cfg["max_px"] / max(image.size)
        new_size = (int(image.size[0] * ratio), int(image.size[1] * ratio))
        image = image.resize(new_size, Image.Resampling.LANCZOS)

    # Mild denoise before sharpening to avoid amplifying noise
    if cfg["denoise"]:
        image = image.filter(ImageFilter.MedianFilter(size=3))

    # Auto-levels: stretch histogram to use full tonal range.
    # Helps underexposed or overcast phone photos where text looks washed out.
    image = ImageOps.autocontrast(image, cutoff=0.5)

    # Brightness adjustment (compensate for dim lighting when scanning)
    if cfg["brightness"] != 1.0:
        image = ImageEnhance.Brightness(image).enhance(cfg["brightness"])

    # Contrast boost: makes text stand out from card background
    if cfg["contrast"] != 1.0:
        image = ImageEnhance.Contrast(image).enhance(cfg["contrast"])

    # Color saturation: helps distinguish colored text, logos, set identifiers
    if cfg["color"] != 1.0:
        image = ImageEnhance.Color(image).enhance(cfg["color"])

    # Unsharp mask: best filter for sharpening printed text edges.
    # More effective than PIL Sharpness enhancer for small characters.
    image = image.filter(ImageFilter.UnsharpMask(
        radius=cfg["unsharp_radius"],
        percent=cfg["unsharp_percent"],
        threshold=cfg["unsharp_threshold"],
    ))

    return image


def load_image(path: Path) -> Image.Image:
    """Load HEIC, JPEG, or PNG into PIL Image."""
    if path.stat().st_size < 1024:
        raise ValueError(f"file too small ({path.stat().st_size} bytes), likely corrupted")
    if path.suffix.lower() in {".heic", ".heif"}:
        pillow_heif.register_heif_opener()
    return Image.open(str(path))


def process_file(input_path: Path, output_dir: Path, strength: str = "medium") -> bool:
    """Optimize a single image file and save as PNG in output_dir."""
    try:
        image = load_image(input_path)
        optimized = optimize_for_vision(image, strength=strength)

        output_path = output_dir / (input_path.stem + ".png")
        optimized.save(str(output_path), format="PNG", optimize=True)

        # Remove original only if output is in same directory (in-place mode)
        if output_dir.resolve() == input_path.parent.resolve() and output_path != input_path:
            input_path.unlink()

        print(f"  {input_path.name} -> {output_path.name}")
        return True
    except Exception as e:
        print(f"  SKIP {input_path.name}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Optimize card grid images for Claude Vision text extraction"
    )
    parser.add_argument(
        "--dir",
        default=Path.home() / "Downloads",
        type=Path,
        help="Directory to scan (default: ~/Downloads)",
    )
    parser.add_argument(
        "--strength",
        choices=["light", "medium", "strong"],
        default="medium",
        help="Enhancement strength (default: medium)",
    )
    args = parser.parse_args()

    src_dir = args.dir
    if not src_dir.exists():
        print(f"error: directory not found: {src_dir}")
        sys.exit(1)

    exts = {".heic", ".heif", ".jpg", ".jpeg", ".png"}
    files = [f for f in src_dir.iterdir() if f.is_file() and f.suffix.lower() in exts]

    if not files:
        print(f"no image files found in {src_dir}")
        sys.exit(0)

    print(f"optimizing {len(files)} file(s) [{args.strength}]...")
    ok = sum(process_file(f, src_dir, args.strength) for f in sorted(files))
    print(f"done: {ok}/{len(files)}")


if __name__ == "__main__":
    main()
