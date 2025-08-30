"""
GPT-powered value estimation system for trading cards.

Fix: Avoid reading OPENAI_API_KEY before dotenv is loaded by lazily creating
the OpenAI client and falling back gracefully when the key is missing.
"""

import json
import os
from typing import Dict, Any
from pathlib import Path
from openai import OpenAI
from app.utils import llm_chat
from dotenv import load_dotenv


_client = None
_cache: dict[str, dict] | None = None
_cache_path = Path("app/cache/value_estimates.json")


def _get_client() -> OpenAI | None:
    """Return an OpenAI client if API key is available; otherwise None.

    Loads .env before reading the environment to handle import-order issues.
    """
    global _client
    if _client is not None:
        return _client

    # Ensure .env is loaded for subprocesses and CLI runs
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        _client = OpenAI(api_key=api_key)
    except Exception:
        # If key invalid or client init fails, return None so caller can fallback
        _client = None
    return _client


def _load_cache() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    try:
        if _cache_path.exists():
            _cache = json.loads(_cache_path.read_text())
        else:
            _cache_path.parent.mkdir(parents=True, exist_ok=True)
            _cache = {}
    except Exception:
        _cache = {}
    return _cache


def _save_cache() -> None:
    try:
        if _cache is not None:
            _cache_path.parent.mkdir(parents=True, exist_ok=True)
            _cache_path.write_text(json.dumps(_cache, indent=2))
    except Exception:
        pass


def add_value_estimation(card_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add GPT-powered value estimation to card data
    Returns updated card data with value_estimate field
    """
    try:
        # MODE: control work to keep processing fast
        load_dotenv()
        mode = (os.getenv("VALUE_ESTIMATE_MODE", "heuristic").strip().lower())

        # Build idempotent cache key from salient fields
        key_fields = {
            'name': card_data.get('name'),
            'year': card_data.get('copyright_year'),
            'brand': card_data.get('brand'),
            'set': card_data.get('card_set'),
            'number': card_data.get('number'),
            'condition': str(card_data.get('condition')).replace('_', ' ').lower() if card_data.get('condition') else None,
            'sport': card_data.get('sport'),
            'features': str(card_data.get('features', 'none')).replace('_', ' ').lower(),
            'team': card_data.get('team'),
        }
        cache_key = json.dumps(key_fields, sort_keys=True)

        # Try cache first regardless of mode
        cache = _load_cache()
        if cache_key in cache:
            enhanced_data = card_data.copy()
            enhanced_data['value_estimate'] = cache[cache_key]['value_range']
            enhanced_data['_value_details'] = cache[cache_key]
            return enhanced_data

        # Fast paths
        if mode in ("off", "disabled"):
            # Do not add any estimate
            enhanced_data = card_data.copy()
            return enhanced_data
        if mode in ("heuristic", "fast"):
            # Lightweight heuristic, then cache
            value_range = _heuristic_range(card_data)
            details = {
                'confidence': 'low',
                'reasoning': 'Heuristic estimate (fast mode)',
                'source': 'heuristic'
            }
            cache[cache_key] = {'value_range': value_range, **details}
            _save_cache()
            enhanced_data = card_data.copy()
            enhanced_data['value_estimate'] = value_range
            enhanced_data['_value_details'] = details
            return enhanced_data

        # Build prompt for GPT value estimation
        estimation_prompt = f"""You are a professional trading card appraiser with expertise in sports card valuation. Estimate the current market value of this trading card based on the provided information.

Card Details:
- Player: {card_data.get('name', 'Unknown')}
- Year: {card_data.get('copyright_year', 'Unknown')}
- Brand: {card_data.get('brand', 'Unknown')}
- Set: {card_data.get('card_set', 'Unknown')}
- Card Number: {card_data.get('number', 'Unknown')}
- Condition: {card_data.get('condition', 'Unknown')}
- Sport: {card_data.get('sport', 'Baseball')}
- Features: {card_data.get('features', 'None')}
- Team: {card_data.get('team', 'Unknown')}

Instructions:
1. Consider current market trends, player significance, card rarity, condition, and historical sales
2. Provide a realistic value range for the current market (not peak/bubble prices)
3. Account for condition impact on value
4. Consider if this is a rookie card, star player, or Hall of Famer
5. Factor in brand significance and set popularity

Return ONLY a JSON object with this exact format:
{{
  "value_range": "$X-Y",
  "confidence": "high|medium|low",
  "reasoning": "Brief explanation of key value factors"
}}

Be conservative and realistic in your estimates. Consider actual sales data and current market conditions."""

        client = _get_client()
        if client is None:
            raise RuntimeError("OPENAI_API_KEY missing; using fallback value estimate")

        # Get GPT response
        response = llm_chat(
            messages=[
                {"role": "system", "content": "You are a professional sports card appraiser with deep knowledge of trading card markets, player values, and pricing trends."},
                {"role": "user", "content": estimation_prompt}
            ],
            max_tokens=300,
            temperature=0.1,
            client_override=client,
        )
        
        # Parse GPT response
        response_text = response.choices[0].message.content.strip()
        
        # Clean and parse JSON
        if response_text.startswith("```json"):
            response_text = response_text[7:].strip()
        if response_text.endswith("```"):
            response_text = response_text[:-3].strip()
        
        value_data = json.loads(response_text)
        
        # Add to card data
        enhanced_data = card_data.copy()
        enhanced_data['value_estimate'] = value_data.get('value_range', '$1-5')
        enhanced_data['_value_details'] = {
            'confidence': value_data.get('confidence', 'low'),
            'reasoning': value_data.get('reasoning', 'GPT-powered estimate'),
            'source': 'gpt_valuation'
        }
        # Cache successful responses
        _cache = _load_cache()
        _cache[cache_key] = {
            'value_range': enhanced_data['value_estimate'],
            **enhanced_data['_value_details'],
        }
        _save_cache()

        return enhanced_data
        
    except Exception as e:
        print(f"Error in GPT value estimation: {e}")
        # Fallback to simple estimate
        enhanced_data = card_data.copy()
        value_range = _heuristic_range(card_data)
        enhanced_data['value_estimate'] = value_range
        enhanced_data['_value_details'] = {
            'confidence': 'low',
            'reasoning': f'Fallback estimate (GPT error: {str(e)})',
            'source': 'fallback'
        }
        return enhanced_data


def _heuristic_range(card: Dict[str, Any]) -> str:
    """A simple, fast heuristic range used for performance.
    Kept consistent with the backfill script.
    """
    try:
        features = str(card.get('features') or '').lower()
        condition = str(card.get('condition') or '').lower().replace('_', ' ')
        year = None
        if card.get('copyright_year'):
            year = int(str(card['copyright_year']))
    except Exception:
        features, condition, year = '', '', None

    low, high = 1, 5
    if 'autograph' in features:
        low, high = 20, 200
    elif 'rookie' in features:
        low, high = 5, 25
    elif 'hall of fame' in features or 'hof' in features:
        low, high = 5, 20
    if year and year <= 1979:
        low = max(low, 5)
        high = max(high, 30)
    if condition in {'poor', 'fair'}:
        high = max(3, min(high, 8))
        low = max(1, min(low, 2))
    elif condition in {'excellent', 'near mint', 'mint', 'gem mint'}:
        high = int(high * 1.5)
    return f"${low}-{high}"
