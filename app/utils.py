import base64
import json
import os
import re
import sys
import time
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
from app.team_map import canonicalize_team
from app.models import Card
from app.schemas import CardCreate  # make sure this import exists
from app.tcdb_scraper import search_tcdb_cards

# Import image enhancement functions
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

# Centralized OpenAI client and model selection
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
# Model selection: default to a high-quality multimodal model.
# Override via OPENAI_MODEL to target a specific snapshot.
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

# Unified LLM chat helper with retries/backoff
def _is_retryable_error(exc: Exception) -> bool:
    code = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    if code is not None:
        try:
            c = int(code)
            if c == 429 or 500 <= c < 600:
                return True
        except Exception:
            pass
    text = str(exc).lower()
    retry_tokens = [
        "timeout", "timed out", "temporar", "connection reset",
        "connection aborted", "server error", "service unavailable",
        "gateway timeout", "rate limit", "too many requests",
    ]
    return any(t in text for t in retry_tokens)

def llm_chat(
    *,
    messages,
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = 0.1,
    response_format: dict | None = None,
    retries: int = 3,
    backoff_seconds: float = 1.5,
    client_override=None,
):
    """Central wrapper for chat.completions with retries/backoff.

    Returns the OpenAI response object.
    """
    use_model = model or MODEL
    attempt = 0
    while True:
        try:
            _client = client_override or client
            return _client.chat.completions.create(
                model=use_model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                response_format=response_format,
            )
        except Exception as e:
            attempt += 1
            if attempt > retries or not _is_retryable_error(e):
                print(f"LLM call failed (final): {e}", file=sys.stderr)
                raise
            sleep_for = min(backoff_seconds ** attempt, 30)
            print(
                f"LLM call error (attempt {attempt}/{retries}): {e} — retrying in {sleep_for:.1f}s",
                file=sys.stderr,
            )
            time.sleep(sleep_for)


def build_legacy_system_prompt(include_learning: bool = True) -> str:
    """Deprecated: retained as a thin wrapper for backward compatibility.

    The legacy prompt has been removed to reduce maintenance. We now defer to
    build_system_prompt, which is the canonical multi-pass prompt.
    """
    return build_system_prompt(include_learning)

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
    """Build a strict, high-signal system prompt for card extraction.

    Emphasizes precise field definitions, consistent naming, and strict JSON output.
    Allows optional metadata keys prefixed with '_' for evidence/confidence.
    """

    # Explicit schema guidance for the model
    schema_block = (
        "{\n"
        "  \"cards\": [\n"
        "    {\n"
        "      \"name\": \"string\",\n"
        "      \"sport\": \"baseball|basketball|football|hockey|soccer\",\n"
        "      \"brand\": \"string or 'unknown'\",\n"
        "      \"number\": \"string or 'n/a'\",\n"
        "      \"copyright_year\": \"YYYY or 'unknown'\",\n"
        "      \"team\": \"string or 'n/a'\",\n"
        "      \"card_set\": \"'n/a' for base set; only specify a subset/insert/parallel beyond brand+year\",\n"
        "      \"condition\": \"gem_mint|mint|near_mint|excellent|very_good|good|fair|poor\",\n"
        "      \"is_player_card\": true,\n"
        "      \"features\": \"'none' or CSV from {rookie,autograph,jersey,serial numbered,refractor,chrome,parallel,insert,short print}\",\n"
        "      \"notes\": \"string or 'n/a'\"\n"
        "      /* Optional metadata to aid verification (allowed): */\n"
        "      /* _field_confidence: { name:0-1, brand:0-1, ... } */\n"
        "      /* _field_evidence: { name:\"where found\", year:\"© year bottom edge\", ... } */\n"
        "    }\n"
        "  ]\n"
        "}"
    )

    rules = (
        "Extract trading card data from the image. Count visible cards and analyze each one.\n\n"
        "You may receive multiple views/variants of the same image (e.g., high-contrast). Use ALL provided images to read tiny fine print (copyright year, brand marks).\n\n"
        "Naming rules and distinctions:\n"
        "- NAME: Use the exact printed title/subject on the card.\n"
        "  • If it's a Leaders/Checklist/Team/Multi-player card → set is_player_card=false and NAME to the printed TITLE (not individual names).\n"
        "  • If it's a single player card → set is_player_card=true and NAME to the player's name.\n"
        "  • CRITICAL: For card backs, the player name is at the VERY TOP in the LARGEST text (e.g., 'DAVE GOLTZ'). DO NOT confuse with team names, positions, or biographical text.\n"
        "- SET: Use 'n/a' for regular/base cards. Only specify a subset/insert/parallel beyond brand+year (e.g., 'all-star', 'leaders', 'chrome refractor').\n"
        "- YEAR: Use the production/copyright year (©, fine print), not stats years.\n"
        "- CONDITION: Evaluate corners/edges/surface carefully and map to the 8-level scale.\n"
        "- TEAM: Use city + team name (e.g., 'cleveland indians').\n"
        "- FEATURES: Use 'none' or CSV from the allowed list; include 'serial numbered' if a numbering like '/299' is visible.\n\n"
        "Output requirements:\n"
        "- Strict JSON object with top-level key 'cards'.\n"
        "- Each element must follow this schema (optional '_' metadata allowed):\n"
        f"{schema_block}\n\n"
        "Conventions:\n"
        "- Use 'n/a' for truly missing values (except booleans).\n"
        "- Use lowercase for brand, condition, and features.\n"
        "- Be precise and avoid placeholders like 'unspecified' or 'unknown' unless truly unknown.\n"
    )

    # Append learning enhancements if available
    if include_learning:
        try:
            learning_enhancements = generate_learning_prompt_enhancements()
            if learning_enhancements:
                rules = rules + "\n" + learning_enhancements
        except Exception as e:
            print(f"Warning: Could not load learning enhancements: {e}", file=sys.stderr)

    return rules


SYSTEM_PROMPT = build_system_prompt()

def build_single_pass_prompt(include_learning: bool = True) -> str:
    """A compact, high-precision prompt for a single LLM pass.

    Focuses on: exact NAME vs SET distinction, true copyright year, brand, number,
    and a normalized schema. Keeps guidance terse to reduce tokens while preserving
    accuracy. Output must be a JSON object with key 'cards'.
    """

    rules = (
        "You are an expert trading card cataloger. Extract precise data for each card in the image.\n"
        "Rules:\n"
        "- NAME: Use the printed title/subject on the card. For multi-player/leaders/checklist/team cards → set is_player_card=false and NAME to the card title (not individuals). For a single player → is_player_card=true and NAME is the player name.\n"
        "- SET: Use 'n/a' for regular/base cards. Only specify a subset/insert/parallel beyond brand+year.\n"
        "- TEAM: Use city + team name (e.g., 'cleveland indians').\n"
        "- YEAR: Use the true production/copyright year (© fine print or brand imprint), not stats years.\n"
        "- BRAND: The manufacturer (e.g., topps, panini).\n"
        "- NUMBER: Card number if present; else 'n/a'.\n"
        "- CONDITION: gem_mint|mint|near_mint|excellent|very_good|good|fair|poor.\n"
        "- FEATURES: 'none' or CSV from {rookie,autograph,jersey,serial numbered,refractor,chrome,parallel,insert,short print}.\n\n"
        "Output JSON object: { 'cards': [ {\n"
        "  'name': str, 'sport': 'baseball|basketball|football|hockey|soccer', 'brand': str, 'number': str|'n/a',\n"
        "  'copyright_year': 'YYYY', 'team': str|'n/a', 'card_set': str, 'condition': str, 'is_player_card': bool, 'features': str\n"
        "} ] }\n"
        "Conventions: lowercase brand/condition/features; 'n/a' for missing strings; avoid placeholders.\n"
    )

    if include_learning:
        try:
            enh = generate_learning_prompt_enhancements()
            if enh:
                rules += "\n" + enh
        except Exception:
            pass
    return rules

SINGLE_PASS_PROMPT = build_single_pass_prompt()


def build_reprocessing_prompt(_previous_data):
    """Build a focused prompt for reprocessing with key corrections"""

    # Build a completely fresh, focused prompt for reprocessing
    reprocessing_prompt = f"""
Analyze each trading card individually in this image.

Count cards visible and analyze each one separately:
- Player name: CRITICAL - For card backs, look at the VERY TOP for the LARGEST text, which is the player's FULL NAME (e.g., "DAVE GOLTZ", "JIM HOLT"). For card fronts, check text, jersey, nameplate. DO NOT confuse player names with team names, positions, or stats.
- Team (logos, colors, text)
- Year (© symbol, small print)
- Card number
- Brand (Topps, Panini, etc.)
- Condition (corners, edges, surface)

Return a JSON object with key 'cards' that contains an array of card objects. Each object must include these fields:
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
    """Best-effort parse of a JSON array from possibly noisy/truncated text.

    Handles cases where the model returns:
    - Valid JSON array
    - A single JSON object
    - A JSON array that's truncated (missing trailing "]")
    - Extra prose before/after JSON
    - Multiple objects without enclosing array
    """

    def _strip_fences(s: str) -> str:
        s = s.strip()
        s = re.sub(r"^```(?:json)?\n?", "", s)
        s = re.sub(r"\n?```$", "", s)
        return s.strip()

    def _remove_trailing_commas(s: str) -> str:
        # Remove trailing commas before ] or }
        s = re.sub(r",\s*(\])", r"\1", s)
        s = re.sub(r",\s*(\})", r"\1", s)
        return s

    def _parse_if_json(s: str):
        try:
            obj = json.loads(s)
            if isinstance(obj, list):
                return obj
            if isinstance(obj, dict):
                return [obj]
        except Exception:
            return None

    def _extract_objects_from_array_text(s: str) -> list:
        """Extract balanced JSON objects from an array-like text.

        Example inputs handled:
        - "[ {..}, {..}, {.."  (truncated)
        - "some text... [ {..}, {..}, {..} more text"
        """
        if "{" not in s:
            return []
        objs = []
        start_idx = None
        depth = 0
        in_str = False
        escape = False
        for i, ch in enumerate(s):
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                continue
            else:
                if ch == '"':
                    in_str = True
                    continue
                if ch == '{':
                    if depth == 0:
                        start_idx = i
                    depth += 1
                elif ch == '}':
                    if depth > 0:
                        depth -= 1
                        if depth == 0 and start_idx is not None:
                            objs.append(s[start_idx:i+1])
                            start_idx = None
        parsed = []
        for o in objs:
            o_clean = _remove_trailing_commas(_strip_fences(o))
            try:
                parsed_obj = json.loads(o_clean)
                if isinstance(parsed_obj, dict):
                    parsed.append(parsed_obj)
            except Exception:
                # Skip unparseable fragments
                continue
        return parsed

    # Normalize input
    raw = _strip_fences(raw)

    # Fast path: try as-is
    parsed = _parse_if_json(raw)
    if parsed is not None:
        return parsed

    # If there is an array start, try to salvage from first '['
    if '[' in raw:
        arr_start = raw.find('[')
        candidate = raw[arr_start:]
        candidate = _remove_trailing_commas(candidate.rstrip())

        # Try simple trailing bracket fix for truncated arrays
        simple = candidate
        # Trim any trailing whitespace/commas after last '}'
        simple = simple.rstrip()
        # If it looks like "[ {...}, {...}" then append closing bracket
        if simple.count('[') >= 1 and simple.count(']') < simple.count('['):
            # Cut to last complete object if possible
            objects = _extract_objects_from_array_text(simple)
            if objects:
                try:
                    return json.loads('[' + ','.join(json.dumps(o) for o in objects) + ']')
                except Exception:
                    pass
            # Fallback: best-effort close array
            tail = simple
            # Remove trailing characters until last brace is '}'
            tail = tail.rstrip(', \n\r\t')
            while tail and tail[-1] != '}':
                tail = tail[:-1]
            fixed = tail + ']'
            parsed = _parse_if_json(fixed)
            if parsed is not None:
                return parsed

        # If bracket counts match but JSON still invalid, attempt to extract objects
        objs = _extract_objects_from_array_text(candidate)
        if objs:
            return objs

    # No '[' or failed above: scan entire text for balanced objects
    objs = _extract_objects_from_array_text(raw)
    if objs:
        return objs

    raise ValueError("Could not recover truncated JSON")


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

    # Convert image to supported format for GPT vision with preprocessing
    encoded_image, mime_type = convert_image_to_supported_format(
        image_path, apply_preprocessing=True
    )

    # Provide an additional high-contrast variant to help the model read fine print
    # (copyright lines, tiny brand marks, card numbers)
    high_contrast_b64 = None
    try:
        from PIL import Image
        buf = BytesIO()
        img = Image.open(image_path)
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.save(buf, format="PNG")
        base_bytes = buf.getvalue()
        hc_bytes = create_high_contrast_version(base_bytes)  # uses OpenCV if available
        high_contrast_b64 = base64.b64encode(hc_bytes).decode("utf-8")
    except Exception as _:
        high_contrast_b64 = None

    # Use enhanced prompt if this is a reprocessing with previous data
    if previous_data:
        prompt_to_use = build_reprocessing_prompt(previous_data)
    else:
        # For initial extraction, use base prompt (specialized prompts need
        # data analysis first)
        prompt_to_use = SYSTEM_PROMPT

    # First pass: Initial extraction
    user_content = [
        {
            "type": "image_url",
            "image_url": {"url": f"data:{mime_type};base64,{encoded_image}"},
        }
    ]
    if high_contrast_b64:
        user_content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{high_contrast_b64}"},
            }
        )

    messages = [
        {"role": "system", "content": prompt_to_use},
        {"role": "user", "content": user_content},
    ]

    response = llm_chat(
        messages=messages,
        max_tokens=2500,
        temperature=0.1,
        response_format={"type": "json_object"},
    )

    try:
        raw_response = response.choices[0].message.content.strip()

        if raw_response.startswith("```json"):
            raw_response = raw_response[7:].strip()
        elif raw_response.startswith("```"):
            raw_response = raw_response[3:].strip()
        if raw_response.endswith("```"):
            raw_response = raw_response[:-3].strip()

        # Prefer strict JSON object with 'cards' (due to response_format)
        parsed = None
        try:
            obj = json.loads(raw_response)
            if isinstance(obj, dict) and isinstance(obj.get("cards"), list):
                parsed = obj["cards"]
            elif isinstance(obj, list):
                parsed = obj
        except Exception:
            parsed = None

        if parsed is None:
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

        import os
        fast_mode = os.getenv("FAST_MODE", "false").lower() in ("1", "true", "yes")

        for card in scored_cards:
            overall_confidence = card.get("_overall_confidence", 0.5)
            confidence_scores = card.get("_confidence", {})

            # Flag cards with very low confidence in critical fields
            # Be less aggressive about reprocessing for names since they're
            # often unclear in vintage cards
            name_thresh = 0.25 if not fast_mode else 0.20
            year_thresh = 0.50 if not fast_mode else 0.40
            overall_thresh = 0.35 if not fast_mode else 0.30

            critical_low_confidence = (
                confidence_scores.get("name", 1.0) < name_thresh
                or confidence_scores.get("copyright_year", 1.0) < year_thresh
                or overall_confidence < overall_thresh
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
                reprocess_response = llm_chat(
                    messages=reprocess_messages,
                    max_tokens=2500,
                    temperature=0.1,
                    response_format={"type": "json_object"},
                )

                reprocess_content = reprocess_response.choices[0].message.content.strip()
                # Prefer strict JSON object with 'cards'
                reprocess_parsed = None
                try:
                    obj = json.loads(reprocess_content)
                    if isinstance(obj, dict) and isinstance(obj.get("cards"), list):
                        reprocess_parsed = obj["cards"]
                    elif isinstance(obj, list):
                        reprocess_parsed = obj
                except Exception:
                    reprocess_parsed = None

                if reprocess_parsed is None:
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

        # Add value estimation to each final card (lazy import to avoid circular deps)
        try:
            from app.value_estimator import add_value_estimation
            final_cards = [add_value_estimation(card) for card in final_cards]
        except Exception as e:
            print(f"Value estimation unavailable, skipping: {e}", file=sys.stderr)

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


def gpt_extract_cards_single_pass(image_path: str) -> tuple[list, list[CardCreate]]:
    """Fast path: single high-accuracy LLM pass using a compact prompt.

    Keeps high-contrast variant for better OCR of fine print. Skips
    reprocessing, TCDB lookups, and value estimation to reduce latency.
    """
    # Convert image and optional high-contrast variant
    encoded_image, mime_type = convert_image_to_supported_format(
        image_path, apply_preprocessing=True
    )
    high_contrast_b64 = None
    try:
        from PIL import Image
        buf = BytesIO()
        img = Image.open(image_path)
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.save(buf, format="PNG")
        base_bytes = buf.getvalue()
        hc_bytes = create_high_contrast_version(base_bytes) if CV2_AVAILABLE else base_bytes
        high_contrast_b64 = base64.b64encode(hc_bytes).decode("utf-8")
    except Exception:
        high_contrast_b64 = None

    user_content = [
        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded_image}"}},
    ]
    if high_contrast_b64:
        user_content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{high_contrast_b64}"}})

    messages = [
        {"role": "system", "content": SINGLE_PASS_PROMPT},
        {"role": "user", "content": user_content},
    ]

    response = llm_chat(
        messages=messages,
        max_tokens=1800,
        temperature=0.0,
        response_format={"type": "json_object"},
    )

    raw_response = response.choices[0].message.content.strip()
    if raw_response.startswith("```json"):
        raw_response = raw_response[7:].strip()
    elif raw_response.startswith("```"):
        raw_response = raw_response[3:].strip()
    if raw_response.endswith("```"):
        raw_response = raw_response[:-3].strip()

    parsed = None
    try:
        obj = json.loads(raw_response)
        if isinstance(obj, dict) and isinstance(obj.get("cards"), list):
            parsed = obj["cards"]
        elif isinstance(obj, list):
            parsed = obj
    except Exception:
        parsed = None
    if parsed is None:
        try:
            raw_json = extract_json_array(raw_response)
        except ValueError:
            raw_json = raw_response
        parsed = safe_parse_json_array(raw_json)
    if isinstance(parsed, dict):
        parsed = [parsed]

    # Minimal cleanup
    for item in parsed:
        if isinstance(item, dict):
            if item.get("features") in (None, "null", ""):
                item["features"] = "none"
            if item.get("is_player_card") in (None, "null"):
                item["is_player_card"] = True

    # Optionally add value estimation now so initial processing carries pricing
    try:
        from app.value_estimator import add_value_estimation
        parsed = [add_value_estimation(card) for card in parsed]
    except Exception as e:
        print(f"Value estimation unavailable in single-pass: {e}", file=sys.stderr)

    clean_cards = [{k: v for k, v in d.items() if isinstance(d, dict) and not k.startswith("_")} for d in parsed]
    return parsed, [CardCreate(**c) for c in clean_cards if isinstance(c, dict)]


def _enhance_card_with_tcdb_data(card: dict, tcdb_match: dict) -> dict:
    """
    Enhance extracted card data with information from a TCDB match.

    Goals:
    - Prefer GPT-extracted fields but FILL CLEAR GAPS from TCDB
    - Soft-correct likely issues (e.g., obvious year mismatch)

    Fields we may fill from TCDB when missing/unknown:
      team, copyright_year, card_set, brand (derived from set), number, name
    """
    import re

    enhanced_card = card.copy()
    enhanced_fields: list[str] = []

    tcdb_title = str(tcdb_match.get("title", ""))
    tcdb_set = str(tcdb_match.get("set", ""))
    tcdb_year = str(tcdb_match.get("year", "")).strip()
    tcdb_team = str(tcdb_match.get("team", "")).strip()

    # Helper: parse brand from TCDB set (e.g., "1979 Topps" → brand "Topps")
    def _brand_from_set(set_text: str) -> str | None:
        m = re.match(r"\s*(?:19|20)\d{2}\s+([A-Za-z][A-Za-z &'-]+)", set_text)
        if m:
            return m.group(1).strip().lower()
        # If no year prefix, still try to take the first token
        parts = set_text.strip().split()
        if parts:
            return parts[0].strip().lower()
        return None

    # Helper: parse number and player name from TCDB title
    # Examples: "Nolan Ryan #500 California Angels" → name "Nolan Ryan", number "500"
    def _parse_title(title_text: str) -> tuple[str | None, str | None]:
        name, number = None, None
        # Find card number like #123 or #A-23
        num_match = re.search(r"#\s*([A-Za-z0-9-]+)", title_text)
        if num_match:
            number = num_match.group(1).strip()
        # Name is often before the number
        if number:
            pre = title_text.split('#', 1)[0].strip()
            # Remove trailing separators/commas
            name = re.sub(r"[-–|/:]+$", "", pre).strip()
        else:
            # Fall back: take up to first team-like token
            name = title_text.strip()
        # Basic cleanup
        if name:
            name = re.sub(r"\s{2,}", " ", name)
        return (name or None, number)

    # 1) Team backfill
    if (not enhanced_card.get("team") or str(enhanced_card.get("team")).lower() in {"n/a", "unknown", ""}) and tcdb_team:
        enhanced_card["team"] = tcdb_team
        enhanced_fields.append("team")

    # 2) Year: backfill if missing; otherwise flag mismatch
    if enhanced_card.get("copyright_year") in (None, "", "n/a", "unknown"):
        if tcdb_year:
            enhanced_card["copyright_year"] = tcdb_year
            enhanced_fields.append("copyright_year")
    elif tcdb_year:
        try:
            extracted_year = int(str(enhanced_card["copyright_year"]).strip())
            tcdb_year_int = int(tcdb_year)
            if abs(extracted_year - tcdb_year_int) > 1:
                enhanced_card["_year_discrepancy"] = {
                    "extracted": str(extracted_year),
                    "tcdb": str(tcdb_year_int),
                    "note": "Year mismatch with TCDB - verify copyright vs. stats year",
                }
        except Exception:
            # If extracted year isn't parseable but TCDB has a year, use it
            enhanced_card["copyright_year"] = tcdb_year
            enhanced_fields.append("copyright_year")

    # 3) Set backfill
    if not enhanced_card.get("card_set") or str(enhanced_card.get("card_set")).lower() in {"n/a", "unknown", ""}:
        if tcdb_set:
            enhanced_card["card_set"] = tcdb_set
            enhanced_fields.append("card_set")

    # 4) Brand backfill (derived from set)
    if not enhanced_card.get("brand") or str(enhanced_card.get("brand")).lower() in {"n/a", "unknown", ""}:
        brand = _brand_from_set(tcdb_set)
        if brand:
            enhanced_card["brand"] = brand
            enhanced_fields.append("brand")

    # 5) Number backfill (from title)
    if not enhanced_card.get("number") or str(enhanced_card.get("number")).lower() in {"n/a", "unknown", ""}:
        _, parsed_number = _parse_title(tcdb_title)
        if parsed_number:
            enhanced_card["number"] = parsed_number
            enhanced_fields.append("number")

    # 6) Name backfill if GPT totally missed it
    if not enhanced_card.get("name") or str(enhanced_card.get("name")).lower() in {"unidentified", "unknown", "n/a", ""}:
        parsed_name, _ = _parse_title(tcdb_title)
        if parsed_name:
            enhanced_card["name"] = parsed_name
            enhanced_fields.append("name")

    # Add TCDB metadata for reference
    enhanced_card["_tcdb_title"] = tcdb_title
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

            # Enrich the TCDB query with number and set when available
            if card.get("number") and str(card["number"]).strip() not in ("", "n/a", "unknown"):
                query_parts.append(f"#{card['number']}")
            if card.get("card_set") and card["card_set"] not in ("n/a", "unknown"):
                query_parts.append(card["card_set"])

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

    # TCDB verification removed per user request

    # Helper: standardize category-like fields to lowercase for easier matching
    def _standardize_categories(card: dict) -> dict:
        def _lower(v):
            return v.lower().strip() if isinstance(v, str) else v
        standardized = dict(card)
        for key in ("name", "sport", "brand", "team", "card_set", "condition"):
            if key in standardized and standardized[key] is not None:
                standardized[key] = _lower(standardized[key])
        # canonicalize team to "city team" format when possible
        if standardized.get("team"):
            standardized["team"] = canonicalize_team(standardized["team"], standardized.get("sport"))
        # features as comma-separated, lowercased tokens
        if "features" in standardized and standardized["features"] is not None:
            if isinstance(standardized["features"], str):
                feats = [t.strip().lower().replace("_", " ") for t in standardized["features"].split(",")]
                feats = [t for t in feats if t]
                standardized["features"] = ",".join(sorted(set(feats))) if feats else "none"
        # If card_set is not a specific subset beyond the brand/year, set to 'n/a'
        try:
            cs = standardized.get("card_set") or ""
            br = standardized.get("brand") or ""
            if isinstance(cs, str):
                import re
                # Remove brand tokens and years from card_set to see what's left (case-insensitive)
                leftovers = cs.lower()
                brand_tokens = ["topps", "panini", "upper deck", "donruss", "fleer", "bowman", "leaf", "score", "pinnacle", "select", "o-pee-chee", "opc", "baseball"]
                for bt in brand_tokens + ([br.lower()] if br else []):
                    if bt:
                        leftovers = leftovers.replace(bt, "")
                leftovers = re.sub(r"\b(19\d{2}|20\d{2})\b", "", leftovers)
                leftovers = re.sub(r"[^a-z]+", " ", leftovers)
                if leftovers.strip() == "":
                    standardized["card_set"] = "n/a"
        except Exception:
            pass
        return standardized

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
                card_create = CardCreate(**_standardize_categories(clean_card))
                card_dict = card_create.model_dump()
                # Add metadata back
                if "_confidence" in card:
                    card_dict["_confidence"] = card["_confidence"]
                if "_overall_confidence" in card:
                    card_dict["_overall_confidence"] = card["_overall_confidence"]
                if "_tcdb_verification" in card:
                    card_dict["_tcdb_verification"] = card["_tcdb_verification"]
                card_dicts.append(_standardize_categories(card_dict))
            else:
                # Regular card without metadata
                card_create = CardCreate(**_standardize_categories(card))
                card_dicts.append(_standardize_categories(card_create.model_dump()))
        else:
            # CardCreate instance
            card_dicts.append(_standardize_categories(card.model_dump()))

    filename = out_dir / (
        f"{filename_stem}.json" if filename_stem else f"{uuid.uuid4()}.json"
    )

    try:
        # Write grouped JSON for compatibility with existing UI
        with open(filename, "w") as f:
            json.dump(card_dicts, f, indent=2)

        # Also write split-per-card JSON files for each card
        try:
            base = filename_stem or filename.stem
            for idx, c in enumerate(card_dicts, start=1):
                per_name = f"{base}__c{idx}.json"
                with open(out_dir / per_name, "w") as pf:
                    json.dump([c], pf, indent=2)
        except Exception as e:
            print(f"Per-card JSON split failed: {e}", file=sys.stderr)
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
