"""
Detailed 3x3 grid processing that extracts and analyzes each card individually.
Optimized for grid processing.
"""

import cv2
import numpy as np
from PIL import Image
import base64
from io import BytesIO
from pathlib import Path
from typing import List, Tuple, Dict, Any
import json
import os

from .utils import client, llm_chat
from .logging_system import logger, LogSource, ActionType

# Progress file for real-time UI updates
PROGRESS_FILE = Path("logs/processing_progress.json")


def write_substep_progress(substep: str, detail: str = "", percent: int = None):
    """Write substep progress to file for UI to read during long operations"""
    try:
        PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Read existing progress to preserve current/total
        existing = {}
        if PROGRESS_FILE.exists():
            try:
                existing = json.loads(PROGRESS_FILE.read_text())
            except Exception:
                pass

        import datetime
        progress_data = {
            "current": existing.get("current", 0),
            "total": existing.get("total", 1),
            "percent": percent if percent is not None else existing.get("percent", 0),
            "current_file": existing.get("current_file", ""),
            "status": "processing",
            "substep": substep,
            "detail": detail,
            "timestamp": datetime.datetime.now().isoformat()
        }
        PROGRESS_FILE.write_text(json.dumps(progress_data))
    except Exception:
        pass


# Optimal settings for GPT-4 Vision analysis of individual cards
# Increased resolution for better text recognition
CARD_TARGET_WIDTH = 640   # Larger for better OCR
CARD_TARGET_HEIGHT = 896  # Maintains trading card aspect ratio (2.5:3.5)
GRID_TARGET_SIZE = 2400   # Higher resolution for initial grid processing


def detect_and_extract_grid_cards(image_path: str) -> List[np.ndarray]:
    """
    Detect and extract all 9 individual cards from a 3x3 grid with high precision
    
    Returns:
        List of 9 numpy arrays, each containing an individual card image
    """
    # Load image at high resolution
    image = cv2.imread(image_path)
    if image is None:
        # Try with PIL for HEIC support
        pil_image = Image.open(image_path)
        image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
    
    # Resize to optimal grid processing size
    height, width = image.shape[:2]
    if width > GRID_TARGET_SIZE or height > GRID_TARGET_SIZE:
        scale = GRID_TARGET_SIZE / max(width, height)
        new_width = int(width * scale)
        new_height = int(height * scale)
        image = cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_LANCZOS4)
    
    # Apply preprocessing to enhance grid line detection
    processed_image = enhance_for_grid_detection(image)
    
    # Detect grid lines and extract cards
    card_regions = detect_3x3_grid(processed_image)

    if not card_regions or len(card_regions) != 9:
        # Try smart grid detection with edge profiling
        print("Hough detection incomplete, trying smart edge detection...")
        card_regions = smart_grid_detection(image)

    if not card_regions or len(card_regions) != 9:
        # Final fallback: simple grid division
        print("Using simple grid division fallback")
        card_regions = simple_grid_division(image)
    
    # Extract and enhance individual cards
    extracted_cards = []
    for i, region in enumerate(card_regions):
        try:
            # Extract card from region
            x, y, w, h = region
            card_image = image[y:y+h, x:x+w]
            
            # Apply detailed enhancement to individual card
            enhanced_card = enhance_individual_card(card_image)
            extracted_cards.append(enhanced_card)
            
        except Exception as e:
            print(f"Failed to extract card {i}: {e}")
            # Create placeholder for failed extraction
            placeholder = np.zeros((CARD_TARGET_HEIGHT, CARD_TARGET_WIDTH, 3), dtype=np.uint8)
            extracted_cards.append(placeholder)
    
    # Ensure we have exactly 9 cards
    while len(extracted_cards) < 9:
        placeholder = np.zeros((CARD_TARGET_HEIGHT, CARD_TARGET_WIDTH, 3), dtype=np.uint8)
        extracted_cards.append(placeholder)
    
    return extracted_cards[:9]


def enhance_for_grid_detection(image: np.ndarray) -> np.ndarray:
    """Apply preprocessing optimized for grid line detection"""
    
    # Noise reduction while preserving edges
    denoised = cv2.bilateralFilter(image, 9, 75, 75)
    
    # Convert to grayscale for line detection
    gray = cv2.cvtColor(denoised, cv2.COLOR_BGR2GRAY)
    
    # Enhance contrast for better line visibility
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    
    # Apply Gaussian blur to reduce noise
    blurred = cv2.GaussianBlur(enhanced, (3, 3), 0)
    
    return blurred


def detect_3x3_grid(image: np.ndarray) -> List[Tuple[int, int, int, int]]:
    """
    Detect 3x3 grid structure and return card regions
    
    Returns:
        List of (x, y, width, height) tuples for each card region
    """
    try:
        # Apply edge detection
        edges = cv2.Canny(image, 50, 150, apertureSize=3)
        
        # Detect horizontal and vertical lines
        horizontal_lines = detect_lines(edges, horizontal=True)
        vertical_lines = detect_lines(edges, horizontal=False)
        
        if len(horizontal_lines) >= 2 and len(vertical_lines) >= 2:
            # Sort lines by position
            horizontal_lines.sort()
            vertical_lines.sort()
            
            # Create grid intersections
            card_regions = []
            
            # Add image boundaries to line lists
            h, w = image.shape[:2]
            h_lines = [0] + horizontal_lines + [h]
            v_lines = [0] + vertical_lines + [w]
            
            # Extract 3x3 grid regions
            for row in range(3):
                for col in range(3):
                    # Calculate region boundaries
                    y1 = h_lines[row]
                    y2 = h_lines[row + 1]
                    x1 = v_lines[col]
                    x2 = v_lines[col + 1]
                    
                    # Add small margin to avoid grid lines
                    margin = 5
                    x1 += margin
                    y1 += margin
                    x2 -= margin
                    y2 -= margin
                    
                    if x2 > x1 and y2 > y1:
                        card_regions.append((x1, y1, x2 - x1, y2 - y1))
            
            if len(card_regions) == 9:
                return card_regions
                
    except Exception as e:
        print(f"Grid detection failed: {e}")
    
    return []


def detect_lines(edges: np.ndarray, horizontal: bool = True) -> List[int]:
    """Detect horizontal or vertical lines using Hough Line Transform"""
    
    # Use probabilistic Hough line transform
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi/180 if horizontal else np.pi/2,
        threshold=100,
        minLineLength=100,
        maxLineGap=20
    )
    
    detected_lines = []
    
    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = line[0]
            
            if horizontal:
                # Check if line is mostly horizontal
                if abs(y2 - y1) < 10:  # Allow small deviation
                    avg_y = (y1 + y2) // 2
                    detected_lines.append(avg_y)
            else:
                # Check if line is mostly vertical
                if abs(x2 - x1) < 10:  # Allow small deviation
                    avg_x = (x1 + x2) // 2
                    detected_lines.append(avg_x)
    
    # Remove duplicates and return unique lines
    unique_lines = []
    for line_pos in detected_lines:
        # Check if this line is close to an existing one
        is_duplicate = any(abs(line_pos - existing) < 20 for existing in unique_lines)
        if not is_duplicate:
            unique_lines.append(line_pos)
    
    return unique_lines


def simple_grid_division(image: np.ndarray) -> List[Tuple[int, int, int, int]]:
    """Fallback: divide image into 3x3 grid using simple math with smart margins"""

    h, w = image.shape[:2]

    card_regions = []
    cell_width = w // 3
    cell_height = h // 3

    # Calculate dynamic margin based on image size (2% of cell size)
    margin_x = max(5, int(cell_width * 0.02))
    margin_y = max(5, int(cell_height * 0.02))

    for row in range(3):
        for col in range(3):
            x = col * cell_width
            y = row * cell_height

            # For the last column/row, extend to image edge
            width = cell_width if col < 2 else w - x
            height = cell_height if row < 2 else h - y

            # Add margins, smaller on edges that touch other cards
            x_margin_left = margin_x if col > 0 else margin_x // 2
            x_margin_right = margin_x if col < 2 else margin_x // 2
            y_margin_top = margin_y if row > 0 else margin_y // 2
            y_margin_bottom = margin_y if row < 2 else margin_y // 2

            x += x_margin_left
            y += y_margin_top
            width -= (x_margin_left + x_margin_right)
            height -= (y_margin_top + y_margin_bottom)

            if width > 0 and height > 0:
                card_regions.append((x, y, width, height))

    return card_regions


def smart_grid_detection(image: np.ndarray) -> List[Tuple[int, int, int, int]]:
    """Advanced grid detection using multiple edge detection methods"""

    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image

    # Method 1: Try Sobel edge detection for grid lines
    sobel_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    sobel_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)

    # Find vertical separators (high vertical edge density)
    vert_profile = np.sum(np.abs(sobel_x), axis=0)
    horiz_profile = np.sum(np.abs(sobel_y), axis=1)

    # Find peaks in profiles that indicate grid lines
    v_peaks = find_grid_peaks(vert_profile, 3, w)
    h_peaks = find_grid_peaks(horiz_profile, 3, h)

    if len(v_peaks) >= 2 and len(h_peaks) >= 2:
        # Use detected grid lines
        v_lines = [0] + sorted(v_peaks)[:2] + [w]
        h_lines = [0] + sorted(h_peaks)[:2] + [h]

        regions = []
        for row in range(3):
            for col in range(3):
                x1, x2 = v_lines[col], v_lines[col + 1]
                y1, y2 = h_lines[row], h_lines[row + 1]
                margin = 5
                regions.append((x1 + margin, y1 + margin, x2 - x1 - 2*margin, y2 - y1 - 2*margin))
        return regions

    # Fallback to simple division
    return simple_grid_division(image)


def find_grid_peaks(profile: np.ndarray, num_peaks: int, max_val: int) -> List[int]:
    """Find peaks in profile that likely represent grid lines"""
    # Smooth the profile
    kernel_size = max(5, len(profile) // 50)
    if kernel_size % 2 == 0:
        kernel_size += 1
    smoothed = cv2.GaussianBlur(profile.reshape(1, -1), (kernel_size, 1), 0).flatten()

    # Find local maxima
    peaks = []
    min_distance = max_val // 4  # Minimum distance between grid lines

    for i in range(min_distance, len(smoothed) - min_distance):
        if smoothed[i] > smoothed[i-1] and smoothed[i] > smoothed[i+1]:
            # Check if it's a significant peak
            local_mean = np.mean(smoothed[max(0, i-50):min(len(smoothed), i+50)])
            if smoothed[i] > local_mean * 1.5:
                # Check distance from existing peaks
                if all(abs(i - p) > min_distance for p in peaks):
                    peaks.append(i)

    # Sort by peak height and return top num_peaks
    peaks.sort(key=lambda x: smoothed[x], reverse=True)
    return peaks[:num_peaks]


def enhance_individual_card(card_image: np.ndarray) -> np.ndarray:
    """
    Apply detailed enhancement to individual card with optimized preprocessing
    for maximum text extraction quality
    """

    # Step 1: Stronger noise reduction while preserving text edges
    denoised = cv2.bilateralFilter(card_image, 11, 85, 85)

    # Step 2: Enhanced contrast with stronger settings for card backs
    enhanced_contrast = enhance_contrast_advanced(denoised)

    # Step 3: Additional local contrast for small text (copyright lines)
    local_enhanced = enhance_local_contrast(enhanced_contrast)

    # Step 4: Sharpen text and details more aggressively
    sharpened = apply_unsharp_mask(local_enhanced, strength=1.8)

    # Step 5: Color correction for better analysis
    color_corrected = color_correct_advanced(sharpened)

    # Step 6: Resize to optimal dimensions for GPT analysis
    final_card = resize_card_for_analysis(color_corrected)

    return final_card


def enhance_local_contrast(image: np.ndarray) -> np.ndarray:
    """Apply local contrast enhancement to improve small text visibility"""
    # Convert to LAB for better contrast control
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)

    # Apply stronger CLAHE with smaller tile grid for local enhancement
    clahe_local = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
    enhanced_l = clahe_local.apply(l)

    enhanced_lab = cv2.merge((enhanced_l, a, b))
    return cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)


def enhance_contrast_advanced(image: np.ndarray) -> np.ndarray:
    """Advanced contrast enhancement optimized for card text"""
    
    # Convert to LAB color space for better contrast control
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    
    # Apply CLAHE with optimal settings for text
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced_l = clahe.apply(l)
    
    # Merge back and convert to BGR
    enhanced_lab = cv2.merge((enhanced_l, a, b))
    result = cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)
    
    # Apply gamma correction for optimal brightness
    gamma = 1.2
    lookup_table = np.array([((i / 255.0) ** (1.0 / gamma)) * 255 for i in np.arange(0, 256)]).astype("uint8")
    
    return cv2.LUT(result, lookup_table)


def apply_unsharp_mask(image: np.ndarray, strength: float = 1.5) -> np.ndarray:
    """Apply unsharp masking for crisp text and details"""

    # Create Gaussian blur
    blurred = cv2.GaussianBlur(image, (0, 0), 1.5)

    # Create unsharp mask with configurable strength
    unsharp_mask = cv2.addWeighted(image, 1.0 + strength * 0.5, blurred, -strength * 0.5, 0)

    return unsharp_mask


def color_correct_advanced(image: np.ndarray) -> np.ndarray:
    """Advanced color correction for optimal card analysis"""
    
    # Convert to LAB for better color correction
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    
    # Auto white balance
    l_normalized = cv2.normalize(l, None, 0, 255, cv2.NORM_MINMAX)
    
    # Merge and convert back
    corrected_lab = cv2.merge((l_normalized, a, b))
    result = cv2.cvtColor(corrected_lab, cv2.COLOR_LAB2BGR)
    
    return result


def resize_card_for_analysis(image: np.ndarray) -> np.ndarray:
    """Resize individual card to optimal dimensions for GPT analysis"""
    
    h, w = image.shape[:2]
    aspect_ratio = w / h
    
    # Maintain aspect ratio while targeting optimal size
    if aspect_ratio > (CARD_TARGET_WIDTH / CARD_TARGET_HEIGHT):
        # Width is limiting factor
        new_width = CARD_TARGET_WIDTH
        new_height = int(CARD_TARGET_WIDTH / aspect_ratio)
    else:
        # Height is limiting factor
        new_height = CARD_TARGET_HEIGHT
        new_width = int(CARD_TARGET_HEIGHT * aspect_ratio)
    
    return cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_LANCZOS4)


def create_high_contrast_card(card_image: np.ndarray) -> np.ndarray:
    """Create high-contrast version optimized for reading fine print like copyright"""
    # Convert to grayscale
    gray = cv2.cvtColor(card_image, cv2.COLOR_BGR2GRAY)

    # Apply very strong CLAHE for maximum text visibility
    clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(4, 4))
    enhanced = clahe.apply(gray)

    # Apply adaptive thresholding for text
    # Use a larger block size for better text detection
    thresh = cv2.adaptiveThreshold(
        enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 5
    )

    # Convert back to BGR for consistency
    return cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR)


def convert_cards_to_base64(card_images: List[np.ndarray]) -> List[str]:
    """Convert list of card images to base64 strings for GPT analysis
    Returns both enhanced and high-contrast versions for each card"""

    base64_images = []

    for i, card_image in enumerate(card_images):
        try:
            # Convert OpenCV image to PIL
            card_rgb = cv2.cvtColor(card_image, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(card_rgb)

            # Convert to base64 with high quality
            buffer = BytesIO()
            pil_image.save(buffer, format='PNG')  # PNG for lossless quality
            image_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

            base64_images.append(image_base64)

        except Exception as e:
            print(f"Failed to convert card {i} to base64: {e}")
            # Create placeholder base64 image
            placeholder = np.zeros((CARD_TARGET_HEIGHT, CARD_TARGET_WIDTH, 3), dtype=np.uint8)
            placeholder_rgb = cv2.cvtColor(placeholder, cv2.COLOR_BGR2RGB)
            pil_placeholder = Image.fromarray(placeholder_rgb)
            buffer = BytesIO()
            pil_placeholder.save(buffer, format='PNG')
            placeholder_b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
            base64_images.append(placeholder_b64)

    return base64_images


def convert_cards_to_base64_with_variants(card_images: List[np.ndarray]) -> Tuple[List[str], List[str]]:
    """Convert cards to base64 with both normal and high-contrast versions"""
    normal_images = []
    high_contrast_images = []

    for i, card_image in enumerate(card_images):
        try:
            # Normal enhanced version
            card_rgb = cv2.cvtColor(card_image, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(card_rgb)
            buffer = BytesIO()
            pil_image.save(buffer, format='PNG')
            normal_images.append(base64.b64encode(buffer.getvalue()).decode('utf-8'))

            # High contrast version for copyright text
            hc_card = create_high_contrast_card(card_image)
            hc_rgb = cv2.cvtColor(hc_card, cv2.COLOR_BGR2RGB)
            pil_hc = Image.fromarray(hc_rgb)
            buffer_hc = BytesIO()
            pil_hc.save(buffer_hc, format='PNG')
            high_contrast_images.append(base64.b64encode(buffer_hc.getvalue()).decode('utf-8'))

        except Exception as e:
            print(f"Failed to convert card {i}: {e}")
            placeholder = np.zeros((CARD_TARGET_HEIGHT, CARD_TARGET_WIDTH, 3), dtype=np.uint8)
            placeholder_rgb = cv2.cvtColor(placeholder, cv2.COLOR_BGR2RGB)
            pil_placeholder = Image.fromarray(placeholder_rgb)
            buffer = BytesIO()
            pil_placeholder.save(buffer, format='PNG')
            placeholder_b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
            normal_images.append(placeholder_b64)
            high_contrast_images.append(placeholder_b64)

    return normal_images, high_contrast_images


def build_detailed_grid_analysis_prompt() -> str:
    """Build optimized prompt for detailed grid analysis - concise for speed"""

    return """Analyze 9 baseball card BACKS extracted from a 3x3 grid.

EXTRACTION PRIORITY (in order):
1. COPYRIGHT YEAR: Find © symbol + 4-digit year (often tiny at bottom edge)
2. PLAYER NAME: Usually at top of card back in large text
3. CARD NUMBER: Look in corners (e.g., "#123" or just "123")
4. BRAND: Topps, Panini, Upper Deck, Fleer, Donruss, etc.
5. TEAM: CRITICAL - Extract from card back using these locations:
   - Stats table header often shows team abbreviation (CHC, NYY, LAD, etc.)
   - Biographical text: "plays for the [team]" or "traded to [team]"
   - Position line: "Third Base, Chicago White Sox"
   - Card title: "CUBS", "YANKEES" in header text
   - Career text: "[team] drafted him in..." or "signed with [team]"
   - Look for city names + baseball context (Chicago=Cubs/White Sox, NY=Yankees/Mets)
   - Common abbreviations: ATL=Braves, BOS=Red Sox, CHC=Cubs, CWS=White Sox, CLE=Indians/Guardians, DET=Tigers, HOU=Astros, KC=Royals, LAA=Angels, LAD=Dodgers, MIL=Brewers, MIN=Twins, NYM=Mets, NYY=Yankees, OAK=Athletics, PHI=Phillies, PIT=Pirates, SD=Padres, SF=Giants, SEA=Mariners, STL=Cardinals, TB=Rays, TEX=Rangers, TOR=Blue Jays, WSH=Nationals

KEY RULES:
- Multi-player/Leaders/Checklist cards: is_player_card=false, name=printed title
- Single player cards: is_player_card=true, name=player name
- Use stats + team + era to identify unclear names
- card_set = "n/a" for base cards; only specify actual subsets
- NEVER return "unknown" for team if ANY team info is visible - make your best determination

Return JSON array with 9 objects:
[{"grid_position":0,"name":"string","sport":"baseball","brand":"string","number":"string or null","copyright_year":"YYYY","team":"string","card_set":"n/a","condition":"very_good","is_player_card":true,"features":"none","notes":null}]

Be precise. Use "unknown" only when truly unreadable."""


def process_detailed_3x3_grid(image_path: str) -> Tuple[List[Dict], List[str]]:
    """
    Process 3x3 grid with individual card extraction and detailed analysis

    Returns:
        Tuple of (card_data_list, base64_images_list)
    """
    filename = Path(image_path).name

    try:
        print(f"Starting detailed 3x3 grid processing: {image_path}")
        write_substep_progress("Starting grid processing", filename, percent=5)

        # Step 1: Extract individual cards from grid
        print("Extracting individual cards from grid...")
        write_substep_progress("Extracting 9 cards from grid", "detecting card boundaries", percent=10)
        card_images = detect_and_extract_grid_cards(image_path)
        print(f"Extracted {len(card_images)} individual cards")
        write_substep_progress("Cards extracted", f"{len(card_images)} cards found", percent=25)

        # Step 2: Convert to base64 with both normal and high-contrast variants
        print("Converting cards to base64 with high-contrast variants...")
        write_substep_progress("Processing card images", "enhancing for OCR", percent=35)
        normal_images, hc_images = convert_cards_to_base64_with_variants(card_images)
        write_substep_progress("Images ready", "sending to GPT-4 Vision", percent=45)

        # Step 3: Analyze cards with GPT using both image variants
        print("Analyzing cards with GPT-4 Vision (using dual image variants)...")
        write_substep_progress("Analyzing with GPT-4 Vision", "extracting card data", percent=50)
        card_data = analyze_cards_with_gpt_dual(normal_images, hc_images, filename)
        write_substep_progress("Analysis complete", f"{len(card_data)} cards identified", percent=90)

        logger.log_grid_processing(
            filename,
            "complete",
            cards_detected=len(card_data),
            method="detailed_individual_dual"
        )

        print(f"Detailed grid processing completed: {len(card_data)} cards analyzed")
        return card_data, normal_images
        
    except Exception as e:
        error_msg = f"Detailed grid processing failed: {str(e)}"
        print(error_msg)
        
        logger.log_grid_processing(filename, "fail", error=error_msg, method="detailed_individual")
        
        # Return default cards
        default_cards = []
        for i in range(9):
            default_cards.append({
                "grid_position": i,
                "name": "unidentified",
                "sport": "baseball",
                "brand": "unknown",
                "number": None,
                "copyright_year": "unknown", 
                "team": "unknown",
                "card_set": "unknown",
                "condition": "very_good",
                "is_player_card": True,
                "features": "none",
                "notes": f"detailed processing failed at position {i}"
            })
        
        return default_cards, []


def analyze_cards_with_gpt(base64_images: List[str], filename: str) -> List[Dict]:
    """Send individual card images to GPT for detailed analysis (legacy single-variant)"""
    return analyze_cards_with_gpt_dual(base64_images, [], filename)


def analyze_cards_with_gpt_dual(normal_images: List[str], hc_images: List[str], filename: str) -> List[Dict]:
    """Send both normal and high-contrast card images to GPT for maximum accuracy"""

    try:
        # Build optimized analysis prompt
        analysis_prompt = build_detailed_grid_analysis_prompt()

        # Create messages with card images - include high-contrast for copyright detection
        image_content = []
        use_hc = len(hc_images) == len(normal_images)

        for i, image_b64 in enumerate(normal_images):
            image_content.append({
                "type": "text",
                "text": f"Card {i}:"
            })
            image_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{image_b64}"}
            })
            # Add high-contrast version for better copyright/fine print reading
            if use_hc and i < len(hc_images):
                image_content.append({
                    "type": "text",
                    "text": f"Card {i} (high-contrast for copyright/fine print):"
                })
                image_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{hc_images[i]}"}
                })

        messages = [
            {"role": "system", "content": analysis_prompt},
            {
                "role": "user",
                "content": image_content
            }
        ]

        # Send to LLM with optimized settings
        response = llm_chat(
            messages=messages,
            max_tokens=3000,  # Reduced for faster response with concise prompt
            temperature=0.0,  # More deterministic for accuracy
        )

        # Parse response
        raw_response = response.choices[0].message.content.strip()

        # Clean and parse JSON
        if raw_response.startswith("```json"):
            raw_response = raw_response[7:].strip()
        elif raw_response.startswith("```"):
            raw_response = raw_response[3:].strip()
        if raw_response.endswith("```"):
            raw_response = raw_response[:-3].strip()

        # Find and parse JSON array
        start = raw_response.find("[")
        if start == -1:
            raise ValueError("No JSON array found")

        depth = 0
        for idx in range(start, len(raw_response)):
            char = raw_response[idx]
            if char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    json_str = raw_response[start:idx + 1]
                    break
        else:
            raise ValueError("Incomplete JSON array")

        parsed_cards = json.loads(json_str)

        # Ensure we have exactly 9 cards
        while len(parsed_cards) < 9:
            parsed_cards.append({
                "grid_position": len(parsed_cards),
                "name": "unidentified",
                "sport": "baseball",
                "brand": "unknown",
                "number": None,
                "copyright_year": "unknown",
                "team": "unknown",
                "card_set": "n/a",
                "condition": "very_good",
                "is_player_card": True,
                "features": "none",
                "notes": "card analysis incomplete"
            })

        return parsed_cards[:9]

    except Exception as e:
        print(f"GPT analysis failed: {e}")
        raise
