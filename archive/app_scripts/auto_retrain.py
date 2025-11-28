"""
Automatic model retraining system for condition classification.

This module detects when a bulk back batch has been fully verified and
automatically triggers model retraining with the new labeled data.
"""

import os
import sys
import json
import sqlite3
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Paths
BASE_DIR = Path(__file__).parent.parent
CARDS_DIR = BASE_DIR / "cards"
VERIFIED_DIR = CARDS_DIR / "verified"
DB_PATH = VERIFIED_DIR / "trading_cards.db"
MODEL_DIR = BASE_DIR / "app" / "models"
TRAINING_STATE_FILE = MODEL_DIR / "training_state.json"

# Ensure directories exist
MODEL_DIR.mkdir(exist_ok=True)


class TrainingState:
    """
    Tracks training state to know when to retrain.

    Stores:
    - last_training_time: When the model was last trained
    - last_card_count: Number of cards in the last training
    - bulk_backs_processed: List of bulk back files that have been processed
    """

    def __init__(self, state_file: Path = TRAINING_STATE_FILE):
        self.state_file = state_file
        self.state = self._load_state()

    def _load_state(self) -> Dict:
        """Load training state from disk."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Could not load training state: {e}")

        return {
            'last_training_time': None,
            'last_card_count': 0,
            'bulk_backs_processed': [],
            'training_history': []
        }

    def _save_state(self):
        """Save training state to disk."""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=2)
            logger.info(f"Saved training state to {self.state_file}")
        except Exception as e:
            logger.error(f"Could not save training state: {e}")

    def get_last_training_time(self) -> Optional[str]:
        """Get the timestamp of the last training."""
        return self.state.get('last_training_time')

    def get_last_card_count(self) -> int:
        """Get the number of cards in the last training."""
        return self.state.get('last_card_count', 0)

    def get_processed_bulk_backs(self) -> List[str]:
        """Get list of bulk backs that have been processed."""
        return self.state.get('bulk_backs_processed', [])

    def mark_bulk_back_processed(self, bulk_back_file: str):
        """Mark a bulk back file as processed."""
        if bulk_back_file not in self.state['bulk_backs_processed']:
            self.state['bulk_backs_processed'].append(bulk_back_file)
            self._save_state()

    def update_after_training(self, card_count: int, bulk_back_files: List[str] = None):
        """Update state after successful training."""
        self.state['last_training_time'] = datetime.now().isoformat()
        self.state['last_card_count'] = card_count

        # Add to training history
        history_entry = {
            'timestamp': self.state['last_training_time'],
            'card_count': card_count,
            'bulk_backs': bulk_back_files or []
        }

        if 'training_history' not in self.state:
            self.state['training_history'] = []

        self.state['training_history'].append(history_entry)

        # Mark bulk backs as processed
        if bulk_back_files:
            for bf in bulk_back_files:
                if bf not in self.state['bulk_backs_processed']:
                    self.state['bulk_backs_processed'].append(bf)

        self._save_state()


def get_verified_bulk_backs() -> List[str]:
    """
    Get list of verified bulk back files from the database.

    Returns:
        List of unique source_file names that represent bulk backs
    """
    if not DB_PATH.exists():
        logger.warning(f"Database not found at {DB_PATH}")
        return []

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Get unique source files that have verified cards
    query = """
        SELECT DISTINCT source_file
        FROM cards_complete
        WHERE source_file IS NOT NULL
        AND source_file != ''
        ORDER BY source_file
    """

    cursor.execute(query)
    results = cursor.fetchall()
    conn.close()

    return [row[0] for row in results]


def get_card_count_for_source(source_file: str) -> int:
    """Get the number of verified cards from a specific source file."""
    if not DB_PATH.exists():
        return 0

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    query = """
        SELECT COUNT(*)
        FROM cards_complete
        WHERE source_file = ?
        AND condition IS NOT NULL
        AND condition != ''
    """

    cursor.execute(query, (source_file,))
    count = cursor.fetchone()[0]
    conn.close()

    return count


def get_total_labeled_cards() -> int:
    """Get total number of cards with condition labels."""
    if not DB_PATH.exists():
        return 0

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    query = """
        SELECT COUNT(*)
        FROM cards_complete
        WHERE condition IS NOT NULL
        AND condition != ''
        AND cropped_back_file IS NOT NULL
    """

    cursor.execute(query)
    count = cursor.fetchone()[0]
    conn.close()

    return count


def check_if_retraining_needed(min_new_cards: int = 9) -> Dict:
    """
    Check if model retraining is needed.

    Args:
        min_new_cards: Minimum number of new cards needed to trigger retraining
                      (default 9, which is one complete 3x3 grid)

    Returns:
        Dict with:
            - should_retrain: bool
            - reason: str
            - current_card_count: int
            - new_cards_since_last_training: int
            - new_bulk_backs: List[str]
    """
    state = TrainingState()

    current_card_count = get_total_labeled_cards()
    last_card_count = state.get_last_card_count()
    new_cards = current_card_count - last_card_count

    # Get all verified bulk backs
    all_bulk_backs = get_verified_bulk_backs()
    processed_bulk_backs = state.get_processed_bulk_backs()

    # Find new bulk backs that haven't been processed
    new_bulk_backs = [bf for bf in all_bulk_backs if bf not in processed_bulk_backs]

    result = {
        'should_retrain': False,
        'reason': '',
        'current_card_count': current_card_count,
        'last_card_count': last_card_count,
        'new_cards_since_last_training': new_cards,
        'new_bulk_backs': new_bulk_backs,
        'new_bulk_back_count': len(new_bulk_backs)
    }

    # Check if we have any new bulk backs
    if len(new_bulk_backs) > 0:
        result['should_retrain'] = True
        result['reason'] = f"New bulk back(s) verified: {', '.join(new_bulk_backs)}"
        return result

    # Check if we have enough new cards even without a new bulk back
    if new_cards >= min_new_cards:
        result['should_retrain'] = True
        result['reason'] = f"{new_cards} new labeled cards available (threshold: {min_new_cards})"
        return result

    result['reason'] = f"Not enough new data ({new_cards} new cards, need {min_new_cards})"
    return result


def trigger_model_retraining() -> bool:
    """
    Trigger the model retraining process.

    Returns:
        True if retraining succeeded, False otherwise
    """
    logger.info("Starting model retraining...")

    trainer_script = BASE_DIR / "app" / "condition_model_trainer.py"

    if not trainer_script.exists():
        logger.error(f"Training script not found at {trainer_script}")
        return False

    try:
        # Run the training script
        python_executable = sys.executable

        logger.info(f"Running: {python_executable} {trainer_script}")

        result = subprocess.run(
            [python_executable, str(trainer_script)],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=600  # 10 minute timeout
        )

        if result.returncode == 0:
            logger.info("Model retraining completed successfully!")
            logger.info(f"Training output:\n{result.stdout}")

            # Update training state
            current_card_count = get_total_labeled_cards()
            new_bulk_backs = get_verified_bulk_backs()

            state = TrainingState()
            state.update_after_training(current_card_count, new_bulk_backs)

            return True
        else:
            logger.error(f"Model retraining failed with exit code {result.returncode}")
            logger.error(f"Error output:\n{result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        logger.error("Model retraining timed out after 10 minutes")
        return False
    except Exception as e:
        logger.error(f"Error during model retraining: {e}")
        return False


def auto_retrain_if_needed(min_new_cards: int = 9) -> Dict:
    """
    Check if retraining is needed and trigger it if necessary.

    Args:
        min_new_cards: Minimum number of new cards to trigger retraining

    Returns:
        Dict with results of the check and training attempt
    """
    logger.info("Checking if model retraining is needed...")

    check_result = check_if_retraining_needed(min_new_cards)

    result = {
        **check_result,
        'retraining_attempted': False,
        'retraining_succeeded': False
    }

    if check_result['should_retrain']:
        logger.info(f"Retraining needed: {check_result['reason']}")

        result['retraining_attempted'] = True
        result['retraining_succeeded'] = trigger_model_retraining()
    else:
        logger.info(f"No retraining needed: {check_result['reason']}")

    return result


def main():
    """CLI interface for auto-retraining."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Automatically retrain condition model when new data is available'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Force retraining even if not enough new data'
    )
    parser.add_argument(
        '--min-new-cards',
        type=int,
        default=9,
        help='Minimum new cards needed to trigger retraining (default: 9)'
    )
    parser.add_argument(
        '--check-only',
        action='store_true',
        help='Only check if retraining is needed, do not actually retrain'
    )

    args = parser.parse_args()

    if args.force:
        logger.info("Force retraining requested...")
        success = trigger_model_retraining()
        sys.exit(0 if success else 1)

    if args.check_only:
        check_result = check_if_retraining_needed(args.min_new_cards)
        print(json.dumps(check_result, indent=2))
        sys.exit(0)

    # Normal auto-retrain
    result = auto_retrain_if_needed(args.min_new_cards)
    print(json.dumps(result, indent=2))

    if result['retraining_attempted'] and not result['retraining_succeeded']:
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
