"""
Detailed 3x3 grid processing that extracts and analyzes each card individually
Similar to single_card_analysis.py but optimized for grid processing
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

from .utils import client
from .logging_system import logger, LogSource, ActionType

# Optimal settings for GPT-4 Vision analysis of individual cards
CARD_TARGET_WIDTH = 512   # Smaller than single card since we have 9 cards
CARD_TARGET_HEIGHT = 714  # Maintains trading card aspect ratio (2.5:3.5)
GRID_TARGET_SIZE = 1800   # High resolution for initial grid processing


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
    
    if not card_regions:
        # Fallback: simple grid division
        print("Grid detection failed, using simple division")
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
    """Fallback: divide image into 3x3 grid using simple math"""
    
    h, w = image.shape[:2]
    
    card_regions = []
    cell_width = w // 3
    cell_height = h // 3
    
    for row in range(3):
        for col in range(3):
            x = col * cell_width
            y = row * cell_height
            
            # For the last column/row, extend to image edge
            width = cell_width if col < 2 else w - x
            height = cell_height if row < 2 else h - y
            
            # Add small margin
            margin = 10
            x += margin
            y += margin
            width -= 2 * margin
            height -= 2 * margin
            
            if width > 0 and height > 0:
                card_regions.append((x, y, width, height))
    
    return card_regions


def enhance_individual_card(card_image: np.ndarray) -> np.ndarray:
    """
    Apply detailed enhancement to individual card similar to single_card_analysis.py
    """
    
    # Step 1: Noise reduction while preserving detail
    denoised = cv2.bilateralFilter(card_image, 9, 75, 75)
    
    # Step 2: Enhanced contrast for text clarity
    enhanced_contrast = enhance_contrast_advanced(denoised)
    
    # Step 3: Sharpen text and details
    sharpened = apply_unsharp_mask(enhanced_contrast)
    
    # Step 4: Color correction for better analysis
    color_corrected = color_correct_advanced(sharpened)
    
    # Step 5: Resize to optimal dimensions for GPT analysis
    final_card = resize_card_for_analysis(color_corrected)
    
    return final_card


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


def apply_unsharp_mask(image: np.ndarray) -> np.ndarray:
    """Apply unsharp masking for crisp text and details"""
    
    # Create Gaussian blur
    blurred = cv2.GaussianBlur(image, (0, 0), 1.0)
    
    # Create unsharp mask
    unsharp_mask = cv2.addWeighted(image, 1.5, blurred, -0.5, 0)
    
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


def convert_cards_to_base64(card_images: List[np.ndarray]) -> List[str]:
    """Convert list of card images to base64 strings for GPT analysis"""
    
    base64_images = []
    
    for i, card_image in enumerate(card_images):
        try:
            # Convert OpenCV image to PIL
            card_rgb = cv2.cvtColor(card_image, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(card_rgb)
            
            # Convert to base64
            buffer = BytesIO()
            pil_image.save(buffer, format='JPEG', quality=95)
            image_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
            
            base64_images.append(image_base64)
            
        except Exception as e:
            print(f"Failed to convert card {i} to base64: {e}")
            # Create placeholder base64 image
            placeholder = np.zeros((CARD_TARGET_HEIGHT, CARD_TARGET_WIDTH, 3), dtype=np.uint8)
            placeholder_rgb = cv2.cvtColor(placeholder, cv2.COLOR_BGR2RGB)
            pil_placeholder = Image.fromarray(placeholder_rgb)
            buffer = BytesIO()
            pil_placeholder.save(buffer, format='JPEG', quality=95)
            placeholder_b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
            base64_images.append(placeholder_b64)
    
    return base64_images


def build_detailed_grid_analysis_prompt() -> str:
    """Build comprehensive prompt for detailed grid analysis"""
    
    return """You are analyzing 9 individual baseball card BACKS that have been extracted from a 3x3 grid and enhanced for maximum detail recognition.

CRITICAL ANALYSIS REQUIREMENTS:

Each image shows ONE individual card back that has been:
- Extracted from its grid position (0-8: top-left to bottom-right)
- Enhanced for optimal text recognition
- Resized for detailed analysis

For each card back, perform INTENSIVE analysis:

TEXT EXTRACTION:
- Scan every visible text element systematically
- Read player names (usually prominent at top)
- Find card numbers (often in corners or edges)
- Locate copyright years (© symbol + year, often very small)
- Identify brand names and logos
- Read team names from text or uniforms
- Extract statistical information that could identify players

VISUAL ANALYSIS:
- Examine uniform colors and logos for team identification
- Look for jersey numbers on uniform images
- Analyze card design elements for era/brand identification
- Assess card condition (corners, edges, surface quality)

CONTEXT CLUES:
- Use visible statistics (batting averages, ERAs, etc.) + team + era to identify specific players
- Cross-reference multiple data points for accuracy
- Apply baseball historical knowledge to validate identifications

RETURN FORMAT:
Analyze all 9 cards and return a JSON array with exactly 9 objects:

[
  {
    "grid_position": 0,
    "name": "player name from card text",
    "sport": "baseball",
    "brand": "brand name from logos/text", 
    "number": "card number if visible",
    "copyright_year": "production year (© symbol)",
    "team": "team name from text/uniform/logo",
    "card_set": "set name if identifiable",
    "condition": "mint/near_mint/excellent/very_good/good/fair/poor",
    "is_player_card": true,
    "features": "rookie/autograph/jersey/parallel/none",
    "notes": "any additional observations about this specific card"
  }
]

ACCURACY MANDATE:
- Use ONLY information visible on each individual card back
- If text is unclear, use "unknown" rather than guessing
- Focus on the card back as primary information source
- Each card represents a DIFFERENT player with DIFFERENT details
- Provide maximum detail possible from enhanced card images"""


def process_detailed_3x3_grid(image_path: str) -> Tuple[List[Dict], List[str]]:
    """
    Process 3x3 grid with individual card extraction and detailed analysis
    
    Returns:
        Tuple of (card_data_list, base64_images_list)
    """
    filename = Path(image_path).name
    
    try:
        print(f"Starting detailed 3x3 grid processing: {image_path}")
        
        # Step 1: Extract individual cards from grid
        print("Extracting individual cards from grid...")
        card_images = detect_and_extract_grid_cards(image_path)
        print(f"Extracted {len(card_images)} individual cards")
        
        # Step 2: Convert to base64 for GPT analysis
        print("Converting cards to base64 for analysis...")
        base64_images = convert_cards_to_base64(card_images)
        
        # Step 3: Analyze each card individually with GPT
        print("Analyzing each card with GPT-4 Vision...")
        card_data = analyze_cards_with_gpt(base64_images, filename)
        
        logger.log_grid_processing(
            filename,
            "complete", 
            cards_detected=len(card_data),
            method="detailed_individual"
        )
        
        print(f"Detailed grid processing completed: {len(card_data)} cards analyzed")
        return card_data, base64_images
        
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
    """Send individual card images to GPT for detailed analysis"""
    
    try:
        # Build comprehensive analysis prompt
        analysis_prompt = build_detailed_grid_analysis_prompt()
        
        # Create messages with all 9 card images
        image_content = []
        for i, image_b64 in enumerate(base64_images):
            image_content.append({
                "type": "text",
                "text": f"Card {i} (Grid Position {i}):"
            })
            image_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}
            })
        
        messages = [
            {"role": "system", "content": analysis_prompt},
            {
                "role": "user",
                "content": image_content
            }
        ]
        
        # Send to GPT-4 Vision
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=4000,
            temperature=0.1
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
                "card_set": "unknown",
                "condition": "very_good",
                "is_player_card": True,
                "features": "none",
                "notes": "card analysis incomplete"
            })
        
        return parsed_cards[:9]
        
    except Exception as e:
        print(f"GPT analysis failed: {e}")
        raise