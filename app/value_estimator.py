"""
GPT-powered value estimation system for trading cards
"""

import json
import os
from typing import Dict, Any
from openai import OpenAI

# Load OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def add_value_estimation(card_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add GPT-powered value estimation to card data
    Returns updated card data with value_estimate field
    """
    try:
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

        # Get GPT response
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a professional sports card appraiser with deep knowledge of trading card markets, player values, and pricing trends."},
                {"role": "user", "content": estimation_prompt}
            ],
            max_tokens=300,
            temperature=0.1
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
        
        return enhanced_data
        
    except Exception as e:
        print(f"Error in GPT value estimation: {e}")
        # Fallback to simple estimate
        enhanced_data = card_data.copy()
        enhanced_data['value_estimate'] = '$1-10'
        enhanced_data['_value_details'] = {
            'confidence': 'low',
            'reasoning': f'Fallback estimate (GPT error: {str(e)})',
            'source': 'fallback'
        }
        return enhanced_data