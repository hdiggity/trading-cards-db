"""
Enhanced 3x3 grid processing with improved image preprocessing and card detection
"""

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
import base64
from io import BytesIO
from pathlib import Path
from typing import List, Tuple
import os

from .utils import convert_image_to_supported_format, client, llm_chat
from .logging_system import logger, LogSource, ActionType


def preprocess_grid_image(image_path: str) -> str:
    """
    Apply advanced preprocessing to optimize 3x3 grid images for better card detection
    
    Args:
        image_path: Path to the original grid image
        
    Returns:
        Base64 encoded preprocessed image
    """
    # Load image
    image = cv2.imread(image_path)
    if image is None:
        # Try with PIL for HEIC support
        pil_image = Image.open(image_path)
        image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
    
    # Apply preprocessing pipeline
    processed = apply_grid_enhancement_pipeline(image)
    
    # Convert to base64 for GPT
    _, buffer = cv2.imencode('.jpg', processed)
    image_base64 = base64.b64encode(buffer).decode('utf-8')
    
    return image_base64


def apply_grid_enhancement_pipeline(image: np.ndarray) -> np.ndarray:
    """
    Apply comprehensive enhancement pipeline optimized for 3x3 grids
    """
    # 1. Resize to optimal dimensions for processing (if too large/small)
    height, width = image.shape[:2]
    target_size = 1200  # Target width for processing
    
    if width > target_size * 1.5 or width < target_size * 0.5:
        aspect_ratio = height / width
        new_width = target_size
        new_height = int(target_size * aspect_ratio)
        image = cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_LANCZOS4)
    
    # 2. Improve lighting and contrast
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    
    # Apply CLAHE (Contrast Limited Adaptive Histogram Equalization) to L channel
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    l = clahe.apply(l)
    
    # Merge back
    enhanced = cv2.merge([l, a, b])
    enhanced = cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)
    
    # 3. Noise reduction while preserving text details
    enhanced = cv2.bilateralFilter(enhanced, 9, 75, 75)
    
    # 4. Enhance text contrast
    # Convert to grayscale for text analysis
    gray = cv2.cvtColor(enhanced, cv2.COLOR_BGR2GRAY)
    
    # Apply unsharp masking for text sharpening
    gaussian = cv2.GaussianBlur(gray, (0, 0), 2.0)
    unsharp_mask = cv2.addWeighted(gray, 1.5, gaussian, -0.5, 0)
    
    # Convert back to color
    enhanced = cv2.cvtColor(unsharp_mask, cv2.COLOR_GRAY2BGR)
    
    # 5. Perspective correction (basic)
    enhanced = correct_perspective_if_needed(enhanced)
    
    return enhanced


def correct_perspective_if_needed(image: np.ndarray) -> np.ndarray:
    """
    Apply basic perspective correction if the image appears skewed
    """
    try:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Find contours to detect rectangular shapes
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edged = cv2.Canny(blurred, 50, 150)
        
        contours, _ = cv2.findContours(edged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # Find the largest rectangular contour (likely the grid boundary)
        for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
            # Approximate contour
            epsilon = 0.02 * cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, epsilon, True)
            
            # If we found a rectangular shape
            if len(approx) == 4:
                # Get the corners
                corners = approx.reshape(4, 2)
                
                # Order corners: top-left, top-right, bottom-right, bottom-left
                corners = order_corners(corners)
                
                # Define target rectangle
                h, w = image.shape[:2]
                target_corners = np.array([
                    [0, 0],
                    [w, 0], 
                    [w, h],
                    [0, h]
                ], dtype=np.float32)
                
                # Apply perspective transform
                matrix = cv2.getPerspectiveTransform(corners.astype(np.float32), target_corners)
                corrected = cv2.warpPerspective(image, matrix, (w, h))
                
                return corrected
                
    except Exception as e:
        print(f"Perspective correction failed: {e}")
    
    # Return original if correction fails
    return image


def order_corners(corners):
    """Order corners as top-left, top-right, bottom-right, bottom-left"""
    # Sum and difference to find corners
    s = corners.sum(axis=1)
    diff = np.diff(corners, axis=1)
    
    ordered = np.zeros((4, 2), dtype=np.float32)
    ordered[0] = corners[np.argmin(s)]      # top-left (smallest sum)
    ordered[2] = corners[np.argmax(s)]      # bottom-right (largest sum)
    ordered[1] = corners[np.argmin(diff)]   # top-right (smallest difference)
    ordered[3] = corners[np.argmax(diff)]   # bottom-left (largest difference)
    
    return ordered


def build_enhanced_grid_prompt() -> str:
    """Build enhanced prompt specifically for 3x3 grid processing of card BACKS"""
    return """You are analyzing a 3x3 grid of baseball card BACKS (9 cards total) that has been optimized for better text recognition.

IMPORTANT: These are CARD BACKS, not fronts. Focus on the back-side information.

CRITICAL GRID ANALYSIS INSTRUCTIONS:
1. This image contains EXACTLY 9 trading card backs arranged in a 3x3 grid
2. Count systematically: Top row (positions 0,1,2), Middle row (3,4,5), Bottom row (6,7,8)
3. Each position contains a DIFFERENT player card with DIFFERENT information
4. Look for grid lines or borders separating the 9 cards
5. Analyze each card's back individually for text, stats, and details

ENHANCED TEXT DETECTION:
- The image has been preprocessed for optimal text clarity
- PLAYER NAME EXTRACTION (HIGHEST PRIORITY): Find the player's FULL NAME printed in ALL CAPS or bold text. Common locations: header section near top (may be below biographical text), next to card number, or as distinct name line (e.g., "ARTHUR BOBBY LEE DARWIN", "DAVE GOLTZ"). DO NOT extract team names, positions, biographical snippets, or stats. Look for the person's actual name in all caps/bold.
- Find copyright years (© symbol + year, often small text at borders)
- Identify team names from uniform colors, logos, or text
- Look for card numbers (often in corners or along edges)
- Read statistical information that may help identify players

GRID CONSISTENCY ANALYSIS:
- Cards in the same grid are typically from the same set/year
- Use clear cards to help identify unclear ones in the same grid
- Brand and copyright year should be consistent across all 9 cards
- If 8 cards clearly show "1975 Topps", assume the 9th is also 1975 Topps

INDIVIDUAL CARD EXTRACTION FOCUS:
NAMING RULE: If a card shows multiple players or is a Leaders/Checklist/Team card, set is_player_card=false and set name to the printed title header (e.g., '1973 Rookie First Basemen', 'Brewers Field Leaders', 'NL Batting Leaders'). Only for single-player cards set is_player_card=true and use the player's name.
For each of the 9 positions (0-8), extract:
- Player name: Find the player's FULL NAME in ALL CAPS or bold (e.g., "ARTHUR BOBBY LEE DARWIN", "DAVE GOLTZ"). Typically near top but may be below biographical text. DO NOT extract team names, positions, biographical snippets, or stats. Look for the person's actual name.
- Team (from uniform, text, or team colors)
- Card number (often in corners)
- Copyright year (© symbol, not stats years)
- Brand (Topps, Donruss, etc.)
- Set name (e.g., "1975 Topps")
- Condition assessment of that specific card
- Any special features visible

Return a JSON array with exactly 9 objects, one for each grid position. For card_set, use BASE SET naming '<year> <brand>' (e.g., '1975 Topps'); only include subset names if clearly printed (e.g., 'Topps Heritage', 'Stadium Club', 'Chrome'). Do not confuse card titles like 'Rookie First Basemen' with set names.
Return exactly this object shape for each card:
{{
  "grid_position": 0-8,
  "name": "FULL player name from TOP of card (largest text)",
  "sport": "baseball",
  "brand": "brand name",
  "number": "card number",
  "copyright_year": "production year",
  "team": "team name",
  "card_set": "set name", 
  "condition": "condition assessment",
  "is_player_card": true,
  "features": "special features or none",
  "notes": "any additional observations"
}}

ACCURACY REQUIREMENTS:
- Return exactly 9 different cards with different player names
- Use visible text evidence, not assumptions
- If text is unclear, use "unknown" rather than guessing
- Apply grid context to improve individual card identification
- Focus on card backs as the primary information source"""


def process_enhanced_3x3_grid(image_path: str) -> Tuple[List[dict], str]:
    """
    Process 3x3 grid with enhanced preprocessing and specialized prompting
    
    Returns:
        Tuple of (extracted_cards, preprocessed_image_base64)
    """
    filename = Path(image_path).name
    
    try:
        print(f"Processing enhanced 3x3 grid: {image_path}")
        
        # Step 1: Apply advanced preprocessing
        print("Applying image enhancement...")
        
        preprocessed_image_b64 = preprocess_grid_image(image_path)
        
        # Step 2: Use enhanced grid-specific prompt
        enhanced_prompt = build_enhanced_grid_prompt()
        
        # Step 3: Send to GPT with enhanced image and prompt
        messages = [
            {"role": "system", "content": enhanced_prompt},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{preprocessed_image_b64}"}
                    }
                ]
            }
        ]
        
        import os
        MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
        response = llm_chat(
            messages=messages,
            max_tokens=4000,  # Increased for 9 cards
            temperature=0.1,
        )
        
        # Parse response
        raw_response = response.choices[0].message.content.strip()
        print(f"GPT Response length: {len(raw_response)} characters")
        
        # Clean and parse JSON
        if raw_response.startswith("```json"):
            raw_response = raw_response[7:].strip()
        elif raw_response.startswith("```"):
            raw_response = raw_response[3:].strip()
        if raw_response.endswith("```"):
            raw_response = raw_response[:-3].strip()
        
        # Find JSON array
        start = raw_response.find("[")
        if start == -1:
            raise ValueError("No JSON array found in response")
        
        depth = 0
        end = -1
        for idx in range(start, len(raw_response)):
            char = raw_response[idx]
            if char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    end = idx + 1
                    break
        
        if end == -1:
            raise ValueError("Incomplete JSON array")
        
        json_str = raw_response[start:end]
        import json
        parsed_cards = json.loads(json_str)
        
        print(f"Successfully parsed {len(parsed_cards)} cards from enhanced processing")
        
        # Ensure we have exactly 9 cards
        if len(parsed_cards) != 9:
            print(f"Warning: Expected 9 cards, got {len(parsed_cards)}")
            # Pad or trim to 9
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
                    "notes": "card not detected in enhanced processing"
                })
            parsed_cards = parsed_cards[:9]
        
        # Log successful completion with consolidated details
        logger.log_grid_processing(
            filename, 
            "complete", 
            cards_detected=len(parsed_cards), 
            method="enhanced"
        )
        
        return parsed_cards, preprocessed_image_b64
        
    except Exception as e:
        error_msg = f"Enhanced grid processing failed: {str(e)}"
        print(error_msg)
        
        # Log failure with consolidated error details
        logger.log_grid_processing(filename, "fail", error=error_msg, method="enhanced")
        
        # Return default 9 cards if parsing fails
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
                "notes": f"enhanced processing failed at position {i}"
            })
        
        return default_cards, ""
