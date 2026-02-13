import sys
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from sqlmodel import select

from app.database import get_session
from app.logging_system import ActionType, LogLevel, LogSource, logger
from app.models import Card, CardComplete, UndoTransaction
from app.schemas import CardCreate


def upsert_card(card_data: CardCreate, image_path: str = None, source_metadata: dict = None):
    """
    DEPRECATED: Direct card insertion is deprecated.
    Use insert_card_complete() instead - cards table is now auto-synced from cards_complete via triggers.

    This function maintained for backward compatibility only.
    """
    # For backward compatibility, insert into cards_complete which will trigger sync to cards
    return insert_card_complete(card_data, source_metadata or {})


def insert_card_complete(card_data: CardCreate, source_metadata: dict = None):
    """Insert a new card into cards_complete table. The cards table will be
    automatically updated via database triggers.

    Args:
        card_data: Card information to insert
        source_metadata: Optional metadata about the source scan (source_file, position, etc.)

    Returns:
        The created CardComplete record
    """
    data = card_data.model_dump()
    source_metadata = source_metadata or {}

    with get_session() as sess:
        # Find or create the card_id (cards table entry will be created by trigger if needed)
        # Use canonical_name for matching if available, otherwise fall back to exact name match
        canonical_name = data.get("canonical_name")

        if canonical_name:
            # Use canonical name for duplicate detection (handles name variations)
            stmt = select(Card).where(
                Card.brand == data.get("brand"),
                Card.number == data.get("number"),
                Card.canonical_name == canonical_name,
                Card.copyright_year == data.get("copyright_year"),
            )
        else:
            # Fallback to exact name match for backwards compatibility
            stmt = select(Card).where(
                Card.brand == data.get("brand"),
                Card.number == data.get("number"),
                Card.name == data.get("name"),
                Card.copyright_year == data.get("copyright_year"),
            )
        existing_card = sess.exec(stmt).first()
        card_id = existing_card.id if existing_card else None

        # If no existing card, we need to create a temporary one that will be updated by trigger
        if not card_id:
            temp_card = Card(**data)
            sess.add(temp_card)
            sess.flush()
            card_id = temp_card.id

        # Create CardComplete record (this will trigger update to cards table)
        card_complete = CardComplete(
            card_id=card_id,
            source_file=source_metadata.get('source_file'),
            grid_position=source_metadata.get('grid_position') or source_metadata.get('source_position'),
            original_filename=source_metadata.get('original_filename'),
            notes=source_metadata.get('notes'),
            verification_date=datetime.now(),  # Use local time, not UTC
            # Card data fields
            name=data.get("name"),
            canonical_name=data.get("canonical_name"),
            sport=data.get("sport"),
            brand=data.get("brand"),
            number=data.get("number"),
            copyright_year=data.get("copyright_year"),
            team=data.get("team"),
            card_set=data.get("card_set"),
            condition=data.get("condition"),
            is_player=data.get("is_player"),
            features=data.get("features"),
            value_estimate=data.get("value_estimate"),
            cropped_back_file=source_metadata.get('cropped_back_file'),
        )

        sess.add(card_complete)
        sess.commit()
        sess.refresh(card_complete)

        # Automatically merge any duplicates after insertion
        from app.auto_merge import auto_merge_duplicates_for_card
        merged_count = auto_merge_duplicates_for_card(card_id)
        if merged_count > 0:
            print(f"Auto-merged {merged_count} duplicate(s) for {card_complete.name}", file=sys.stderr)

        try:
            rec = f"{card_complete.name} #{card_complete.number or ''} {card_complete.brand or ''} {card_complete.copyright_year or ''}".strip()
            logger.log_database_operation(
                operation="insert", table="cards_complete", record_info=rec, success=True
            )
        except Exception:
            pass

        return card_complete


def list_cards() -> List[Card]:
    """Retrieve all cards in the database."""
    with get_session() as sess:
        rows = sess.exec(select(Card)).all()
        try:
            logger.log(
                LogLevel.INFO,
                LogSource.DATABASE,
                "List cards",
                ActionType.DB_QUERY,
                details=f"returned={len(rows)}",
            )
        except Exception:
            pass
        return rows


def get_card_by_id(card_id: int) -> Optional[Card]:
    """Fetch a single Card by its primary key."""
    with get_session() as sess:
        row = sess.get(Card, card_id)
        try:
            logger.log(
                LogLevel.INFO,
                LogSource.DATABASE,
                f"Get card by id {card_id}",
                ActionType.DB_QUERY,
                details="found" if row else "not_found",
            )
        except Exception:
            pass
        return row


def create_undo_transaction(
    file_id: str,
    action_type: str,
    before_state: Dict,
    card_index: Optional[int] = None
) -> str:
    """Create undo transaction record before database operation.

    Args:
        file_id: ID of the file being processed
        action_type: Type of action (pass_card, pass_all, fail_card, fail_all)
        before_state: State before operation (file paths, etc.)
        card_index: Index of card if single-card operation

    Returns:
        transaction_id (UUID string)
    """
    transaction_id = str(uuid.uuid4())

    with get_session() as sess:
        transaction = UndoTransaction(
            transaction_id=transaction_id,
            file_id=file_id,
            action_type=action_type,
            card_index=card_index,
            before_state=before_state,
            after_state=None,
            is_reversed=False
        )
        sess.add(transaction)
        sess.commit()

        try:
            logger.log(
                LogLevel.INFO,
                LogSource.DATABASE,
                f"Created undo transaction {transaction_id}",
                ActionType.DB_INSERT,
                details=f"file_id={file_id}, action={action_type}"
            )
        except Exception:
            pass

    return transaction_id


def update_undo_transaction_after_state(transaction_id: str, after_state: Dict):
    """Update transaction with after_state (DB IDs, file movements).

    Args:
        transaction_id: UUID of transaction to update
        after_state: State after operation (card_complete_ids, files_moved, etc.)
    """
    with get_session() as sess:
        transaction = sess.query(UndoTransaction).filter_by(
            transaction_id=transaction_id
        ).first()

        if transaction:
            transaction.after_state = after_state
            sess.commit()

            try:
                logger.log(
                    LogLevel.INFO,
                    LogSource.DATABASE,
                    f"Updated undo transaction {transaction_id} with after_state",
                    ActionType.DB_UPDATE
                )
            except Exception:
                pass


def undo_card_import(transaction_id: str) -> Dict:
    """Reverse a card import transaction.

    - Deletes cards_complete records
    - Database triggers automatically update cards table
    - Returns list of deleted IDs

    Args:
        transaction_id: UUID of transaction to reverse

    Returns:
        dict with deleted_ids and affected_cards
    """
    with get_session() as sess:
        transaction = sess.query(UndoTransaction).filter_by(
            transaction_id=transaction_id
        ).first()

        if not transaction:
            return {"error": "Transaction not found", "deleted_ids": []}

        if transaction.is_reversed:
            return {"error": "Transaction already reversed", "deleted_ids": []}

        after_state = transaction.after_state or {}
        card_complete_ids = after_state.get("card_complete_ids", [])

        deleted_ids = []
        for card_id in card_complete_ids:
            card_complete = sess.get(CardComplete, card_id)
            if card_complete:
                sess.delete(card_complete)
                deleted_ids.append(card_id)

        sess.commit()

        try:
            logger.log(
                LogLevel.INFO,
                LogSource.DATABASE,
                f"Undone card import for transaction {transaction_id}",
                ActionType.DB_DELETE,
                details=f"deleted_ids={deleted_ids}"
            )
        except Exception:
            pass

        return {
            "deleted_ids": deleted_ids,
            "affected_cards": len(deleted_ids)
        }


def mark_transaction_reversed(transaction_id: str):
    """Mark transaction as reversed with timestamp.

    Args:
        transaction_id: UUID of transaction to mark
    """
    with get_session() as sess:
        transaction = sess.query(UndoTransaction).filter_by(
            transaction_id=transaction_id
        ).first()

        if transaction:
            transaction.is_reversed = True
            transaction.reversed_at = datetime.now()
            sess.commit()

            try:
                logger.log(
                    LogLevel.INFO,
                    LogSource.DATABASE,
                    f"Marked transaction {transaction_id} as reversed",
                    ActionType.DB_UPDATE
                )
            except Exception:
                pass


def get_transactions_for_file(file_id: str) -> List[UndoTransaction]:
    """Get all transactions for a file (for undo_all).

    Args:
        file_id: File ID to query

    Returns:
        List of UndoTransaction objects
    """
    with get_session() as sess:
        transactions = sess.query(UndoTransaction).filter_by(
            file_id=file_id,
            is_reversed=False
        ).order_by(UndoTransaction.timestamp.desc()).all()

        return transactions
