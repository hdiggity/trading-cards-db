"""
Enhanced processing system for 3x3 grid card back images with front image matching
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional
from dataclasses import dataclass
from PIL import Image
import base64
from io import BytesIO

from .utils import convert_image_to_supported_format, client, build_system_prompt, llm_chat
import os
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
from .accuracy import CardValidator, ConfidenceScorer, detect_card_era_and_type
from .tcdb_scraper import search_tcdb_cards
from .value_estimator import add_value_estimation
from .enhanced_grid_processor import process_enhanced_3x3_grid
from .detailed_grid_processor import process_detailed_3x3_grid

@dataclass
class GridCard:
    """Represents a card extracted from a grid with position info"""
    position: int  # 0-8 for 3x3 grid (top-left to bottom-right)
    row: int       # 0-2
    col: int       # 0-2
    data: Dict[str, Any]
    confidence: float = 0.0
    matched_front: Optional[str] = None  # Path to matched front image


class GridProcessor:
    """Enhanced processor for 3x3 grid card back images"""
    
    def __init__(self):
        self.validator = CardValidator()
        self.scorer = ConfidenceScorer()
        
    def build_grid_prompt(self, era_context: Dict[str, Any] = None) -> str:
        """Build specialized prompt for 3x3 grid processing"""
        
        era_guidance = ""
        if era_context:
            era = era_context.get('era', 'modern')
            sport = era_context.get('sport', 'baseball')
            
            if era == 'vintage':
                era_guidance = """
VINTAGE CARD GRID ANALYSIS (Pre-1980):
- Cards in a 3x3 grid are typically from the same set/year
- Copyright years will be consistent across the grid (within 1-2 years)
- Use context from clearer cards to help identify unclear ones
- Vintage card backs often have simple layouts with basic stats
- Player names are usually at the top in ALL CAPS or simple fonts
- Look for pattern consistency: if 8 cards are 1975 Topps, the 9th likely is too
"""
            elif era == 'classic':
                era_guidance = """
CLASSIC ERA GRID ANALYSIS (1980-2000):
- Grid cards are typically from same set/manufacturer
- Copyright information became more standardized
- Use set context to improve individual card identification
- Brand consistency across grid helps validate individual card data
- Player statistics can help cross-reference with known career data
"""
            else:
                era_guidance = """
MODERN CARD GRID ANALYSIS (2000+):
- High-quality printing makes text more readable
- Copyright information should be clearly visible
- Cards likely from same product/release
- Use clear cards to establish context for unclear ones
"""
        
        return f"""You are analyzing a 3x3 grid of trading card BACKS (9 cards total).

GRID ANALYSIS STRATEGY:
1. Systematically analyze each card position (top-left to bottom-right)
2. Look for pattern consistency across the grid (same set, year, brand)
3. Use context from clearly readable cards to help identify unclear ones
4. Each card should have DIFFERENT player information

{era_guidance}

CRITICAL REQUIREMENTS:
- Count exactly 9 cards and return 9 JSON objects
- Use grid position context: if 8 cards are clearly 1975 Topps, assume the 9th is too
- Apply consistent set/brand identification across the grid
- For unclear player names, use team + year + visible stats to identify from baseball history
- Cross-reference jersey numbers, positions, and stats across the grid for accuracy

CARD BACK IDENTIFICATION TECHNIQUES:
- Player names typically at top of card back
- Statistical tables often include player name headers
- Biographical sections mention player names multiple times
- Career highlights reference player achievements with names
- Use visible statistics (BA, ERA, HRs) + team + year to identify specific players
- Example: ".305 BA" + "Yankees" + "1975" = specific identifiable player

For each card in the grid (position 0-8), analyze:
- Position in grid (0=top-left, 1=top-center, ..., 8=bottom-right)
- Player name (make maximum effort using all available clues)
- Team (consistent with year and known team histories)
- Copyright year (look for © symbol, ignore stats years)
- Brand (should be consistent across grid)
- Card number
- Condition (assess each card individually)
- Sport (likely consistent across grid)
- Set name (typically same across grid)

Return JSON array with 9 objects:
{{
  "grid_position": 0-8,
  "name": "player name or card title",
  "sport": "baseball/basketball/football/hockey", 
  "brand": "topps/panini/upper deck/etc",
  "number": "card number",
  "copyright_year": "production year (© symbol)",
  "team": "team name",
  "card_set": "set name",
  "condition": "condition assessment",
  "is_player_card": true/false,
  "features": "none or comma-separated features",
  "notes": "any additional observations or null"
}}

ACCURACY MANDATE: Use ALL visible information and context clues. Grid consistency helps validate individual card accuracy."""

    def process_3x3_grid(self, image_path: str, front_images_dir: Path = None) -> Tuple[List[GridCard], List[Dict]]:
        """
        Process a 3x3 grid of card backs (PRIMARY) with optional front image matching (BACKUP)
        
        Data Priority:
        1. PRIMARY: 3x3 grid back extraction (enhanced preprocessing + GPT analysis)  
        2. BACKUP: Front image matching to supplement missing data only
        3. CONTEXT: Apply grid consistency patterns
        
        Returns: (grid_cards, raw_data)
        """
        print(f"Processing 3x3 grid as PRIMARY input: {image_path}", file=sys.stderr)
        
        # STEP 1: Detailed individual card processing (PRIMARY data source)
        print("Using detailed individual card processing for maximum detail extraction...", file=sys.stderr)
        try:
            detailed_data, _ = process_detailed_3x3_grid(image_path)
            raw_data = detailed_data
            print(f"Detailed processing extracted {len(raw_data)} cards", file=sys.stderr)
        except Exception as e:
            print(f"Detailed processing failed, trying enhanced processing: {e}", file=sys.stderr)
            try:
                enhanced_data, _ = process_enhanced_3x3_grid(image_path)
                raw_data = enhanced_data
                print(f"Enhanced processing extracted {len(raw_data)} cards", file=sys.stderr)
            except Exception as e2:
                print(f"Enhanced processing also failed, falling back to standard: {e2}", file=sys.stderr)
            # Fallback to standard processing
            encoded_image, mime_type = convert_image_to_supported_format(image_path, apply_preprocessing=True)
            grid_prompt = self.build_grid_prompt()
            
            messages = [
                {"role": "system", "content": grid_prompt},
                {
                    "role": "user", 
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{encoded_image}"}
                        }
                    ]
                }
            ]
            
            response = llm_chat(
                messages=messages,
                max_tokens=4000,
                temperature=0.1,
            )
            
            raw_response = response.choices[0].message.content.strip()
            raw_data = self._parse_grid_response(raw_response)
        
        # Ensure exactly 9 cards (3x3 grid requirement)
        if len(raw_data) != 9:
            print(f"Adjusting card count: Expected 9 cards, got {len(raw_data)}", file=sys.stderr)
            while len(raw_data) < 9:
                raw_data.append(self._create_default_card(len(raw_data)))
            raw_data = raw_data[:9]
        
        # STEP 2: Apply context-based enhancements (grid consistency)
        enhanced_data = self._apply_grid_context_enhancement(raw_data)
        
        # Validate and score cards (prioritizing back data)
        validated_data = self.validator.validate_and_correct(enhanced_data)
        scored_data = self.scorer.score_extraction(validated_data)
        
        # Add value estimation to each card
        scored_data = [add_value_estimation(card) for card in scored_data]
        
        # Create GridCard objects
        grid_cards = []
        for i, card_data in enumerate(scored_data):
            grid_card = GridCard(
                position=i,
                row=i // 3,
                col=i % 3,
                data=card_data,
                confidence=card_data.get('_overall_confidence', 0.5)
            )
            grid_cards.append(grid_card)
        
        # STEP 4: Match with front images as BACKUP data source (supplements missing info only)
        if front_images_dir and front_images_dir.exists():
            print(f"Using front images as BACKUP to supplement missing data from backs...", file=sys.stderr)
            grid_cards = self._match_front_images(grid_cards, front_images_dir)
        else:
            print("No front images directory provided - using back data only", file=sys.stderr)
        
        print(f"Grid processing completed: {len(grid_cards)} cards processed", file=sys.stderr)
        return grid_cards, raw_data
    
    def _parse_grid_response(self, response: str) -> List[Dict]:
        """Parse GPT response for grid cards"""
        try:
            # Clean up response
            if response.startswith("```json"):
                response = response[7:].strip()
            elif response.startswith("```"):
                response = response[3:].strip()
            if response.endswith("```"):
                response = response[:-3].strip()
            
            # Find JSON array
            start = response.find("[")
            if start == -1:
                raise ValueError("No JSON array found")
            
            depth = 0
            for idx in range(start, len(response)):
                char = response[idx]
                if char == "[":
                    depth += 1
                elif char == "]":
                    depth -= 1
                    if depth == 0:
                        json_str = response[start:idx + 1]
                        break
            else:
                raise ValueError("Incomplete JSON array")
            
            parsed = json.loads(json_str)
            if isinstance(parsed, dict):
                parsed = [parsed]
                
            return parsed
            
        except Exception as e:
            print(f"Error parsing grid response: {e}", file=sys.stderr)
            return [self._create_default_card(i) for i in range(9)]
    
    def _create_default_card(self, position: int) -> Dict:
        """Create a default card entry for missing data"""
        return {
            "grid_position": position,
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
            "notes": None
        }
    
    def _apply_grid_context_enhancement(self, cards: List[Dict]) -> List[Dict]:
        """Apply context-based enhancement using grid patterns"""
        enhanced_cards = []
        
        # Analyze patterns across the grid
        years = [c.get('copyright_year') for c in cards if c.get('copyright_year') and c.get('copyright_year') != 'unknown']
        brands = [c.get('brand') for c in cards if c.get('brand') and c.get('brand') != 'unknown']
        sports = [c.get('sport') for c in cards if c.get('sport') and c.get('sport') != 'unknown']
        sets = [c.get('card_set') for c in cards if c.get('card_set') and c.get('card_set') != 'unknown']
        
        # Determine most common values
        common_year = self._most_common(years)
        common_brand = self._most_common(brands)
        common_sport = self._most_common(sports)
        common_set = self._most_common(sets)
        
        print(f"Grid context: year={common_year}, brand={common_brand}, sport={common_sport}, set={common_set}", file=sys.stderr)
        
        for card in cards:
            enhanced_card = card.copy()
            
            # Apply common values where missing
            if not enhanced_card.get('copyright_year') or enhanced_card.get('copyright_year') == 'unknown':
                if common_year:
                    enhanced_card['copyright_year'] = common_year
                    print(f"Applied grid year context: {common_year}")
            
            if not enhanced_card.get('brand') or enhanced_card.get('brand') == 'unknown':
                if common_brand:
                    enhanced_card['brand'] = common_brand
                    print(f"Applied grid brand context: {common_brand}")
            
            if not enhanced_card.get('sport') or enhanced_card.get('sport') == 'unknown':
                if common_sport:
                    enhanced_card['sport'] = common_sport
                    print(f"Applied grid sport context: {common_sport}")
            
            if not enhanced_card.get('card_set') or enhanced_card.get('card_set') == 'unknown':
                if common_set:
                    enhanced_card['card_set'] = common_set
                    print(f"Applied grid set context: {common_set}")
            
            enhanced_cards.append(enhanced_card)
        
        return enhanced_cards
    
    def _most_common(self, items: List) -> Optional[str]:
        """Find most common item in list"""
        if not items:
            return None
        
        counts = {}
        for item in items:
            if item:
                counts[str(item)] = counts.get(str(item), 0) + 1
        
        if not counts:
            return None
            
        return max(counts, key=counts.get)
    
    def _match_front_images(self, grid_cards: List[GridCard], front_images_dir: Path) -> List[GridCard]:
        """Match grid cards with front images using AI vision comparison"""
        print(f"Matching front images from {front_images_dir}", file=sys.stderr)
        import os
        if os.getenv("DISABLE_FRONT_MATCH", "false").lower() == "true":
            print("Front matching disabled via DISABLE_FRONT_MATCH", file=sys.stderr)
            return grid_cards
        
        # Collect candidate front images
        front_images = (
            list(front_images_dir.glob("*.jpg"))
            + list(front_images_dir.glob("*.png"))
            + list(front_images_dir.glob("*.heic"))
        )
        if not front_images:
            print("No front images found for matching", file=sys.stderr)
            return grid_cards
        
        # Limit matching set to avoid excessive API calls; default 60
        try:
            max_candidates = int(os.getenv("FRONT_MATCH_MAX", "60"))
        except Exception:
            max_candidates = 60
        
        total_front = len(front_images)
        if total_front > max_candidates:
            # Heuristic: prefer most recently modified files (likely recent uploads)
            front_images.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            front_images = front_images[:max_candidates]
            print(
                f"Found {total_front} front images; limiting to {len(front_images)} most recent for matching",
                file=sys.stderr,
            )
        else:
            print(f"Found {total_front} front images for matching", file=sys.stderr)
        
        # Process front images to extract basic info
        front_cards_info = []
        for front_img in front_images:
            try:
                front_info = self._extract_front_card_info(front_img)
                front_info['_filename'] = front_img.name  # Store filename for reference
                front_cards_info.append({
                    'path': front_img,
                    'info': front_info
                })
            except Exception as e:
                print(f"Error processing front image {front_img}: {e}", file=sys.stderr)
                continue
        
        # Match grid cards with front images
        for grid_card in grid_cards:
            best_match = self._find_best_front_match(grid_card, front_cards_info)
            if best_match:
                grid_card.matched_front = str(best_match['path'])
                # Enhance grid card data with front card info
                grid_card.data = self._merge_front_back_data(grid_card.data, best_match['info'])
                print(f"Matched grid position {grid_card.position} with {best_match['path'].name}")
        
        return grid_cards
    
    def _extract_front_card_info(self, front_image_path: Path) -> Dict[str, Any]:
        """Extract basic info from a front card image"""
        encoded_image, mime_type = convert_image_to_supported_format(str(front_image_path))
        
        front_prompt = """Analyze this trading card FRONT and extract basic information:

Return JSON with:
{
  "name": "player name if visible",
  "team": "team name from logo/uniform", 
  "sport": "sport type",
  "era": "vintage/classic/modern based on design",
  "uniform_number": "jersey number if visible",
  "brand_visible": "any brand logos visible",
  "distinguishing_features": "unique visual elements"
}

Focus on information that would help match this front with a corresponding back."""
        
        messages = [
            {"role": "system", "content": front_prompt},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{encoded_image}"}
                    }
                ]
            }
        ]
        
        response = llm_chat(
            messages=messages,
            max_tokens=500,
            temperature=0.1,
        )
        
        try:
            content = response.choices[0].message.content.strip()
            if content.startswith("```json"):
                content = content[7:].strip()
            if content.endswith("```"):
                content = content[:-3].strip()
            
            return json.loads(content)
        except:
            return {"name": "unknown", "team": "unknown", "sport": "baseball"}
    
    def _find_best_front_match(self, grid_card: GridCard, front_cards: List[Dict]) -> Optional[Dict]:
        """Find the best matching front card for a grid card"""
        back_data = grid_card.data
        best_match = None
        best_score = 0
        
        for front_card in front_cards:
            front_info = front_card['info']
            score = self._calculate_match_score(back_data, front_info)
            
            if score > best_score and score > 0.3:  # Minimum threshold
                best_score = score
                best_match = front_card
        
        return best_match
    
    def _calculate_match_score(self, back_data: Dict, front_info: Dict) -> float:
        """Calculate matching score between back and front card data"""
        score = 0.0
        matches = 0
        total_checks = 0
        
        # Name matching (if both have names)
        back_name = str(back_data.get('name', '')).lower().strip()
        front_name = str(front_info.get('name', '')).lower().strip()
        
        if back_name and front_name and back_name != 'unknown' and front_name != 'unknown':
            total_checks += 1
            if back_name in front_name or front_name in back_name:
                score += 0.4
                matches += 1
        
        # Team matching
        back_team = str(back_data.get('team', '')).lower().strip()
        front_team = str(front_info.get('team', '')).lower().strip()
        
        if back_team and front_team and back_team != 'unknown' and front_team != 'unknown':
            total_checks += 1
            if back_team in front_team or front_team in back_team:
                score += 0.3
                matches += 1
        
        # Sport matching
        back_sport = str(back_data.get('sport', '')).lower()
        front_sport = str(front_info.get('sport', '')).lower()
        
        if back_sport and front_sport:
            total_checks += 1
            if back_sport == front_sport:
                score += 0.2
                matches += 1
        
        # Era consistency (basic check)
        back_year = back_data.get('copyright_year')
        front_era = front_info.get('era')
        
        if back_year and front_era:
            total_checks += 1
            try:
                year_int = int(str(back_year))
                if ((year_int < 1980 and front_era == 'vintage') or
                    (1980 <= year_int < 2000 and front_era == 'classic') or
                    (year_int >= 2000 and front_era == 'modern')):
                    score += 0.1
                    matches += 1
            except:
                pass
        
        # Normalize score
        if total_checks > 0:
            return score / max(total_checks * 0.25, 1.0)  # Scale to 0-1 range
        
        return 0.0
    
    def _merge_front_back_data(self, back_data: Dict, front_info: Dict) -> Dict:
        """
        Merge front card info with back card data with back data as primary source
        Back data takes priority - front data only supplements missing information
        """
        merged = back_data.copy()
        
        # PRIORITY 1: Back data is primary - only supplement if truly missing
        back_name = str(back_data.get('name', '')).lower()
        front_name = front_info.get('name', '')
        
        # Only use front name if back name is completely missing/unclear
        if (back_name in ['unknown', 'unidentified', 'n/a', '', 'none'] and 
            front_name and front_name not in ['unknown', 'unidentified']):
            merged['name'] = front_name
            merged['_name_source'] = 'front_supplemented'
            print(f"Supplemented name from front image: {front_name}")
        else:
            merged['_name_source'] = 'back_primary'
        
        # Only use front team if back team is missing
        back_team = str(back_data.get('team', '')).lower()
        front_team = front_info.get('team', '')
        
        if (back_team in ['unknown', 'n/a', '', 'none'] and 
            front_team and front_team not in ['unknown', 'unidentified']):
            merged['team'] = front_team
            merged['_team_source'] = 'front_supplemented'
            print(f"Supplemented team from front image: {front_team}")
        else:
            merged['_team_source'] = 'back_primary'
        
        # Record matched front file (always add if matched)
        merged['matched_front_file'] = front_info.get('_filename')
        
        # Add supplemental matching metadata (for verification/debugging)
        merged['_front_match'] = {
            'matched_file': True,
            'front_name': front_info.get('name'),
            'front_team': front_info.get('team'),
            'uniform_number': front_info.get('uniform_number'),
            'data_priority': 'back_primary_front_supplemental'
        }
        
        return merged


def save_grid_cards_to_verification(
    grid_cards: List[GridCard],
    out_dir: Path,
    filename_stem: str = None,
    include_tcdb_verification: bool = True,
    save_cropped_backs: bool = False,
    original_image_path: str = None
):
    """Save grid cards to verification with enhanced metadata"""
    out_dir.mkdir(exist_ok=True)
    
    # Convert GridCard objects to dicts for JSON serialization
    cards_data = []
    for grid_card in grid_cards:
        card_dict = grid_card.data.copy()
        
        # Add grid-specific metadata
        card_dict['_grid_metadata'] = {
            'position': grid_card.position,
            'row': grid_card.row,
            'col': grid_card.col,
            'confidence': grid_card.confidence,
            'matched_front': grid_card.matched_front
        }
        
        cards_data.append(card_dict)
    
    # Apply TCDB verification if requested
    if include_tcdb_verification:
        try:
            print("Adding TCDB verification to grid cards...", file=sys.stderr)
            from .utils import verify_cards_with_tcdb
            cards_data = verify_cards_with_tcdb(cards_data)
        except Exception as e:
            print(f"TCDB verification failed: {e}", file=sys.stderr)
    
    # Save to file using SAME basename as source image so UI associates JSON↔image
    filename = out_dir / (
        f"{filename_stem}.json" if filename_stem else f"grid_{len(cards_data)}_cards.json"
    )
    
    with open(filename, "w") as f:
        json.dump(cards_data, f, indent=2)
    
    # Optionally save cropped individual back images
    if save_cropped_backs and original_image_path:
        try:
            cropped_dir = out_dir / "cropped_backs"
            cropped_dir.mkdir(exist_ok=True)
            _extract_and_save_individual_backs(original_image_path, grid_cards, cropped_dir, filename_stem)
        except Exception as e:
            print(f"Failed to save cropped backs: {e}", file=sys.stderr)
    
    print(f"Saved {len(cards_data)} grid cards to {filename}")
    return filename.stem


def _extract_and_save_individual_backs(image_path: str, grid_cards: List[GridCard], 
                                     output_dir: Path, filename_stem: str):
    """Extract and save individual card backs from 3x3 grid"""
    try:
        # Load original image
        img = Image.open(image_path)
        width, height = img.size
        
        # Calculate grid dimensions (3x3)
        card_width = width // 3
        card_height = height // 3
        
        for grid_card in grid_cards:
            # Calculate crop coordinates
            col = grid_card.col
            row = grid_card.row
            
            left = col * card_width
            top = row * card_height
            right = left + card_width
            bottom = top + card_height
            
            # Crop individual card
            cropped_card = img.crop((left, top, right, bottom))
            
            # Generate filename
            card_name = grid_card.data.get('name', 'unknown').replace(' ', '_')
            card_number = grid_card.data.get('number', 'no_num')
            crop_filename = f"{filename_stem}_pos{grid_card.position}_{card_name}_{card_number}.png"
            
            # Save cropped image
            crop_path = output_dir / crop_filename
            cropped_card.save(crop_path, "PNG")
            
            print(f"Saved cropped back: {crop_filename}")
            
    except Exception as e:
        print(f"Error extracting individual backs: {e}", file=sys.stderr)
