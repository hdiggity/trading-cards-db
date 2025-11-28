"""
Update database with model-predicted conditions for cards missing condition data.

This script:
1. Finds cards in the database that have cropped_back_file but no condition
2. Runs the condition predictor on those images
3. Updates the database with predicted conditions and confidence scores
"""

import sys
import sqlite3
from pathlib import Path
from typing import List, Dict

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.condition_predictor import ConditionPredictor


# Paths
BASE_DIR = Path(__file__).parent.parent.parent
CARDS_DIR = BASE_DIR / "cards" / "verified"
IMAGE_DIR = CARDS_DIR / "verified_cropped_backs"
DB_PATH = CARDS_DIR / "trading_cards.db"


def get_cards_without_condition() -> List[Dict]:
    """
    Query the database for cards that have cropped_back_file but no condition.

    Returns:
        List of dicts with card_id and cropped_back_file
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    query = """
        SELECT id, cropped_back_file
        FROM cards_complete
        WHERE cropped_back_file IS NOT NULL
        AND (condition IS NULL OR condition = '')
    """

    cursor.execute(query)
    results = cursor.fetchall()
    conn.close()

    cards = [
        {'id': card_id, 'cropped_back_file': filename}
        for card_id, filename in results
    ]

    return cards


def update_card_condition(card_id: int, condition: str, confidence: float):
    """
    Update a card's condition in the database.

    Args:
        card_id: The card's database ID
        condition: The predicted condition
        confidence: The prediction confidence (0-1)
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Update cards_complete table
    update_query = """
        UPDATE cards_complete
        SET condition = ?,
            notes = CASE
                WHEN notes IS NULL OR notes = '' THEN ?
                ELSE notes || ' | ' || ?
            END
        WHERE id = ?
    """

    confidence_note = f"Auto-predicted condition (confidence: {confidence:.1%})"

    cursor.execute(update_query, (condition, confidence_note, confidence_note, card_id))
    conn.commit()
    conn.close()


def main():
    """Main script to update conditions using the model."""
    print("="*70)
    print("Update Card Conditions with ML Model Predictions")
    print("="*70)

    # Check database exists
    if not DB_PATH.exists():
        print(f"Error: Database not found at {DB_PATH}")
        sys.exit(1)

    # Load cards without conditions
    print("\nFinding cards without condition data...")
    cards = get_cards_without_condition()

    if not cards:
        print("No cards found that need condition predictions.")
        print("All cards already have condition data!")
        return

    print(f"Found {len(cards)} cards without condition data")

    # Initialize predictor
    print("\nInitializing condition predictor...")
    try:
        predictor = ConditionPredictor()
    except Exception as e:
        print(f"Error loading model: {e}")
        print("\nPlease train the model first:")
        print("  python -m app.condition_model_trainer")
        sys.exit(1)

    # Process each card
    print("\nPredicting conditions...")
    print("-"*70)

    successful = 0
    failed = 0
    predictions = {'fair': 0, 'good': 0, 'very_good': 0}

    for i, card in enumerate(cards, 1):
        card_id = card['id']
        filename = card['cropped_back_file']
        image_path = IMAGE_DIR / filename

        # Show progress
        if i % 10 == 0:
            print(f"Processing {i}/{len(cards)}...")

        # Check image exists
        if not image_path.exists():
            print(f"Warning: Image not found - {filename}")
            failed += 1
            continue

        # Predict condition
        try:
            result = predictor.predict(image_path)

            if result['error']:
                print(f"Error predicting {filename}: {result['error']}")
                failed += 1
                continue

            condition = result['predicted_condition']
            confidence = result['confidence']

            # Update database
            update_card_condition(card_id, condition, confidence)

            predictions[condition] = predictions.get(condition, 0) + 1
            successful += 1

            # Show progress for low confidence predictions
            if confidence < 0.6:
                print(f"  {filename}: {condition} (LOW confidence: {confidence:.1%})")

        except Exception as e:
            print(f"Error processing {filename}: {e}")
            failed += 1

    # Summary
    print("\n" + "="*70)
    print("Update Complete!")
    print("="*70)
    print(f"\nResults:")
    print(f"  Successfully updated: {successful}/{len(cards)}")
    print(f"  Failed: {failed}/{len(cards)}")

    if successful > 0:
        print(f"\nPredicted condition distribution:")
        for condition, count in sorted(predictions.items()):
            percentage = (count / successful) * 100
            print(f"  {condition}: {count} ({percentage:.1f}%)")

        print(f"\nConditions have been updated in: {DB_PATH}")
        print("\nNote: Predictions are added to the 'notes' field for reference.")
        print("You can review and manually correct any predictions as needed.")


if __name__ == "__main__":
    main()
