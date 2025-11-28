#!/bin/bash

# Test script for automatic retraining system

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
export PYTHONPATH="$SCRIPT_DIR"
PYTHON="/opt/anaconda3/envs/trading_cards_db/bin/python3"

echo "=========================================="
echo "Testing Automatic Retraining System"
echo "=========================================="
echo ""

echo "1. Checking current training state..."
echo "--------------------------------------"
if [ -f "$SCRIPT_DIR/app/models/training_state.json" ]; then
    echo "Training state file exists:"
    cat "$SCRIPT_DIR/app/models/training_state.json" | $PYTHON -m json.tool
else
    echo "No training state file found (first run)"
fi
echo ""

echo "2. Checking if retraining is needed..."
echo "--------------------------------------"
$PYTHON -m app.auto_retrain --check-only
echo ""

echo "3. Current model status..."
echo "--------------------------------------"
if [ -f "$SCRIPT_DIR/app/models/condition_classifier.pkl" ]; then
    MODEL_SIZE=$(ls -lh "$SCRIPT_DIR/app/models/condition_classifier.pkl" | awk '{print $5}')
    MODEL_DATE=$(ls -l "$SCRIPT_DIR/app/models/condition_classifier.pkl" | awk '{print $6, $7, $8}')
    echo "Model exists: condition_classifier.pkl"
    echo "Size: $MODEL_SIZE"
    echo "Last modified: $MODEL_DATE"
else
    echo "No trained model found"
fi
echo ""

echo "4. Database statistics..."
echo "--------------------------------------"
TOTAL_CARDS=$(sqlite3 "$SCRIPT_DIR/cards/verified/trading_cards.db" "SELECT COUNT(*) FROM cards_complete WHERE condition IS NOT NULL AND condition != ''")
echo "Total labeled cards: $TOTAL_CARDS"

BULK_BACKS=$(sqlite3 "$SCRIPT_DIR/cards/verified/trading_cards.db" "SELECT COUNT(DISTINCT source_file) FROM cards_complete WHERE source_file IS NOT NULL")
echo "Total bulk backs: $BULK_BACKS"

echo ""
echo "Condition distribution:"
sqlite3 "$SCRIPT_DIR/cards/verified/trading_cards.db" "SELECT condition, COUNT(*) as count FROM cards_complete WHERE condition IS NOT NULL GROUP BY condition ORDER BY count DESC"
echo ""

echo "=========================================="
echo "Test Complete"
echo "=========================================="
echo ""
echo "To force retraining:"
echo "  $PYTHON -m app.auto_retrain --force"
echo ""
echo "To trigger normal auto-retrain:"
echo "  $PYTHON -m app.auto_retrain"
echo ""
