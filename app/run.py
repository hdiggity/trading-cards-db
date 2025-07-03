import argparse
import datetime
import json
import os
import time
from pathlib import Path

from .utils import gpt_extract_cards_from_image, save_cards_to_verification
from .grid_processor import GridProcessor, save_grid_cards_to_verification
from .logging_system import logger, LogSource, ActionType

PENDING_VERIFICATION_DIR = Path("images/pending_verification")
FAILED_PROCESSING_DIR = Path("images/failed_processing")

RAW_IMAGE_DIR = Path("images/raw_scans")
FRONT_IMAGES_DIR = Path("images/unprocessed_single_front")
BACK_IMAGES_DIR = Path("images/unprocessed_bulk_back")
LAST_PROCESSED_FILE = Path("last_processed.txt")
FAILED_LOG_FILE = Path("failed_processing.log")


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
        if use_grid_processing:
            # Use enhanced grid processing for 3x3 back images
            grid_processor = GridProcessor()
            
            # Check for front images to use for matching
            front_dir = FRONT_IMAGES_DIR if FRONT_IMAGES_DIR.exists() else None
            
            grid_cards, raw_data = grid_processor.process_3x3_grid(
                str(image_path), 
                front_images_dir=front_dir
            )
            
            processing_time = time.time() - start_time
            filename_stem = image_path.stem
            disable_tcdb = os.getenv("DISABLE_TCDB_VERIFICATION", "false").lower() == "true"
            
            # Save grid cards with enhanced metadata
            save_grid_cards_to_verification(
                grid_cards,
                out_dir=PENDING_VERIFICATION_DIR,
                filename_stem=filename_stem,
                include_tcdb_verification=not disable_tcdb
            )
            
            card_count = len(grid_cards)
            print(f"Grid processing completed: {card_count} cards extracted")
        else:
            # Use standard processing for single cards or other formats
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

        # track last processed file
        with open(LAST_PROCESSED_FILE, "w") as f:
            f.write(image_path.name)
        
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
        move_to_failed(image_path, str(e))


def move_to_failed(image_path: Path, error_message: str):
    """Move a failed image to the failed processing directory and log the error"""
    try:
        FAILED_PROCESSING_DIR.mkdir(exist_ok=True)

        # Move image to failed directory
        failed_image_path = FAILED_PROCESSING_DIR / image_path.name
        image_path.rename(failed_image_path)

        # Log the failure
        log_failure(image_path.name, error_message)

        print(f"moved failed image to: {failed_image_path}")
    except Exception as e:
        print(f"error moving failed image {image_path.name}: {e}")


def log_failure(filename: str, error_message: str):
    """Log failure details to the failed processing log"""
    import json
    from datetime import datetime

    failure_entry = {
        "filename": filename,
        "error": error_message,
        "timestamp": datetime.now().isoformat(),
        "retry_count": 0,
    }

    # Read existing failures
    failures = []
    if FAILED_LOG_FILE.exists():
        try:
            with open(FAILED_LOG_FILE, "r") as f:
                failures = json.load(f)
        except json.JSONDecodeError:
            failures = []

    # Add new failure
    failures.append(failure_entry)

    # Write back to file
    with open(FAILED_LOG_FILE, "w") as f:
        json.dump(failures, f, indent=2)


def retry_failed_image(filename: str):
    """Retry processing a specific failed image"""
    failed_image_path = FAILED_PROCESSING_DIR / filename

    if not failed_image_path.exists():
        raise FileNotFoundError(f"Failed image {filename} not found")

    print(f"retrying: {filename}")

    try:
        # Try processing again
        parsed_cards, _ = gpt_extract_cards_from_image(str(failed_image_path))
        filename_stem = failed_image_path.stem
        # Check if TCDB verification should be disabled
        disable_tcdb = os.getenv("DISABLE_TCDB_VERIFICATION", "false").lower() == "true"
        save_cards_to_verification(
            parsed_cards,
            out_dir=PENDING_VERIFICATION_DIR,
            filename_stem=filename_stem,
            include_tcdb_verification=not disable_tcdb)

        # Move to pending verification
        PENDING_VERIFICATION_DIR.mkdir(exist_ok=True)
        failed_image_path.rename(PENDING_VERIFICATION_DIR / filename)

        # Remove from failed log
        remove_from_failed_log(filename)

        print(f"retry successful: {filename}")
        return True
    except Exception as e:
        print(f"retry failed: {filename}: {e}")
        # Update retry count in log
        update_retry_count(filename, str(e))
        return False


def remove_from_failed_log(filename: str):
    """Remove a file from the failed processing log"""
    if not FAILED_LOG_FILE.exists():
        return

    try:
        with open(FAILED_LOG_FILE, "r") as f:
            failures = json.load(f)

        # Remove the file entry
        failures = [f for f in failures if f.get("filename") != filename]

        with open(FAILED_LOG_FILE, "w") as f:
            json.dump(failures, f, indent=2)
    except (json.JSONDecodeError, KeyError):
        pass


def update_retry_count(filename: str, error_message: str):
    """Update the retry count for a failed file"""
    if not FAILED_LOG_FILE.exists():
        return

    try:
        with open(FAILED_LOG_FILE, "r") as f:
            failures = json.load(f)

        # Find and update the file entry
        for failure in failures:
            if failure.get("filename") == filename:
                failure["retry_count"] = failure.get("retry_count", 0) + 1
                failure["last_retry"] = datetime.now().isoformat()
                failure["last_error"] = error_message
                break

        with open(FAILED_LOG_FILE, "w") as f:
            json.dump(failures, f, indent=2)
    except (json.JSONDecodeError, KeyError):
        pass


def get_failed_images():
    """Get list of failed images with their error details"""
    if not FAILED_LOG_FILE.exists():
        return []

    try:
        with open(FAILED_LOG_FILE, "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return []


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
        process_and_move(image_path)


def process_3x3_grid_backs():
    """Process 3x3 grid back images with enhanced grid processing"""
    print("processing 3x3 grid back images...")
    
    back_images = [
        p
        for p in BACK_IMAGES_DIR.glob("*")
        if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".heic")
    ] if BACK_IMAGES_DIR.exists() else []
    
    if not back_images:
        print(f"no 3x3 grid images found in {BACK_IMAGES_DIR}")
        return
    
    print(f"found {len(back_images)} grid images to process")
    
    for image_path in back_images:
        print(f"processing grid image: {image_path.name}")
        process_and_move(image_path, use_grid_processing=True)


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
    """Undo the last image processing operation"""
    if not LAST_PROCESSED_FILE.exists():
        print("no processing history found.")
        return

    with open(LAST_PROCESSED_FILE, "r") as f:
        last_filename = f.read().strip()

    if not last_filename:
        print("no processing history found.")
        return

    # paths for the files to undo
    pending_image = PENDING_VERIFICATION_DIR / last_filename
    json_file = PENDING_VERIFICATION_DIR / f"{Path(last_filename).stem}.json"
    original_location = RAW_IMAGE_DIR / last_filename

    success = True

    # move image back to raw_scans
    if pending_image.exists():
        try:
            RAW_IMAGE_DIR.mkdir(exist_ok=True)
            pending_image.rename(original_location)
            print(f"moved {last_filename} back to raw_scans/")
        except Exception as e:
            print(f"error moving image: {e}")
            success = False
    else:
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

    # clear the last processed file if successful
    if success:
        LAST_PROCESSED_FILE.unlink()
        print(f"undo completed for {last_filename}")
    else:
        print("undo operation had errors")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Process trading card images with enhanced accuracy"
    )
    parser.add_argument(
        "--raw", action="store_true", 
        help="Process raw images in images/raw_scans/"
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
    args = parser.parse_args()

    if args.raw:
        process_all_raw_scans()
    elif args.grid:
        process_3x3_grid_backs()
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
