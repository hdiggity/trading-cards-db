import base64
import json
import os
import re
import sys
import uuid
from io import BytesIO
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image
from pillow_heif import register_heif_opener

from app.accuracy import (
    CardValidator,
    ConfidenceScorer,
    build_specialized_prompt,
    detect_card_era_and_type,
)
from app.database import SessionLocal
from app.fields import shared_card_field_specs
from app.learning import generate_learning_prompt_enhancements
from app.models import Card
from app.schemas import CardCreate  # make sure this import exists
from app.tcdb_scraper import search_tcdb_cards

# Import image enhancement functions from single_card analysis
try:
    import cv2
    import numpy as np
    from .image_enhancement import enhance_image_for_ocr, adaptive_preprocessing, create_high_contrast_version
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    print("OpenCV not available, image preprocessing disabled", file=sys.stderr)

# setup
load_dotenv()
register_heif_opener()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def build_legacy_system_prompt(include_learning: bool = True) -> str:
    # generate system prompt with field descriptions from fields.py
    description_map = {
        "name": "player's full name. if multiple people appear on the card, include each as separate entries with identical card details.",
        "sport": "what sport the individual played in the year that the trading card is from, or detect based on the card",
        "brand": "e.g., 'Topps', 'Donruss', 'Upper Deck', 'Panini', 'Leaf', and common card brands",
        "number": "card number if available",
        "copyright_year": "CRITICAL: Find the TRUE copyright/production year, NOT statistics years. Look ONLY for: 1) Copyright symbol (©) followed by year - this is ALWAYS the production year, 2) Fine print text at card edges/corners with year, 3) Brand logo with year (like 'Topps 1975'), 4) Set identifier year. IGNORE all other years including: player career stats, birth years, team years, statistical data years. The copyright year is typically much smaller text and may be on edges/borders. For vintage cards, copyright is often tiny text at bottom edge. If you see both '© 1975' and '1974 stats', use 1975. If uncertain, look for the smallest, least prominent year - that's usually copyright.",
        "team": "mlb team from the year that the card is from, inferred from card text or player history if not directly visible. never leave blank—make your best guess based on the image.",
        "card_set": "set name or series, default to N/A, but the card_set is the subset of the brand",
        "condition": """CRITICAL: Perform a detailed, systematic condition assessment using professional grading standards. Examine the card under good lighting and look for ALL defects:

        CORNERS (Most Important):
        - Sharp, pointed corners = Mint level
        - Slightly touched corners = Near Mint
        - Light rounding/fuzzing = Excellent
        - Moderate rounding = Very Good
        - Heavy rounding/chipping = Good or lower

        EDGES:
        - Smooth, clean edges = Mint level
        - Minor roughness = Near Mint/Excellent
        - Visible nicks, cuts = Very Good or lower
        - Severe edge damage = Fair/Poor

        SURFACE:
        - Pristine, scratch-free = Mint level
        - Minor print spots = Near Mint
        - Light scratches/scuffs = Excellent/Very Good
        - Heavy scratches, stains = Good or lower
        - Writing, tape residue = Fair/Poor

        CENTERING:
        - Perfectly centered = Mint level
        - Slightly off-center = Near Mint
        - Noticeably off-center = Excellent/Very Good
        - Severely off-center = Good or lower

        PRINT QUALITY:
        - Sharp, vibrant colors = Higher grades
        - Slight color fade = Lower by 1-2 grades
        - Print defects, spots = Significant grade reduction

        GRADING SCALE (Be conservative - err on lower side):
        - 'gem_mint' (10): PERFECT in all aspects - extremely rare for vintage cards
        - 'mint' (9): Near perfect, only microscopic flaws allowed
        - 'near_mint' (8): Slight wear visible but overall excellent condition
        - 'excellent' (7): Light wear on corners/edges, minor surface issues
        - 'very_good' (6): Moderate wear visible, still attractive card
        - 'good' (5): Obvious wear but card is intact and displayable
        - 'fair' (4): Heavy wear, creases, but card is complete
        - 'poor' (3): Extensive damage, major creases, writing, or missing pieces

        VINTAGE CARD CONSIDERATIONS:
        - Cards from 1970s-1980s rarely grade above Very Good due to printing/storage
        - Consider age when assessing - slight age-related wear is normal
        - Focus on most damaged aspect to determine overall grade""",
        "is_player_card": "true if this is a player card (individual athlete), false if this is a non-player card such as a checklist, team card, or highlight card",
        "features": "comma-separated list of special features from these options: 'rookie', 'autograph', 'jersey', 'parallel', 'refractor', 'chrome', 'limited edition', 'serial numbered', 'prospect', 'hall of fame', 'insert', 'short print'. Use 'none' if no special features. Multiple features should be comma-separated like 'rookie,autograph'",
        "notes": "optional field for any additional observations, anomalies, or important details about the card that don't fit in other fields. Use null if no special notes needed.",
    }

    # Use field names from fields.py to ensure consistency
    field_names = [field_spec[0] for field_spec in shared_card_field_specs]
    field_lines = [
        f'  "{field}": ...,  # {description_map.get(field, "field description")}'
        for field in field_names
    ]
    joined_fields = "\n".join(field_lines)
    return (
        "You are an expert sports card analyst extracting data from trading cards in an image. The cards may show fronts, backs, or a mix of both.\n"
        "CRITICAL: First, carefully count how many cards are visible in the image and output exactly that number of JSON objects.\n"
        "CRITICAL: Each card is a DIFFERENT player with DIFFERENT details - do not use identical values for all cards.\n"
        "Analyze each card individually using whatever information is visible (names, uniforms, logos, text, etc.).\n"
        "If a card features multiple players, output one object per player with identical card details.\n"
        "Scan the grid systematically (top-left to bottom-right), ensuring you analyze every card present.\n\n"
        "CRITICAL ACCURACY REQUIREMENTS:\n\n"
        "COPYRIGHT YEAR DETECTION (MOST IMPORTANT):\n"
        "- Find ONLY the copyright/production year, ignore ALL statistics years\n"
        "- Look for copyright symbol (©) + year - this is ALWAYS correct\n"
        "- Check card edges/borders for tiny copyright text\n"
        "- Brand logos often include production year (e.g., 'Topps 1975')\n"
        "- Copyright year is usually the SMALLEST, least prominent date\n"
        "- NEVER use years from: player stats, career highlights, team rosters\n"
        "- Example: If card shows '1974 batting average' but has '© 1975', use 1975\n"
        "- For vintage cards: copyright is often microscopic text at bottom\n"
        "- When multiple years visible, the copyright is typically 1 year LATER than stats\n\n"
        "CONDITION ASSESSMENT PRIORITY:\n"
        "Perform professional-grade condition assessment. Be systematic and thorough:\n"
        "- Examine ALL FOUR CORNERS individually for sharpness/rounding\n"
        "- Check ALL FOUR EDGES for nicks, cuts, or roughness\n"
        "- Scan entire surface for scratches, stains, print defects\n"
        "- Assess centering by comparing border widths on all sides\n"
        "- Look for creases, bends, or other structural damage\n"
        "- Consider card age - vintage cards rarely achieve mint grades\n"
        "- When in doubt, grade conservatively (lower grade)\n\n"
        "return a JSON array with one object per card (or per player-card combination) with these fields:\n\n"
        "{\n" f"{joined_fields}\n" "}\n\n"
        "ACCURACY MANDATE:\n"
        "- Use ALL available visual information in the image\n"
        "- Read ALL text visible on each card, including microscopic fine print\n"
        "- Cross-reference multiple clues to determine correct information\n"
        "- For copyright year: ONLY use copyright symbols, brand marks, or production indicators\n"
        "- COMPLETELY IGNORE statistics years, player career years, team years\n"
        "- The copyright year determines when the card was MADE, not when the player played\n"
        "- Look at card borders, edges, and corners for tiny copyright text\n"
        "- For condition: examine every aspect systematically, be conservative in grading\n"
        "- If uncertain about copyright year, look for the least prominent, smallest year visible\n\n"
        "OUTPUT FORMAT:\n"
        "Only return valid JSON. If a value is missing or unreadable, infer it if possible; otherwise use 'n/a' (as a string). Never leave fields blank.\n"
        "Be conservative with condition grading - err on the side of lower grades when in doubt.\n"
        "CRITICAL: copyright_year must be the card production year (from © symbol or brand mark), never player statistics years.\n\n"
        "⚠️  FINAL REMINDER: DO NOT use identical values for different cards. Each card represents a different player!")

    # Add learning enhancements if requested
    if include_learning:
        try:
            learning_enhancements = generate_learning_prompt_enhancements()
            if learning_enhancements:
                return base_prompt + learning_enhancements
        except Exception as e:
            print(
                f"Warning: Could not load learning enhancements: {e}",
                file=sys.stderr)

    return base_prompt


def build_system_prompt(include_learning: bool = True) -> str:
    """Build concise system prompt for card extraction"""
    field_names = [field_spec[0] for field_spec in shared_card_field_specs]
    field_lines = [f'  "{field}": ...' for field in field_names]
    joined_fields = "\n".join(field_lines)
    
    return (
        "Extract trading card data from the image. Count visible cards and analyze each one.\n\n"
        "Return JSON array with one object per card:\n"
        "{\n" f"{joined_fields}\n" "}\n\n"
        "Key requirements:\n"
        "- name: SPECIFIC card title/subject (e.g., '1973 Rookie First Basemen', 'Al Rosen', 'NL Batting Leaders'). For multi-player cards, use the card's title, not individual names.\n"
        "- card_set: The ACTUAL trading card set/series (e.g., '1973 Topps', '1975 Topps', '1989 Upper Deck'). This is usually the main brand + year, NOT specialty subsets.\n"
        "- copyright_year: Find actual production year (© symbol, brand marks), not player stats years\n"
        "- condition: Assess corners, edges, surface damage. Use: gem_mint/mint/near_mint/excellent/very_good/good/fair/poor\n"
        "- is_player_card: true for individual athletes, false for team/checklist/leaders cards\n"
        "- features: Use 'none' or comma-separated values like 'rookie,autograph'\n\n"
        "IMPORTANT: Distinguish card NAME (what's on the card) from card SET (the product line it belongs to).\n"
        "Use 'n/a' for missing values. Never use 'unspecified' or 'unidentified'. Be accurate and specific for each card."
    )


SYSTEM_PROMPT = build_system_prompt()


def build_reprocessing_prompt(_previous_data):
    """Build a focused prompt for reprocessing with key corrections"""

    # Build a completely fresh, focused prompt for reprocessing
    reprocessing_prompt = f"""
Analyze each trading card individually in this image.

Count cards visible and analyze each one separately:
- Player name (check text, jersey, nameplate)
- Team (logos, colors, text)
- Year (© symbol, small print)
- Card number
- Brand (Topps, Panini, etc.)
- Condition (corners, edges, surface)

Return JSON array with one object per card:
{{"name": "SPECIFIC card title/subject (e.g., '1973 Rookie First Basemen', 'Al Rosen', 'NL Batting Leaders')",
  "sport": "baseball/basketball/football/hockey", 
  "brand": "card brand",
  "number": "card number or null",
  "copyright_year": "production year",
  "team": "team name",
  "card_set": "ACTUAL trading card set (e.g., '1973 Topps', '1975 Topps') - the main product line",
  "condition": "mint/near_mint/excellent/very_good/good/fair/poor",
  "is_player_card": true,
  "features": "none"}}

IMPORTANT: For card NAME use what's actually printed on the card. For card SET use the main trading card product line (usually brand + year).
"""

    return reprocessing_prompt


def extract_json_array(text: str) -> str:
    # remove markdown fences if present
    text = re.sub(r"```json|```", "", text)
    # find the first '['
    start = text.find("[")
    if start == -1:
        raise ValueError("no valid json array found in response")
    depth = 0
    # scan for matching closing bracket
    for idx in range(start, len(text)):
        char = text[idx]
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return text[start: idx + 1]
    raise ValueError("no valid json array found in response")


def safe_parse_json_array(raw: str) -> list:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # try to salvage a partial list
        raw = raw.rstrip(", \n\r\t")
        while raw and raw[-1] != "}":
            raw = raw[:-1]
        try:
            return json.loads(raw + "]")
        except Exception as inner:
            raise ValueError("Could not recover truncated JSON") from inner


def convert_image_to_supported_format(
    image_path: str, apply_preprocessing: bool = True, _card_era: str = None
) -> tuple[str, str]:
    """Convert image to JPEG format for GPT-4 Vision with optional preprocessing"""
    path_obj = Path(image_path)
    file_extension = path_obj.suffix.lower()

    if file_extension == ".heic":
        # Convert HEIC to JPEG
        image = Image.open(image_path)
        output_buffer = BytesIO()
        image.convert("RGB").save(output_buffer, format="JPEG", quality=95)
        image_data = output_buffer.getvalue()
        mime_type = "image/jpeg"
    elif file_extension in [".jpg", ".jpeg"]:
        with open(image_path, "rb") as image_file:
            image_data = image_file.read()
        mime_type = "image/jpeg"
    elif file_extension == ".png":
        with open(image_path, "rb") as image_file:
            image_data = image_file.read()
        mime_type = "image/png"
    else:
        # Fallback: try to open with PIL and convert to JPEG
        try:
            image = Image.open(image_path)
            output_buffer = BytesIO()
            image.convert("RGB").save(output_buffer, format="JPEG", quality=95)
            image_data = output_buffer.getvalue()
            mime_type = "image/jpeg"
        except Exception as e:
            raise ValueError(f"Unsupported image format: {file_extension}") from e

    # Apply preprocessing if requested and OpenCV is available
    if apply_preprocessing and CV2_AVAILABLE:
        try:
            if _card_era:
                # Use era-specific preprocessing
                image_data = adaptive_preprocessing(image_data, _card_era)
                print(f"Applied {_card_era} era preprocessing", file=sys.stderr)
            else:
                # Use general enhancement
                image_data = enhance_image_for_ocr(image_data)
                print("Applied general image enhancement", file=sys.stderr)
        except Exception as e:
            print(f"Preprocessing failed, using original image: {e}", file=sys.stderr)
    elif apply_preprocessing and not CV2_AVAILABLE:
        print(
            "Image preprocessing requested but OpenCV not available",
            file=sys.stderr,
        )

    encoded_image = base64.b64encode(image_data).decode("utf-8")
    return encoded_image, mime_type


def gpt_extract_cards_from_image(
    image_path: str, previous_data=None
) -> tuple[list, list[CardCreate]]:
    """
    Extract card data from image with multi-pass validation and confidence scoring
    Returns: (raw_data, validated_card_creates)
    """
    # Initialize validation and scoring components
    validator = CardValidator()
    scorer = ConfidenceScorer()

    # Convert image to supported format for GPT-4 vision (initially without
    # era-specific preprocessing)
    encoded_image, mime_type = convert_image_to_supported_format(
        image_path, apply_preprocessing=True
    )

    # Use enhanced prompt if this is a reprocessing with previous data
    if previous_data:
        prompt_to_use = build_reprocessing_prompt(previous_data)
    else:
        # For initial extraction, use base prompt (specialized prompts need
        # data analysis first)
        prompt_to_use = SYSTEM_PROMPT

    # First pass: Initial extraction
    messages = [
        {"role": "system", "content": prompt_to_use},
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{encoded_image}"},
                }
            ],
        },
    ]

    response = client.chat.completions.create(
        model="gpt-4o", messages=messages, max_tokens=2000, temperature=0.1
    )

    try:
        raw_response = response.choices[0].message.content.strip()

        if raw_response.startswith("```json"):
            raw_response = raw_response[7:].strip()
        elif raw_response.startswith("```"):
            raw_response = raw_response[3:].strip()
        if raw_response.endswith("```"):
            raw_response = raw_response[:-3].strip()

        try:
            raw_json = extract_json_array(raw_response)
        except ValueError:
            # fallback to using entire response for parsing
            raw_json = raw_response
        parsed = safe_parse_json_array(raw_json)

        if isinstance(parsed, dict):
            parsed = [parsed]

        # Clean up the parsed data to handle GPT quirks
        for item in parsed:
            if isinstance(item, dict):
                item.pop("image_path", None)
                # Convert string "null" to actual None/False for boolean fields
                if (
                    item.get("is_player_card") == "null"
                    or item.get("is_player_card") is None
                ):
                    item["is_player_card"] = True  # Default to player card
                elif isinstance(item.get("is_player_card"), str):
                    item["is_player_card"] = item["is_player_card"].lower() in [
                        "true",
                        "yes",
                        "1",
                    ]

                # Ensure features field exists and has proper default
                if not item.get("features") or item.get("features") == "null":
                    item["features"] = "none"

        # Multi-pass validation and enhancement
        print(
            f"Initial extraction completed: {len(parsed)} cards detected",
            file=sys.stderr,
        )

        # Pass 1: Validate and auto-correct obvious errors
        validated_cards = validator.validate_and_correct(parsed)
        print(
            "Pass 1: Field validation and correction completed",
            file=sys.stderr)

        # Pass 1.2: Apply card back layout knowledge
        back_enhanced_cards = validator.apply_card_back_knowledge(
            validated_cards)
        print("Pass 1.2: Card back layout knowledge applied", file=sys.stderr)

        # Pass 1.5: Apply smart defaults based on context clues
        context_enhanced_cards = validator.apply_smart_defaults(
            back_enhanced_cards)
        print("Pass 1.5: Context-based smart defaults applied", file=sys.stderr)

        # Pass 2: Add confidence scores
        scored_cards = scorer.score_extraction(context_enhanced_cards)
        print("Pass 2: Confidence scoring completed", file=sys.stderr)

        # Pass 3: Check for low-confidence cards that might need re-extraction
        needs_reprocessing = []
        final_cards = []

        for card in scored_cards:
            overall_confidence = card.get("_overall_confidence", 0.5)
            confidence_scores = card.get("_confidence", {})

            # Flag cards with very low confidence in critical fields
            # Be less aggressive about reprocessing for names since they're
            # often unclear in vintage cards
            critical_low_confidence = (
                # Lower threshold for names
                confidence_scores.get("name", 1.0) < 0.25
                or confidence_scores.get("copyright_year", 1.0) < 0.5
                or overall_confidence < 0.35  # Lower overall threshold
            )

            if (
                critical_low_confidence and not previous_data
            ):  # Only reprocess on first pass
                needs_reprocessing.append(card)
                print(
                    f"Card '{card.get('name', 'unknown')}' flagged for reprocessing (confidence: {overall_confidence:.2f})",
                    file=sys.stderr,
                )
            else:
                final_cards.append(card)

        # Pass 4: Reprocess low-confidence cards with enhanced prompts
        if needs_reprocessing and not previous_data:
            print(
                f"Reprocessing {len(needs_reprocessing)} low-confidence cards...",
                file=sys.stderr,
            )

            # Detect card characteristics for specialized prompting
            card_context = detect_card_era_and_type(parsed[:3])
            print(
                f"Detected card context: {card_context['era']} era, {card_context['sport']} sport",
                file=sys.stderr,
            )

            # Apply era-specific preprocessing for reprocessing
            try:
                enhanced_image, _ = convert_image_to_supported_format(
                    image_path, apply_preprocessing=True, _card_era=card_context["era"])
                print(
                    f"Applied {card_context['era']} era preprocessing for reprocessing",
                    file=sys.stderr,
                )
            except Exception as e:
                print(
                    f"Era-specific preprocessing failed, using original: {e}",
                    file=sys.stderr,
                )
                enhanced_image = encoded_image

            # Build specialized prompt based on detected characteristics
            specialized_prompt = build_specialized_prompt(card_context)

            reprocess_messages = [
                {
                    "role": "system",
                    "content": specialized_prompt +
                    "\n\nFOCUS EXTRA ATTENTION ON ACCURACY - These cards had low confidence scores.",
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{enhanced_image}"},
                        }],
                },
            ]

            try:
                reprocess_response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=reprocess_messages,
                    max_tokens=2500,
                    temperature=0.1,
                )

                reprocess_content = reprocess_response.choices[
                    0
                ].message.content.strip()
                reprocess_json = extract_json_array(reprocess_content)
                reprocess_parsed = safe_parse_json_array(reprocess_json)

                if isinstance(reprocess_parsed, dict):
                    reprocess_parsed = [reprocess_parsed]

                # Validate and score reprocessed cards
                reprocess_validated = validator.validate_and_correct(
                    reprocess_parsed)
                reprocess_scored = scorer.score_extraction(reprocess_validated)

                # Use reprocessed results if confidence improved
                for i, reprocessed_card in enumerate(reprocess_scored):
                    if i < len(needs_reprocessing):
                        original_confidence = needs_reprocessing[i].get(
                            "_overall_confidence", 0.0
                        )
                        new_confidence = reprocessed_card.get(
                            "_overall_confidence", 0.0
                        )

                        if new_confidence > original_confidence:
                            final_cards.append(reprocessed_card)
                            print(
                                f"Improved confidence for '{reprocessed_card.get('name', 'unknown')}': {original_confidence:.2f} → {new_confidence:.2f}",
                                file=sys.stderr,
                            )
                        else:
                            final_cards.append(needs_reprocessing[i])
                            print(
                                f"Kept original for '{needs_reprocessing[i].get('name', 'unknown')}' (reprocessing didn't improve)",
                                file=sys.stderr,
                            )

                print(
                    "Pass 4: Low-confidence card reprocessing completed",
                    file=sys.stderr,
                )

            except Exception as e:
                print(
                    f"Reprocessing failed, using original results: {e}",
                    file=sys.stderr)
                final_cards.extend(needs_reprocessing)
        else:
            final_cards.extend(needs_reprocessing)  # Add any remaining cards

        # Final cleanup and prepare CardCreate objects
        clean_cards = []
        for card in final_cards:
            # Remove internal scoring fields before creating CardCreate
            clean_card = {
                k: v for k,
                v in card.items() if not k.startswith("_")}
            clean_cards.append(clean_card)

        print(
            f"Final extraction completed: {len(clean_cards)} cards with enhanced accuracy",
            file=sys.stderr,
        )

        return final_cards, [CardCreate(
            **item) for item in clean_cards if isinstance(item, dict)]

    except Exception as e:
        raise ValueError(f"failed to parse GPT response: {str(e)}") from e


def _enhance_card_with_tcdb_data(card: dict, tcdb_match: dict) -> dict:
    """
    Enhance extracted card data with information from TCDB match.
    This fills in missing fields and corrects likely errors.
    """
    enhanced_card = card.copy()
    enhanced_fields = []

    # Extract team from TCDB title if missing or seems wrong
    if not card.get("team") or card.get("team") in ["n/a", "unknown"]:
        if tcdb_match.get("team"):
            enhanced_card["team"] = tcdb_match["team"]
            enhanced_fields.append("team")

    # Cross-check year - if extracted year doesn't match TCDB, flag it
    if card.get("copyright_year") and tcdb_match.get("year"):
        extracted_year = str(card["copyright_year"]).strip()
        tcdb_year = str(tcdb_match["year"]).strip()

        # Allow for 1-year difference (common with card production timing)
        if abs(int(extracted_year) - int(tcdb_year)) > 1:
            enhanced_card["_year_discrepancy"] = {
                "extracted": extracted_year,
                "tcdb": tcdb_year,
                "note": "Year mismatch with TCDB - verify copyright vs. stats year",
            }

    # Enhance set information if missing
    if not card.get("card_set") or card.get("card_set") in ["n/a", "unknown"]:
        if tcdb_match.get("set"):
            enhanced_card["card_set"] = tcdb_match["set"]
            enhanced_fields.append("card_set")

    # Add TCDB metadata for reference
    enhanced_card["_tcdb_title"] = tcdb_match.get("title", "")
    enhanced_card["_enhanced_fields"] = enhanced_fields

    return enhanced_card


def verify_cards_with_tcdb(cards: list) -> list:
    """
    Verify card data against TCDB and add verification information.

    Args:
        cards: List of card dictionaries

    Returns:
        List of cards with TCDB verification data added
    """
    verified_cards = []

    for card in cards:
        try:
            # Build search query from card data
            query_parts = []

            if card.get("name") and card["name"] != "n/a":
                query_parts.append(card["name"])

            if card.get("copyright_year") and card["copyright_year"] != "n/a":
                query_parts.append(str(card["copyright_year"]))

            if card.get("team") and card["team"] != "n/a":
                query_parts.append(card["team"])

            if card.get("brand") and card["brand"] != "n/a":
                query_parts.append(card["brand"])

            # Skip verification for unidentified cards or insufficient data
            if (
                card.get("name") in ["unidentified", "unknown", "n/a"]
                or len(query_parts) < 2
            ):
                card_with_tcdb = card.copy()
                card_with_tcdb["_tcdb_verification"] = {
                    "search_query": "",
                    "results": [],
                    "verified": False,
                    "best_match": None,
                    "error": "Cannot verify unidentified or incomplete card data",
                }
                print(
                    f"Skipping TCDB verification for unidentified card",
                    file=sys.stderr)
                verified_cards.append(card_with_tcdb)
                continue

            search_query = " ".join(query_parts)
            print(f"Searching TCDB for: {search_query}", file=sys.stderr)

            # Search TCDB
            tcdb_results = search_tcdb_cards(search_query, max_results=3)

            # Add TCDB verification data to card
            card_with_tcdb = card.copy()

            if tcdb_results:
                # Enhancement: Use TCDB data to improve extracted information
                best_match = tcdb_results[0]
                enhanced_card = _enhance_card_with_tcdb_data(
                    card_with_tcdb, best_match)

                enhanced_card["_tcdb_verification"] = {
                    "search_query": search_query,
                    "results": tcdb_results,
                    "verified": True,
                    "best_match": best_match,
                    "enhanced_fields": enhanced_card.get(
                        "_enhanced_fields",
                        []),
                }

                print(
                    f"Found {len(tcdb_results)} TCDB matches for {card.get('name', 'unknown')}",
                    file=sys.stderr,
                )
                verified_cards.append(enhanced_card)
            else:
                card_with_tcdb["_tcdb_verification"] = {
                    "search_query": search_query,
                    "results": [],
                    "verified": False,
                    "best_match": None,
                    "error": "No matches found in TCDB",
                }
                print(
                    f"No TCDB matches found for {card.get('name', 'unknown')}",
                    file=sys.stderr,
                )
                verified_cards.append(card_with_tcdb)

        except Exception as e:
            print(
                f"TCDB verification failed for {card.get('name', 'unknown')}: {e}",
                file=sys.stderr,
            )
            # Add error info but continue
            card_with_tcdb = card.copy()
            card_with_tcdb["_tcdb_verification"] = {
                "search_query": "",
                "results": [],
                "verified": False,
                "best_match": None,
                # Limit error message length for JSON safety
                "error": str(e)[:200],
            }
            verified_cards.append(card_with_tcdb)

    return verified_cards


def save_cards_to_verification(
    cards: list,
    out_dir: Path,
    filename_stem: str = None,
    include_tcdb_verification: bool = True,
):
    out_dir.mkdir(exist_ok=True)

    # Add TCDB verification if requested
    if include_tcdb_verification:
        try:
            print("Adding TCDB verification to cards...", file=sys.stderr)
            cards = verify_cards_with_tcdb(cards)
        except Exception as e:
            print(
                f"TCDB verification failed, continuing without it: {e}",
                file=sys.stderr)

    # Handle cards that might include confidence data
    card_dicts = []
    for card in cards:
        if isinstance(card, dict):
            # Preserve confidence and verification data if present
            if (
                "_confidence" in card
                or "_overall_confidence" in card
                or "_tcdb_verification" in card
            ):
                # Save the full dict with all metadata
                clean_card = {k: v for k,
                              v in card.items() if not k.startswith("_")}
                card_create = CardCreate(**clean_card)
                card_dict = card_create.model_dump()
                # Add metadata back
                if "_confidence" in card:
                    card_dict["_confidence"] = card["_confidence"]
                if "_overall_confidence" in card:
                    card_dict["_overall_confidence"] = card["_overall_confidence"]
                if "_tcdb_verification" in card:
                    card_dict["_tcdb_verification"] = card["_tcdb_verification"]
                card_dicts.append(card_dict)
            else:
                # Regular card without metadata
                card_create = CardCreate(**card)
                card_dicts.append(card_create.model_dump())
        else:
            # CardCreate instance
            card_dicts.append(card.model_dump())

    filename = out_dir / (
        f"{filename_stem}.json" if filename_stem else f"{uuid.uuid4()}.json"
    )

    try:
        with open(filename, "w") as f:
            json.dump(card_dicts, f, indent=2)
    except (TypeError, ValueError) as e:
        print(
            f"JSON serialization error, saving without metadata: {e}",
            file=sys.stderr)
        # Fallback: save only core fields if JSON serialization fails
        clean_cards = []
        for card_dict in card_dicts:
            core_fields = {
                "name",
                "sport",
                "brand",
                "number",
                "copyright_year",
                "team",
                "card_set",
                "condition",
                "is_player_card",
                "features",
                "notes",
            }
            clean_card = {
                k: v for k,
                v in card_dict.items() if k in core_fields}
            clean_cards.append(clean_card)

        with open(filename, "w") as f:
            json.dump(clean_cards, f, indent=2)

    return filename.stem


def add_verified_cards_to_db():
    verified_dir = Path("verified")
    session = SessionLocal()
    for file in verified_dir.glob("*.json"):
        with open(file, "r") as f:
            card_data = json.load(f)

        for entry in card_data:
            try:
                card_create = CardCreate(**entry)
                card_info = card_create.model_dump()

                # Check for existing card (duplicate detection)
                existing = (
                    session.query(Card)
                    .filter(
                        Card.brand == card_info.get("brand"),
                        Card.number == card_info.get("number"),
                        Card.name == card_info.get("name"),
                        Card.copyright_year == card_info.get("copyright_year"),
                    )
                    .first()
                )

                if existing:
                    # Update quantity for duplicate
                    existing.quantity += 1
                    print(
                        f"Updated quantity for existing card: {card_info.get('name')}", 
                        file=sys.stderr
                    )
                else:
                    # Create new card
                    new_card = Card(**card_info)
                    session.add(new_card)
                    print(
                        f"Added new card: {card_info.get('name')}", 
                        file=sys.stderr
                    )

            except Exception as e:
                print(f"Error parsing {file.name}: {e}", file=sys.stderr)
                continue

        session.commit()
        file.unlink()
    session.close()
