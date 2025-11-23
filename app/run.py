import argparse
import datetime
import json
import os
import time
from pathlib import Path

import os
from .utils import gpt_extract_cards_from_image, gpt_extract_cards_single_pass, save_cards_to_verification
from .grid_processor import GridProcessor, save_grid_cards_to_verification
from .logging_system import logger, LogSource, ActionType

PENDING_VERIFICATION_DIR = Path("cards/pending_verification")
PENDING_BULK_BACK_DIR = Path("cards/pending_verification/pending_verification_bulk_back")

RAW_IMAGE_DIR = Path("cards/raw_scans")
FRONT_IMAGES_DIR = Path("cards/unprocessed_single_front")
BACK_IMAGES_DIR = Path("cards/unprocessed_bulk_back")
PROGRESS_FILE = Path("logs/processing_progress.json")


def update_progress(current: int, total: int, current_file: str = "", status: str = "processing"):
    """Write progress to file for UI to read"""
    try:
        PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
        progress_data = {
            "current": current,
            "total": total,
            "percent": int((current / max(total, 1)) * 100),
            "current_file": current_file,
            "status": status,
            "timestamp": datetime.datetime.now().isoformat()
        }
        with open(PROGRESS_FILE, "w") as f:
            json.dump(progress_data, f)
    except Exception:
        pass


def _is_probable_3x3_grid(image_path: Path) -> bool:
    """Lightweight detection for 3x3 grid backs using OpenCV if available.

    Returns True if we can confidently detect 3 horizontal and 3 vertical separators
    forming a 3x3 grid; False otherwise.
    """
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception:
        # OpenCV not available; cannot reliably detect grid
        return False

    try:
        img = cv2.imread(str(image_path))
        if img is None:
            # Try via PIL for HEIC, then convert
            from PIL import Image
            pil_img = Image.open(str(image_path))
            img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

        # Resize moderately to keep processing quick
        h, w = img.shape[:2]
        max_dim = max(h, w)
        if max_dim > 1600:
            scale = 1600.0 / max_dim
            img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

        # Preprocess for line detection
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)
        blur = cv2.GaussianBlur(gray, (3, 3), 0)
        edges = cv2.Canny(blur, 50, 150)

        # Detect horizontal and vertical lines
        lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=120, minLineLength=100, maxLineGap=20)
        if lines is None:
            return False

        horiz = []
        vert = []
        for ln in lines:
            x1, y1, x2, y2 = ln[0]
            if abs(y2 - y1) < 10:  # horizontal-ish
                horiz.append((y1 + y2) // 2)
            if abs(x2 - x1) < 10:  # vertical-ish
                vert.append((x1 + x2) // 2)

        # Deduplicate positions with tolerance
        def dedup(vals, tol=20):
            vals = sorted(vals)
            out = []
            for v in vals:
                if not out or abs(v - out[-1]) > tol:
                    out.append(v)
            return out

        horiz_u = dedup(horiz)
        vert_u = dedup(vert)

        # We expect at least 2 internal separators in each direction (plus borders)
        # Empirically, requiring >=2 gives a strong hint of 3x3 layout
        return len(horiz_u) >= 2 and len(vert_u) >= 2
    except Exception:
        return False


def process_and_move(image_path: Path, use_grid_processing: bool = False):
    print(f"processing: {image_path.name}")
    
    # Log upload and processing start
    file_size = image_path.stat().st_size if image_path.exists() else None
    file_type = image_path.suffix.lower() if image_path.suffix else None
    
    logger.log_upload(
        filename=image_path.name,
        original_path=str(image_path),
        file_size=file_size,
        file_type=file_type
    )
    
    start_time = time.time()
    logger.log_processing_start(image_path.name)
    
    try:
        # Auto-detect 3x3 grid if not explicitly requested
        if not use_grid_processing and _is_probable_3x3_grid(image_path):
            use_grid_processing = True

        if use_grid_processing:
            # Use enhanced grid processing for 3x3 back images
            grid_processor = GridProcessor()

            # Check for front images to use for matching, gated by env
            disable_front = os.getenv("DISABLE_FRONT_MATCH", "false").lower() == "true"
            front_dir = None
            if not disable_front and FRONT_IMAGES_DIR.exists():
                front_dir = FRONT_IMAGES_DIR

            grid_cards, raw_data = grid_processor.process_3x3_grid(
                str(image_path),
                front_images_dir=front_dir
            )

            processing_time = time.time() - start_time
            filename_stem = image_path.stem
            disable_tcdb = os.getenv("DISABLE_TCDB_VERIFICATION", "false").lower() == "true"

            # Save grid cards with enhanced metadata to pending_verification
            save_grid_cards_to_verification(
                grid_cards,
                out_dir=PENDING_VERIFICATION_DIR,
                # Keep JSON basename identical to image basename for UI association
                filename_stem=filename_stem,
                include_tcdb_verification=not disable_tcdb,
                save_cropped_backs=True,
                original_image_path=str(image_path)
            )

            card_count = len(grid_cards)
            print(f"Grid processing completed: {card_count} cards extracted")

            # Move bulk back image to pending_verification/bulk back
            PENDING_BULK_BACK_DIR.mkdir(parents=True, exist_ok=True)
            old_path = str(image_path)
            new_path = str(PENDING_BULK_BACK_DIR / image_path.name)
            image_path.rename(PENDING_BULK_BACK_DIR / image_path.name)

            # Log file move
            logger.log_file_operation(
                operation="move",
                source_path=old_path,
                dest_path=new_path,
                success=True
            )

            # Log processing completion
            logger.log_processing_complete(
                image_path.name,
                card_count,
                processing_time
            )

            print(f"completed: {image_path.name} (moved to pending_verification/bulk back)")
            return  # Early return since we handled the move differently
        else:
            # Fast single-pass extraction with compact high-accuracy prompt
            fast_mode = os.getenv("FAST_SINGLE_PASS", "true").lower() != "false"
            if fast_mode:
                parsed_cards, _ = gpt_extract_cards_single_pass(str(image_path))
            else:
                parsed_cards, _ = gpt_extract_cards_from_image(str(image_path))
            processing_time = time.time() - start_time
            
            filename_stem = image_path.stem
            disable_tcdb = os.getenv("DISABLE_TCDB_VERIFICATION", "false").lower() == "true"
            save_cards_to_verification(
                parsed_cards,
                out_dir=PENDING_VERIFICATION_DIR,
                filename_stem=filename_stem,
                include_tcdb_verification=not disable_tcdb
            )
            
            card_count = len(parsed_cards)

        # move image to pending_verification directory
        PENDING_VERIFICATION_DIR.mkdir(exist_ok=True)
        old_path = str(image_path)
        new_path = str(PENDING_VERIFICATION_DIR / image_path.name)
        image_path.rename(PENDING_VERIFICATION_DIR / image_path.name)
        
        # Log file move
        logger.log_file_operation(
            operation="move",
            source_path=old_path,
            dest_path=new_path,
            success=True
        )

        # Log processing completion
        logger.log_processing_complete(
            image_path.name,
            card_count,
            processing_time
        )

        print(f"completed: {image_path.name}")
    except Exception as e:
        print(f"error processing {image_path.name}: {e}")
        logger.update_upload_status(
            image_path.name,
            "failed",
            error_message=str(e)
        )
        # Image stays in unprocessed folder for retry


def process_all_raw_scans():
    print("looking for images to process...")
    images = [
        p
        for p in RAW_IMAGE_DIR.glob("*")
        if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".heic")
    ]
    if not images:
        print("no images found.")
    for image_path in images:
        print(f"found image: {image_path.name}")
        # Try to detect 3x3 grid backs and route accordingly for better performance
        use_grid = _is_probable_3x3_grid(image_path)
        if use_grid:
            print(f"detected probable 3x3 grid layout for {image_path.name}")
        process_and_move(image_path, use_grid_processing=use_grid)


def process_3x3_grid_backs(file_list_path=None):
    """
    Process 3x3 grid BACK images as PRIMARY input with enhanced card detection.

    INPUT: Card backs arranged in 3x3 grids (9 cards per image)
    PROCESSING: Enhanced image preprocessing + GPT-4 analysis optimized for card backs
    BACKUP: Single front images used only to supplement missing data from backs

    Front images remain untouched - used only as reference for matching/supplementing.

    Args:
        file_list_path: Optional path to JSON file containing list of specific filenames to process
    """
    print("Processing 3x3 grid BACK images (PRIMARY input source)...")

    # If a file list is provided, only process those specific files
    if file_list_path:
        try:
            with open(file_list_path, 'r') as f:
                file_list = json.load(f)
            back_images = [
                BACK_IMAGES_DIR / filename
                for filename in file_list
                if (BACK_IMAGES_DIR / filename).exists()
            ]
            print(f"Processing {len(back_images)} images from provided file list")
        except Exception as e:
            print(f"Error reading file list: {e}")
            return
    else:
        back_images = [
            p
            for p in BACK_IMAGES_DIR.glob("*")
            if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".heic")
        ] if BACK_IMAGES_DIR.exists() else []

    if not back_images:
        print(f"No 3x3 grid back images found in {BACK_IMAGES_DIR}")
        return

    # Check available front images for backup matching (read-only)
    front_count = 0
    if FRONT_IMAGES_DIR.exists():
        front_images = [
            p for p in FRONT_IMAGES_DIR.glob("*")
            if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".heic")
        ]
        front_count = len(front_images)

    total = len(back_images)
    print(f"Found {total} grid back images to process")
    print(f"Found {front_count} front images available for backup matching")
    print("Pipeline: BACKS (primary) → Enhanced Processing → Front Matching (backup)")

    update_progress(0, total, "", "starting")

    for i, image_path in enumerate(back_images):
        update_progress(i, total, image_path.name, "processing")
        print(f"[{i+1}/{total}] Processing: {image_path.name}")
        process_and_move(image_path, use_grid_processing=True)
        update_progress(i + 1, total, image_path.name, "completed")

    update_progress(total, total, "", "done")


def process_all_images():
    """Process all available images with appropriate methods"""
    print("processing all available images...")
    
    # Process 3x3 grid backs first (most accurate with context)
    if BACK_IMAGES_DIR.exists():
        process_3x3_grid_backs()
    
    # Process any remaining raw scans
    process_all_raw_scans()
    
    print("all image processing completed")


def auto_detect_and_process():
    """Auto-detect image types and process with appropriate methods"""
    print("auto-detecting image types and processing...")
    
    # Check for 3x3 grid images
    if BACK_IMAGES_DIR.exists():
        back_images = list(BACK_IMAGES_DIR.glob("*.jpg")) + list(BACK_IMAGES_DIR.glob("*.png")) + list(BACK_IMAGES_DIR.glob("*.heic"))
        if back_images:
            print(f"detected {len(back_images)} 3x3 grid back images")
            process_3x3_grid_backs()
    
    # Check for single front images
    if FRONT_IMAGES_DIR.exists():
        front_images = list(FRONT_IMAGES_DIR.glob("*.jpg")) + list(FRONT_IMAGES_DIR.glob("*.png")) + list(FRONT_IMAGES_DIR.glob("*.heic"))
        if front_images:
            print(f"detected {len(front_images)} single front images (used for matching)")
    
    # Process any remaining raw scans
    raw_images = [
        p for p in RAW_IMAGE_DIR.glob("*")
        if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".heic")
    ] if RAW_IMAGE_DIR.exists() else []
    
    if raw_images:
        print(f"detected {len(raw_images)} raw scan images")
        process_all_raw_scans()


def undo_last_processing():
    """Undo the last image processing operation using system_logs"""
    last_filename = logger.get_last_processed_filename()

    if not last_filename:
        print("no processing history found in system logs.")
        return

    # paths for the files to undo - check both locations
    pending_bulk_back_image = PENDING_BULK_BACK_DIR / last_filename
    pending_image = PENDING_VERIFICATION_DIR / last_filename
    json_file = PENDING_VERIFICATION_DIR / f"{Path(last_filename).stem}.json"

    # Determine original location based on where the image is now
    # If in pending_verification/bulk back, it was a bulk back -> move back to unprocessed_bulk_back
    # If in pending_verification root, it was a raw scan -> move back to raw_scans
    success = True
    image_found = False

    # Check pending_verification/bulk back first (bulk back images)
    if pending_bulk_back_image.exists():
        image_found = True
        original_location = BACK_IMAGES_DIR / last_filename
        try:
            BACK_IMAGES_DIR.mkdir(exist_ok=True)
            pending_bulk_back_image.rename(original_location)
            print(f"moved {last_filename} back to unprocessed_bulk_back/")
        except Exception as e:
            print(f"error moving image: {e}")
            success = False
    # Check pending_verification root (raw scans)
    elif pending_image.exists():
        image_found = True
        original_location = RAW_IMAGE_DIR / last_filename
        try:
            RAW_IMAGE_DIR.mkdir(exist_ok=True)
            pending_image.rename(original_location)
            print(f"moved {last_filename} back to raw_scans/")
        except Exception as e:
            print(f"error moving image: {e}")
            success = False

    if not image_found:
        print(f"image {last_filename} not found in pending_verification/")
        success = False

    # delete the JSON file
    if json_file.exists():
        try:
            json_file.unlink()
            print(f"deleted {json_file.name}")
        except Exception as e:
            print(f"error deleting JSON: {e}")
            success = False
    else:
        print(f"JSON file {json_file.name} not found")

    if success:
        print(f"undo completed for {last_filename}")
    else:
        print("undo operation had errors")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Process trading card images with enhanced accuracy"
    )
    parser.add_argument(
        "--raw", action="store_true",
        help="Process raw images in cards/raw_scans/"
    )
    parser.add_argument(
        "--grid", action="store_true",
        help="Process 3x3 grid back images with enhanced processing"
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Process all available images with appropriate methods"
    )
    parser.add_argument(
        "--auto", action="store_true",
        help="Auto-detect image types and process with optimal methods"
    )
    parser.add_argument(
        "--undo", action="store_true",
        help="Undo last processing operation"
    )
    parser.add_argument(
        "--file-list", type=str,
        help="Path to JSON file containing list of specific files to process"
    )
    args = parser.parse_args()

    if args.raw:
        process_all_raw_scans()
    elif args.grid:
        process_3x3_grid_backs(file_list_path=args.file_list)
    elif args.all:
        process_all_images()
    elif args.auto:
        auto_detect_and_process()
    elif args.undo:
        undo_last_processing()
    else:
        # Default to auto-detect if no specific mode specified
        print("No processing mode specified. Using auto-detection...")
        auto_detect_and_process()
