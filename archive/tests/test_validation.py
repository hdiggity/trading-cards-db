#!/usr/bin/env python3
"""
Quick test of checklist validation system
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from app.card_set_database import CardSetDatabase

# Test data
test_cards = [
    # Exact match (should boost confidence)
    {
        'brand': 'topps',
        'copyright_year': '1984',
        'number': '1',
        'name': 'tony gwynn'
    },
    # Fuzzy match (OCR error)
    {
        'brand': 'topps',
        'copyright_year': '1984',
        'number': '3',
        'name': 'dan quizzenberry'  # Should match "dan quisenberry"
    },
    # Wrong name (should flag mismatch)
    {
        'brand': 'topps',
        'copyright_year': '1984',
        'number': '245',
        'name': 'cleveland indians'  # Should be "rick sutcliffe"
    },
    # Not in database
    {
        'brand': 'topps',
        'copyright_year': '1984',
        'number': '999',
        'name': 'unknown player'
    },
]

print("Testing Checklist Validation System")
print("=" * 60)

db = CardSetDatabase()

for i, card in enumerate(test_cards, 1):
    print(f"\nTest {i}: {card['name']}")
    print(f"  Brand: {card['brand']}, Year: {card['copyright_year']}, Number: {card['number']}")

    validation = db.validate_extraction(card)

    print(f"  Status: {validation.get('valid')}")
    print(f"  Message: {validation.get('message')}")

    if validation.get('suggestion'):
        print(f"  Suggestion: {validation['suggestion']}")

    if validation.get('similarity') is not None:
        print(f"  Similarity: {validation['similarity']:.2%}")

    if validation.get('expected'):
        expected = validation['expected']
        print(f"  Expected: {expected.player_name} ({expected.team})")

db.close()

print("\n" + "=" * 60)
print("Validation system test complete")
print("\nNow integrated into enhanced extraction pipeline:")
print("  - Exact matches get +20% confidence boost")
print("  - Fuzzy matches show suggestions for review")
print("  - Mismatches get -30% confidence penalty")
print("  - All validation results stored in _validation field")
