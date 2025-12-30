import os
import shutil
import sqlite3
from pathlib import Path
from typing import List, Optional


class FileMovementTracker:
    """Track and reverse file movements for undo functionality."""

    def __init__(self, db_path: str = "logs/file_movements.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize file movements database."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS file_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id TEXT NOT NULL,
                source_path TEXT NOT NULL,
                dest_path TEXT NOT NULL,
                file_type TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                reversed BOOLEAN DEFAULT 0
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_transaction_id
            ON file_movements(transaction_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_reversed
            ON file_movements(reversed)
        """)

        conn.commit()
        conn.close()

    def record_movement(
        self,
        source: str,
        dest: str,
        transaction_id: str,
        file_type: Optional[str] = None
    ):
        """Record file movement.

        Args:
            source: Source file path
            dest: Destination file path
            transaction_id: UUID of associated transaction
            file_type: Type of file (cropped_back, bulk_back, json)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO file_movements
            (transaction_id, source_path, dest_path, file_type, reversed)
            VALUES (?, ?, ?, ?, 0)
        """, (transaction_id, source, dest, file_type))

        conn.commit()
        conn.close()

    def reverse_movement(self, transaction_id: str) -> dict:
        """Move files back to original location.

        Args:
            transaction_id: UUID of transaction to reverse

        Returns:
            dict with reversed_count and errors list
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, source_path, dest_path, file_type
            FROM file_movements
            WHERE transaction_id = ? AND reversed = 0
            ORDER BY id DESC
        """, (transaction_id,))

        movements = cursor.fetchall()
        reversed_count = 0
        errors = []

        for move_id, source, dest, file_type in movements:
            try:
                if os.path.exists(dest):
                    os.makedirs(os.path.dirname(source), exist_ok=True)
                    shutil.move(dest, source)
                    reversed_count += 1

                    cursor.execute("""
                        UPDATE file_movements
                        SET reversed = 1
                        WHERE id = ?
                    """, (move_id,))
                else:
                    errors.append(f"File not found: {dest}")
            except Exception as e:
                errors.append(f"Error reversing {dest} -> {source}: {str(e)}")

        conn.commit()
        conn.close()

        return {
            "reversed_count": reversed_count,
            "total_movements": len(movements),
            "errors": errors
        }

    def verify_files_exist(self, transaction_id: str) -> bool:
        """Check if all destination files exist before reversal.

        Args:
            transaction_id: UUID of transaction to check

        Returns:
            True if all files exist, False otherwise
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT dest_path
            FROM file_movements
            WHERE transaction_id = ? AND reversed = 0
        """, (transaction_id,))

        paths = cursor.fetchall()
        conn.close()

        for (dest_path,) in paths:
            if not os.path.exists(dest_path):
                return False

        return True

    def get_movements_for_transaction(self, transaction_id: str) -> List[dict]:
        """Get all file movements for a transaction.

        Args:
            transaction_id: UUID of transaction

        Returns:
            List of movement dicts
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, source_path, dest_path, file_type, reversed
            FROM file_movements
            WHERE transaction_id = ?
            ORDER BY id
        """, (transaction_id,))

        movements = []
        for row in cursor.fetchall():
            movements.append({
                "id": row[0],
                "source_path": row[1],
                "dest_path": row[2],
                "file_type": row[3],
                "reversed": bool(row[4])
            })

        conn.close()
        return movements
