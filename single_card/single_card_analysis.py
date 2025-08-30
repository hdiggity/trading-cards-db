import cv2
import os
import sys
import numpy as np
import argparse
from pathlib import Path
from PIL import Image
from pillow_heif import register_heif_opener

# Register HEIF opener for PIL
register_heif_opener()

# Settings
INPUT_DIR = "/Users/harlan/Downloads"
OUTPUT_DIR = "/Users/harlan/Downloads"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Allowed image extensions (lowercase)
ALLOWED_IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".heic", ".heif", ".gif",
    ".webp", ".tif", ".tiff", ".bmp"
}

# Optimal settings for LLM analysis
TARGET_WIDTH = 1024  # Good balance of detail and file size for AI analysis
TARGET_HEIGHT = 1400  # Standard trading card aspect ratio (roughly 2.5:3.5)


def reduce_noise(img):
    """Apply noise reduction while preserving text and detail"""
    return cv2.bilateralFilter(img, 9, 75, 75)


def enhance_contrast(img):
    """Enhanced contrast optimization for AI text recognition"""
    # Convert to LAB color space and apply CLAHE
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)

    # More aggressive CLAHE for better text clarity
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    cl = clahe.apply(l)
    merged = cv2.merge((cl, a, b))
    result = cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)

    # Additional gamma correction for optimal brightness
    gamma = 1.2
    lookup_table = np.array(
        [((i / 255.0) ** (1.0 / gamma)) * 255 for i in np.arange(0, 256)]).astype("uint8")
    return cv2.LUT(result, lookup_table)


def sharpen_image(img):
    """Apply unsharp masking for crisp text and details"""
    kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
    return cv2.filter2D(img, -1, kernel)


def color_correct(img):
    """Improve color accuracy and white balance"""
    # Convert to LAB for better color correction
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)

    # Auto white balance
    l = cv2.normalize(l, None, 0, 255, cv2.NORM_MINMAX)

    merged = cv2.merge((l, a, b))
    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)


def resize_for_analysis(img):
    """Resize to optimal dimensions for LLM analysis"""
    h, w = img.shape[:2]
    aspect_ratio = w / h

    # Maintain aspect ratio while targeting optimal size
    if aspect_ratio > (TARGET_WIDTH / TARGET_HEIGHT):
        # Width is limiting factor
        new_width = TARGET_WIDTH
        new_height = int(TARGET_WIDTH / aspect_ratio)
    else:
        # Height is limiting factor
        new_height = TARGET_HEIGHT
        new_width = int(TARGET_HEIGHT * aspect_ratio)

    return cv2.resize(img, (new_width, new_height),
                      interpolation=cv2.INTER_LANCZOS4)


def detect_card_border(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edged = cv2.Canny(blur, 30, 100)  # Reduced sensitivity

    contours, _ = cv2.findContours(
        edged.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    # Filter contours by area to avoid tiny inner borders
    height, width = image.shape[:2]
    min_area = (width * height) * 0.3  # Card should be at least 30% of image

    valid_contours = [c for c in contours if cv2.contourArea(c) > min_area]
    if not valid_contours:
        return None

    card_contour = sorted(valid_contours, key=cv2.contourArea, reverse=True)[0]
    peri = cv2.arcLength(card_contour, True)
    approx = cv2.approxPolyDP(
        card_contour,
        0.05 * peri,
        True)  # More tolerant approximation

    if len(approx) >= 4:
        # If more than 4 points, take the 4 corner points
        if len(approx) > 4:
            # Find the convex hull and approximate to 4 points
            hull = cv2.convexHull(approx)
            peri = cv2.arcLength(hull, True)
            approx = cv2.approxPolyDP(hull, 0.02 * peri, True)

        if len(approx) == 4:
            return np.squeeze(approx)

    return None


def four_point_transform(image, pts):
    # order points: top-left, top-right, bottom-right, bottom-left
    rect = np.zeros((4, 2), dtype="float32")

    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]  # top-left
    rect[2] = pts[np.argmax(s)]  # bottom-right

    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]  # top-right
    rect[3] = pts[np.argmax(diff)]  # bottom-left

    # Add padding to avoid overcropping
    padding = 20  # pixels
    h, w = image.shape[:2]

    # Expand the rectangle outward by padding amount
    rect[0][0] = max(0, rect[0][0] - padding)  # top-left x
    rect[0][1] = max(0, rect[0][1] - padding)  # top-left y
    rect[1][0] = min(w, rect[1][0] + padding)  # top-right x
    rect[1][1] = max(0, rect[1][1] - padding)  # top-right y
    rect[2][0] = min(w, rect[2][0] + padding)  # bottom-right x
    rect[2][1] = min(h, rect[2][1] + padding)  # bottom-right y
    rect[3][0] = max(0, rect[3][0] - padding)  # bottom-left x
    rect[3][1] = min(h, rect[3][1] + padding)  # bottom-left y

    (tl, tr, br, bl) = rect

    # Compute max width and height
    widthA = np.linalg.norm(br - bl)
    widthB = np.linalg.norm(tr - tl)
    maxWidth = int(max(widthA, widthB))

    heightA = np.linalg.norm(tr - br)
    heightB = np.linalg.norm(tl - bl)
    maxHeight = int(max(heightA, heightB))

    # Destination rectangle
    dst = np.array([
        [0, 0],
        [maxWidth - 1, 0],
        [maxWidth - 1, maxHeight - 1],
        [0, maxHeight - 1]
    ], dtype="float32")

    # Apply perspective transform
    M = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(image, M, (maxWidth, maxHeight))
    return warped


def process_image(filepath):
    """Complete image processing pipeline optimized for LLM analysis"""
    # Robust read: try OpenCV first, then PIL fallback (covers HEIC/HEIF)
    original = cv2.imread(filepath)
    if original is None:
        try:
            pil_image = Image.open(filepath)
            if pil_image.mode != 'RGB':
                pil_image = pil_image.convert('RGB')
            original = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
        except Exception as e:
            print(f"Error reading image {filepath}: {e}")
            return None

    # Step 1: Initial noise reduction
    denoised = reduce_noise(original)

    # Step 2: Enhance contrast for better edge detection
    enhanced = enhance_contrast(denoised)

    # Step 3: Detect and correct card perspective
    contour = detect_card_border(enhanced)
    if contour is not None:
        straightened = four_point_transform(enhanced, contour)
    else:
        straightened = enhanced  # fallback if contour detection fails

    # Step 4: Apply color correction
    color_corrected = color_correct(straightened)

    # Step 5: Apply final sharpening for text clarity
    sharpened = sharpen_image(color_corrected)

    # Step 6: Resize to optimal dimensions for AI analysis
    final_image = resize_for_analysis(sharpened)

    return final_image


def is_image_file(path: str) -> bool:
    """Check by extension that path is an allowed image file."""
    return Path(path).suffix.lower() in ALLOWED_IMAGE_EXTS


def iter_image_paths(input_path: str, recursive: bool = False):
    """Yield absolute paths to allowed image files under input_path.

    - If input_path is a file, yield it only if it is an image.
    - If input_path is a directory, iterate its immediate files (or recursively
      if recursive=True) and yield images only.
    """
    p = Path(input_path)
    if p.is_file():
        if is_image_file(str(p)):
            yield str(p.resolve())
        return

    if not p.is_dir():
        return

    if recursive:
        for child in p.rglob('*'):
            if child.is_file() and is_image_file(str(child)):
                yield str(child.resolve())
    else:
        for child in p.iterdir():
            if child.is_file() and is_image_file(str(child)):
                yield str(child.resolve())


def undo_processing():
    """Undo processing by moving optimized images back to raw directory"""
    restored_count = 0

    if not os.path.exists(OUTPUT_DIR):
        print(f"No processed images found in {OUTPUT_DIR}")
        return

    # Read processing log if it exists
    log_file = os.path.join(
        os.path.dirname(
            os.path.dirname(__file__)),
        "single_processed.txt")
    original_formats = {}

    if os.path.exists(log_file):
        with open(log_file, 'r') as f:
            for line in f:
                if " -> " in line:
                    original, processed = line.strip().split(" -> ")
                    base_name = processed.replace("_optimized.png", "")
                    original_formats[base_name] = original

    for filename in os.listdir(OUTPUT_DIR):
        if filename.endswith("_optimized.png"):
            # Extract original filename without _optimized suffix
            base_name = filename.replace("_optimized.png", "")

            # Use logged original format or assume HEIC
            if base_name in original_formats:
                original_filename = original_formats[base_name]
            else:
                original_filename = f"{base_name}.HEIC"

            processed_path = os.path.join(OUTPUT_DIR, filename)
            restored_path = os.path.join(INPUT_DIR, original_filename)

            # Move optimized image back to raw directory
            try:
                os.rename(processed_path, restored_path)
                restored_count += 1
                print(f"✓ Restored: {filename} -> {original_filename}")
            except Exception as e:
                print(f"✗ Failed to restore {filename}: {e}")

    # Clean up log file
    if os.path.exists(log_file):
        os.remove(log_file)

    print(f"\nUndo complete!")
    print(f"Restored {restored_count} images to {INPUT_DIR}")


def main():
    parser = argparse.ArgumentParser(
        description="Process trading card images for AI analysis")
    parser.add_argument(
        "--undo",
        action="store_true",
        help="Undo processing by restoring original images")
    parser.add_argument(
        "input",
        nargs="?",
        default=None,
        help=(
            "Path to an image file or a directory containing images. "
            "Defaults to /Users/harlan/Downloads"
        ),
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="If input is a directory, also process images in subdirectories",
    )
    args = parser.parse_args()

    if args.undo:
        undo_processing()
        return

    # Normal processing mode
    processed_count = 0
    failed_count = 0

    # Determine effective input path
    effective_input = args.input if args.input else INPUT_DIR
    effective_input = os.path.expanduser(effective_input)
    if not os.path.exists(effective_input):
        print(f"Input path does not exist: {effective_input}")
        return

    # Use existing single_processed.txt log file
    log_file = os.path.join(
        os.path.dirname(
            os.path.dirname(__file__)),
        "single_processed.txt")

    # Build list of image paths to process
    image_paths = list(iter_image_paths(effective_input, recursive=args.recursive))
    if not image_paths:
        # If a file was passed and it is not an allowed image
        if os.path.isfile(effective_input) and not is_image_file(effective_input):
            print(
                f"Input file is not a supported image type: {effective_input}\n"
                f"Allowed: {sorted(ALLOWED_IMAGE_EXTS)}"
            )
        else:
            print("No images found to process.")
        return

    for full_path in image_paths:
        filename = os.path.basename(full_path)
        print(f"Processing: {filename}")

        result = process_image(full_path)
        if result is not None:
            # Save as PNG for best quality preservation
            base_name = os.path.splitext(filename)[0]
            out_path = os.path.join(OUTPUT_DIR, f"{base_name}_optimized.png")

            # Use high quality PNG compression settings
            cv2.imwrite(out_path, result, [cv2.IMWRITE_PNG_COMPRESSION, 1])

            # Log the processing for undo functionality
            with open(log_file, 'a') as f:
                f.write(f"{filename} -> {base_name}_optimized.png\n")

            # Move file by removing from source after copying
            try:
                os.remove(full_path)
            except Exception as e:
                print(f"Warning: could not remove source file {full_path}: {e}")
            processed_count += 1
            print(f"✓ Optimized: {filename} -> {base_name}_optimized.png")
        else:
            print(f"✗ Failed to process: {filename}")
            failed_count += 1

    print(f"\nProcessing complete!")
    print(f"Successfully processed: {processed_count} images")
    print(f"Failed: {failed_count} images")
    print(f"Optimized images saved to: {OUTPUT_DIR}")
    print(f"Images are now ready for LLM analysis with:")
    print(f"- Optimal resolution ({TARGET_WIDTH}x{TARGET_HEIGHT} target)")
    print(f"- Enhanced contrast and sharpness for text recognition")
    print(f"- Noise reduction and color correction")
    print(f"- Perspective correction for straight card viewing")


if __name__ == "__main__":
    main()
