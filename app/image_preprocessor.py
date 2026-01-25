"""Image preprocessing for improved GPT Vision extraction.

Enhances images before sending to GPT and handles original/compressed
file management.
"""

import shutil
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageStat

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass


def is_already_enhanced(img: Image.Image) -> bool:
    """Detect if image appears to already be enhanced.

    Checks for signs of prior enhancement:
    - High contrast (wide luminance distribution)
    - High sharpness (strong edge gradients)

    Returns True if image should NOT be enhanced again.
    """
    # Convert to grayscale for analysis
    if img.mode != 'L':
        gray = img.convert('L')
    else:
        gray = img

    # Get image statistics
    stat = ImageStat.Stat(gray)

    # Check contrast via standard deviation of pixel values
    # Enhanced images typically have stddev > 60
    stddev = stat.stddev[0]

    # Check for sharpness by looking at edge strength
    # Apply Laplacian-like filter and measure variance
    from PIL import ImageFilter
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edge_stat = ImageStat.Stat(edges)
    edge_mean = edge_stat.mean[0]

    # Thresholds based on typical enhanced vs raw images
    # High contrast: stddev > 55
    # High sharpness: edge_mean > 25
    is_high_contrast = stddev > 55
    is_sharp = edge_mean > 25

    # If both indicators suggest enhancement, skip
    if is_high_contrast and is_sharp:
        return True

    # Also check if contrast is very high (over-processed)
    if stddev > 70:
        return True

    return False


def enhance_image(img: Image.Image, force: bool = False) -> Image.Image:
    """Enhance image quality for better OCR/extraction.

    Applies:
    - Auto-contrast normalization
    - Sharpening
    - Slight denoising

    Detects if image is already enhanced and skips to avoid over-processing.

    Args:
        img: PIL Image object
        force: If True, always enhance regardless of detection

    Returns:
        Enhanced PIL Image (or original if already enhanced)
    """
    # Check if already enhanced (skip to avoid over-processing)
    if not force and is_already_enhanced(img):
        # Just convert to RGB if needed, don't enhance
        if img.mode != 'RGB':
            return img.convert('RGB')
        return img

    # Convert to RGB if necessary
    if img.mode != 'RGB':
        img = img.convert('RGB')

    # Auto-contrast: normalize brightness levels
    # Get min/max pixel values and stretch to full range
    from PIL import ImageOps
    img = ImageOps.autocontrast(img, cutoff=0.5)

    # Enhance contrast slightly
    contrast_enhancer = ImageEnhance.Contrast(img)
    img = contrast_enhancer.enhance(1.15)

    # Enhance sharpness
    sharpness_enhancer = ImageEnhance.Sharpness(img)
    img = sharpness_enhancer.enhance(1.3)

    # Light unsharp mask for edge enhancement (helps text readability)
    img = img.filter(ImageFilter.UnsharpMask(radius=1, percent=50, threshold=3))

    # Slight denoise using median filter (preserves edges better than blur)
    # Only apply if image is large enough
    if min(img.size) > 500:
        img = img.filter(ImageFilter.MedianFilter(size=3))

    return img


def preprocess_for_extraction(image_path: str,
                               originals_dir: str = None,
                               compressed_dir: str = None,
                               compress_quality: int = 80) -> Image.Image:
    """Preprocess image for GPT extraction and manage file copies.

    1. Copies original to originals_dir (preserving format)
    2. Creates compressed jpeg in compressed_dir (for git)
    3. Returns enhanced image for GPT extraction

    Args:
        image_path: Path to source image
        originals_dir: Directory to store original files (optional)
        compressed_dir: Directory to store compressed versions (optional)
        compress_quality: JPEG quality for compressed version (1-100)

    Returns:
        Enhanced PIL Image ready for GPT extraction
    """
    image_path = Path(image_path)

    # Load image
    img = Image.open(image_path)

    # Copy original if originals_dir specified
    if originals_dir:
        originals_path = Path(originals_dir)
        originals_path.mkdir(parents=True, exist_ok=True)

        # Preserve original filename and format
        dest_original = originals_path / image_path.name
        if not dest_original.exists():
            shutil.copy2(image_path, dest_original)

    # Create compressed version if compressed_dir specified
    if compressed_dir:
        compressed_path = Path(compressed_dir)
        compressed_path.mkdir(parents=True, exist_ok=True)

        # Convert to jpeg with compression
        base_name = image_path.stem
        dest_compressed = compressed_path / f"{base_name}.jpeg"

        if not dest_compressed.exists():
            # Convert and compress
            rgb_img = img.convert('RGB') if img.mode != 'RGB' else img
            rgb_img.save(dest_compressed, 'JPEG', quality=compress_quality, optimize=True)

    # Enhance for extraction
    enhanced = enhance_image(img)

    return enhanced


def get_enhanced_image_bytes(img: Image.Image, format: str = 'JPEG', quality: int = 95) -> bytes:
    """Convert enhanced image to bytes for API submission.

    Args:
        img: PIL Image
        format: Output format (JPEG recommended for API)
        quality: JPEG quality

    Returns:
        Image bytes
    """
    buffer = BytesIO()

    if img.mode != 'RGB' and format.upper() == 'JPEG':
        img = img.convert('RGB')

    img.save(buffer, format=format, quality=quality)
    return buffer.getvalue()


def batch_preprocess(source_dir: str,
                     originals_dir: str,
                     compressed_dir: str,
                     compress_quality: int = 80) -> dict:
    """Preprocess all images in a directory.

    Args:
        source_dir: Directory with source images
        originals_dir: Directory for original copies
        compressed_dir: Directory for compressed versions
        compress_quality: JPEG quality for compressed versions

    Returns:
        Dict with counts: {'processed': n, 'errors': [...]}
    """
    source_path = Path(source_dir)
    extensions = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.webp', '.tiff', '.bmp'}

    results = {'processed': 0, 'errors': []}

    for img_file in source_path.iterdir():
        if img_file.suffix.lower() in extensions:
            try:
                preprocess_for_extraction(
                    str(img_file),
                    originals_dir=originals_dir,
                    compressed_dir=compressed_dir,
                    compress_quality=compress_quality
                )
                results['processed'] += 1
            except Exception as e:
                results['errors'].append({'file': img_file.name, 'error': str(e)})

    return results
