"""Automatic duplicate merging for cards with same canonical name."""

import sys

from sqlalchemy import text

from app.database import get_session


def auto_merge_duplicates_for_card(card_id: int) -> int:
    """Automatically merge any duplicates for a given card.

    Finds all cards with the same canonical_name, brand, number, and copyright_year,
    then merges them into the card with the highest quantity.

    Args:
        card_id: The ID of the card that was just inserted/updated

    Returns:
        Number of duplicates merged (0 if no duplicates found)
    """
    with get_session() as session:
        # Get the card details
        card = session.execute(
            text("SELECT canonical_name, brand, number, copyright_year FROM cards WHERE id = :card_id"),
            {"card_id": card_id}
        ).fetchone()

        if not card or not card[0]:  # No card or no canonical_name
            return 0

        canonical_name, brand, number, copyright_year = card

        # Find all duplicates (same canonical_name, brand, number, year)
        duplicates = session.execute(
            text("""
                SELECT id, quantity
                FROM cards
                WHERE canonical_name = :canonical_name
                AND brand = :brand
                AND number = :number
                AND copyright_year = :copyright_year
                ORDER BY quantity DESC, id ASC
            """),
            {
                "canonical_name": canonical_name,
                "brand": brand,
                "number": number,
                "copyright_year": copyright_year
            }
        ).fetchall()

        if len(duplicates) <= 1:
            return 0  # No duplicates

        # Keep the first one (highest quantity), merge others into it
        keep_id = duplicates[0][0]
        delete_ids = [dup[0] for dup in duplicates[1:]]

        print(f"Auto-merging duplicates: keeping card {keep_id}, merging {len(delete_ids)} duplicates", file=sys.stderr)

        # Reassign all CardComplete records to the kept card
        for del_id in delete_ids:
            session.execute(
                text("UPDATE cards_complete SET card_id = :keep_id WHERE card_id = :del_id"),
                {"keep_id": keep_id, "del_id": del_id}
            )

        # Delete duplicate card entries
        for del_id in delete_ids:
            session.execute(
                text("DELETE FROM cards WHERE id = :del_id"),
                {"del_id": del_id}
            )

        # Update quantity on kept card
        session.execute(
            text("""
                UPDATE cards
                SET quantity = (SELECT COUNT(*) FROM cards_complete WHERE card_id = :keep_id)
                WHERE id = :keep_id
            """),
            {"keep_id": keep_id}
        )

        session.commit()

        return len(delete_ids)
