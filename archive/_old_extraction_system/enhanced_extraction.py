"""
Enhanced card extraction using multi-pass GPT-4 validation and confidence scoring.
This module improves accuracy without relying on external card set databases.
"""

import json
import sys
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import base64
from io import BytesIO
from PIL import Image as PILImage
from openai import OpenAI
import os

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


@dataclass
class ExtractionResult:
    """Result from a single extraction pass"""
    data: Dict
    confidence: Dict[str, float]
    reasoning: str


def encode_image(image_path: str, max_size: int = 2400) -> str:
    """Encode image to base64 with resizing"""
    img = PILImage.open(image_path)
    if max(img.size) > max_size:
        ratio = max_size / max(img.size)
        img = img.resize((int(img.size[0] * ratio), int(img.size[1] * ratio)), PILImage.LANCZOS)
    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=95)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def extract_pass1_visual_analysis(img_b64: str, position: int) -> ExtractionResult:
    """
    Pass 1: Direct visual extraction with explicit location identification
    Focus on finding the player name by describing WHERE it is on the card
    """

    prompt = f"""You are analyzing position {position} in a 3x3 grid of baseball card BACKS.

STEP-BY-STEP VISUAL ANALYSIS:

1. LOCATE THE PLAYER NAME:
   - Scan the card from TOP to BOTTOM
   - The player name is usually the LARGEST TEXT or in ALL CAPS
   - Common locations: top section, below any small text, next to card number
   - Describe what you see: "At the top center, I see large text that says..."

2. AVOID COMMON MISTAKES:
   - DO NOT read team names as player names (Cleveland Indians, Boston Red Sox, etc.)
   - DO NOT read positions as names (Third Base, Pitcher, Catcher, etc.)
   - DO NOT read biographical text as names ("Bobby works for...", "Jim was born in...")
   - DO NOT read stats headers as names (BATTING, PITCHING, etc.)

3. VERIFY YOUR ANSWER:
   - Is this a person's FIRST and LAST name? (e.g., "RICK SUTCLIFFE", "DOUG BIRD")
   - Does it make sense as a player name?
   - Can you point to exactly where you see it on the card?

4. EXTRACT OTHER FIELDS:
   - Card number: Look for # symbol
   - Copyright year: Look for © symbol (usually small text at bottom)
   - Brand: Usually "Topps" or visible logo
   - Team: Often in stats table headers or biographical text

Return JSON with your analysis:
{{
  "visual_description": "Describe what you see and where",
  "name": "FIRST LAST (the person's actual name in caps)",
  "name_location": "where you found it (e.g., 'top center in large bold text')",
  "number": "card number",
  "copyright_year": "© year",
  "brand": "topps/panini/etc",
  "team": "team name",
  "card_set": "n/a unless special (Traded, All-Star, etc.)",
  "sport": "baseball",
  "condition": "excellent/very_good/good/fair/poor based on visible wear",
  "is_player_card": true,
  "features": "none or comma-separated features like 'rookie, autograph'",
  "confidence": {{
    "name": 0-100,
    "number": 0-100,
    "team": 0-100,
    "copyright_year": 0-100
  }},
  "reasoning": "Explain your extraction process"
}}

Think carefully and describe what you see before extracting."""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "You are an expert at analyzing baseball cards. Always describe what you see before extracting data."},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
            ]}
        ],
        max_tokens=1000,
        temperature=0.1
    )

    result_text = response.choices[0].message.content.strip()
    result_text = clean_json_response(result_text)

    parsed = json.loads(result_text)
    confidence = parsed.pop('confidence', {})
    reasoning = parsed.pop('reasoning', '')
    parsed.pop('visual_description', None)
    parsed.pop('name_location', None)

    return ExtractionResult(data=parsed, confidence=confidence, reasoning=reasoning)


def extract_pass2_focused_verification(img_b64: str, pass1_result: ExtractionResult, position: int) -> ExtractionResult:
    """
    Pass 2: Verify the name extraction with focused questioning
    Challenge the first result to catch mistakes
    """

    prompt = f"""You previously identified the player name as "{pass1_result.data.get('name', 'UNKNOWN')}" on this baseball card back.

VERIFICATION TASK:
Let's double-check this is correct by answering these questions:

1. WHERE exactly on the card do you see this name?
   - Point to the specific location
   - Describe the text style (all caps, bold, large, etc.)

2. WHAT ELSE is near this text?
   - Is it next to a card number?
   - Is it in a header section?
   - What's above it? What's below it?

3. CHALLENGE: Could this actually be something else?
   - Is it possibly a TEAM name? (Check if it says Indians, Red Sox, Cubs, etc.)
   - Is it possibly a POSITION? (Check if it says Pitcher, Third Base, etc.)
   - Is it possibly BIOGRAPHICAL text? (Check if it's part of a sentence)

4. VERIFICATION:
   - Does "{pass1_result.data.get('name', 'UNKNOWN')}" sound like a person's name?
   - Can you see FIRST and LAST name components?
   - Is there any OTHER text that might be the actual player name?

Return JSON with verification:
{{
  "verified_name": "The correct player name (or DIFFERENT if you found an error)",
  "confidence": 0-100,
  "location_description": "Exactly where you see the name",
  "why_this_is_correct": "Explain why this is the player name and not team/position/etc",
  "alternative_if_wrong": "If the original was wrong, what should it be?",
  "name_changed": true/false
}}"""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "You are verifying card extraction. Be critical and look for errors."},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
            ]}
        ],
        max_tokens=800,
        temperature=0.2
    )

    result_text = response.choices[0].message.content.strip()
    result_text = clean_json_response(result_text)

    verification = json.loads(result_text)

    # Update the data if verification found an error
    updated_data = pass1_result.data.copy()
    if verification.get('name_changed') and verification.get('alternative_if_wrong'):
        updated_data['name'] = verification['alternative_if_wrong']
        confidence = {'name': verification.get('confidence', 50)}
    else:
        updated_data['name'] = verification.get('verified_name', pass1_result.data.get('name'))
        confidence = {'name': verification.get('confidence', 70)}

    reasoning = verification.get('why_this_is_correct', '') + " | " + verification.get('location_description', '')

    return ExtractionResult(data=updated_data, confidence=confidence, reasoning=reasoning)


def extract_pass3_ensemble_voting(results: List[ExtractionResult]) -> Dict:
    """
    Pass 3: Use ensemble voting to pick best values for each field
    Higher confidence results get more weight
    """

    final_data = {}
    fields = ['name', 'number', 'copyright_year', 'brand', 'team', 'card_set', 'sport', 'condition', 'is_player_card', 'features']

    for field in fields:
        # Collect all values with their confidence scores
        candidates = []
        for result in results:
            if field in result.data:
                conf = result.confidence.get(field, 50)
                candidates.append((result.data[field], conf))

        if not candidates:
            final_data[field] = None
            continue

        # For simple fields, pick highest confidence
        if field in ['is_player_card', 'sport']:
            final_data[field] = max(candidates, key=lambda x: x[1])[0]
        else:
            # For text fields, use weighted voting
            # If multiple high-confidence results agree, use that
            value_scores = {}
            for value, conf in candidates:
                value_scores[value] = value_scores.get(value, 0) + conf

            final_data[field] = max(value_scores.items(), key=lambda x: x[1])[0]

    # Calculate overall confidence
    all_confidences = []
    for result in results:
        all_confidences.extend(result.confidence.values())

    final_data['_confidence'] = sum(all_confidences) / len(all_confidences) if all_confidences else 50

    return final_data


def clean_json_response(text: str) -> str:
    """Remove markdown code blocks from JSON response"""
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    return text


def enhanced_extract_single_card(image_path: str, position: int = 0) -> Dict:
    """
    Extract card data using multi-pass validation

    Args:
        image_path: Path to card image
        position: Grid position (0-8) if part of a grid

    Returns:
        Extracted card data with confidence scores
    """

    print(f"[Enhanced Extraction] Processing position {position}: {image_path}", file=sys.stderr)

    # Encode image once
    img_b64 = encode_image(image_path)

    results = []

    # Pass 1: Visual analysis
    print(f"[Pass 1/2] Visual analysis...", file=sys.stderr)
    pass1 = extract_pass1_visual_analysis(img_b64, position)
    results.append(pass1)
    print(f"[Pass 1] Name: {pass1.data.get('name')}, Confidence: {pass1.confidence.get('name', 0)}", file=sys.stderr)

    # Pass 2: Focused verification
    print(f"[Pass 2/2] Verification...", file=sys.stderr)
    pass2 = extract_pass2_focused_verification(img_b64, pass1, position)
    results.append(pass2)
    print(f"[Pass 2] Name: {pass2.data.get('name')}, Confidence: {pass2.confidence.get('name', 0)}", file=sys.stderr)

    # Pass 3: Ensemble voting
    final_data = extract_pass3_ensemble_voting(results)
    final_data['grid_position'] = position
    final_data['_extraction_method'] = 'enhanced_multi_pass'

    print(f"[Final] Name: {final_data.get('name')}, Overall Confidence: {final_data.get('_confidence', 0):.1f}", file=sys.stderr)

    return final_data


def enhanced_extract_grid(image_path: str, extract_individual: bool = True) -> List[Dict]:
    """
    Extract all 9 cards from a 3x3 grid with enhanced accuracy

    Args:
        image_path: Path to grid image
        extract_individual: If True, extract each card separately (more accurate but slower)

    Returns:
        List of 9 card data dictionaries
    """

    print(f"[Enhanced Grid Extraction] Processing: {image_path}", file=sys.stderr)

    if extract_individual:
        # TODO: Implement individual card extraction from grid
        # For now, fall back to single-shot extraction with enhanced prompting
        pass

    # Single-shot enhanced extraction
    img_b64 = encode_image(image_path)

    prompt = """You are analyzing a 3x3 grid of baseball card BACKS (9 cards total, positions 0-8, left-to-right, top-to-bottom).

CRITICAL NAME EXTRACTION RULES:
1. For EACH card, find the PLAYER NAME by:
   - Looking for the LARGEST or ALL CAPS text on the card back
   - This is typically a person's FIRST and LAST name
   - Common format: "RICK SUTCLIFFE", "DOUG BIRD", "JIM HOLT"

2. DO NOT extract as name:
   - Team names (Indians, Red Sox, Yankees, Cubs, Brewers, etc.)
   - Positions (Pitcher, Catcher, Third Base, Outfield, etc.)
   - Biographical phrases ("Bobby works for...", "Jim was born...")
   - Stats headers (BATTING, PITCHING, FIELDING, etc.)

3. VERIFICATION for each card:
   - Ask: "Is this a person's first and last name?"
   - Ask: "Where exactly do I see this on the card?"
   - Ask: "Could this be a team/position instead?"

4. USE GRID CONTEXT:
   - If multiple cards have same brand/year, they're likely from same set
   - Card numbers should be different for each card
   - Similar design patterns = same set

Return JSON array with exactly 9 objects:
[{
  "grid_position": 0,
  "name": "FIRST LAST",
  "number": "card number",
  "copyright_year": "© year",
  "brand": "topps",
  "team": "team name",
  "card_set": "n/a",
  "sport": "baseball",
  "condition": "good/very_good/excellent",
  "is_player_card": true,
  "features": "none",
  "confidence_name": 0-100,
  "name_location": "where you found the name"
}, ...]

THINK CAREFULLY about each card. Describe what you see before extracting."""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "You are a baseball card expert. Extract data carefully, avoiding common mistakes like confusing team names with player names."},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
            ]}
        ],
        max_tokens=3000,
        temperature=0.1
    )

    result_text = response.choices[0].message.content.strip()
    result_text = clean_json_response(result_text)

    cards = json.loads(result_text)

    # Add metadata
    for i, card in enumerate(cards):
        card.setdefault('grid_position', i)
        card.setdefault('_grid_metadata', {"position": i, "row": i // 3, "col": i % 3})
        card['_extraction_method'] = 'enhanced_grid'

        # Extract confidence from response
        confidence = card.pop('confidence_name', 70)
        card.pop('name_location', None)
        card['_confidence'] = {'name': confidence}

    return cards


def validate_with_checklist(extracted_card: Dict) -> Dict:
    """
    Validate extracted card data against checklist database
    Updates confidence scores and adds suggestions

    Args:
        extracted_card: Card data dict with brand, year, number, name

    Returns:
        Same dict with added _validation field containing checklist results
    """

    try:
        from card_set_database import CardSetDatabase

        db = CardSetDatabase()
        validation = db.validate_extraction(extracted_card)
        db.close()

        # Update confidence based on validation
        if validation.get('valid') == True:
            # Exact match - boost confidence
            if '_confidence' in extracted_card:
                if isinstance(extracted_card['_confidence'], dict):
                    extracted_card['_confidence']['name'] = min(100, extracted_card['_confidence'].get('name', 70) + 20)
                else:
                    extracted_card['_confidence'] = {'name': min(100, extracted_card.get('_confidence', 70) + 20)}
            validation['status'] = 'verified_exact'

        elif validation.get('valid') == 'fuzzy':
            # Fuzzy match - use suggestion
            if validation.get('suggestion'):
                extracted_card['_checklist_suggestion'] = validation['suggestion']
                extracted_card['_original_extraction'] = extracted_card.get('name')
            validation['status'] = 'verified_fuzzy'

        elif validation.get('valid') == False:
            # Mismatch - flag for review
            if validation.get('suggestion'):
                extracted_card['_checklist_suggestion'] = validation['suggestion']
                extracted_card['_original_extraction'] = extracted_card.get('name')
            # Lower confidence
            if '_confidence' in extracted_card:
                if isinstance(extracted_card['_confidence'], dict):
                    extracted_card['_confidence']['name'] = max(30, extracted_card['_confidence'].get('name', 70) - 30)
                else:
                    extracted_card['_confidence'] = {'name': max(30, extracted_card.get('_confidence', 70) - 30)}
            validation['status'] = 'mismatch'

        elif not validation.get('in_database', True):
            # Not in database - can't validate
            validation['status'] = 'no_checklist'

        extracted_card['_validation'] = validation

    except Exception as e:
        print(f"[Checklist Validation] Error: {e}", file=sys.stderr)
        extracted_card['_validation'] = {'status': 'error', 'message': str(e)}

    return extracted_card


def enhanced_extract_with_validation(image_path: str, extract_individual: bool = False) -> List[Dict]:
    """
    Extract cards from grid and validate against checklist database

    Args:
        image_path: Path to grid image
        extract_individual: Use individual card extraction (slower, more accurate)

    Returns:
        List of card dicts with validation results
    """

    # Extract cards
    cards = enhanced_extract_grid(image_path, extract_individual=extract_individual)

    # Apply learned corrections (post-extraction)
    print(f"[Post-Correction] Applying learned corrections...", file=sys.stderr)
    try:
        from post_extraction_corrections import apply_learned_corrections_batch
        cards = apply_learned_corrections_batch(cards)
    except Exception as e:
        print(f"[Post-Correction] Warning: {e}", file=sys.stderr)

    # Validate each card against checklist
    print(f"[Validation] Checking against checklist database...", file=sys.stderr)
    for i, card in enumerate(cards):
        cards[i] = validate_with_checklist(card)

        validation = card.get('_validation', {})
        status = validation.get('status', 'unknown')

        if status == 'verified_exact':
            print(f"  [{i}] {card.get('name')}: EXACT MATCH ✓", file=sys.stderr)
        elif status == 'verified_fuzzy':
            print(f"  [{i}] {card.get('name')}: Fuzzy match, suggested: {card.get('_checklist_suggestion')}", file=sys.stderr)
        elif status == 'mismatch':
            print(f"  [{i}] {card.get('name')}: MISMATCH, expected: {card.get('_checklist_suggestion')}", file=sys.stderr)
        elif status == 'no_checklist':
            print(f"  [{i}] {card.get('name')}: No checklist available", file=sys.stderr)

    return cards
