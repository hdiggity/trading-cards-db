import os
import shutil
from datetime import datetime
from pathlib import Path


def backup_database(db_path: str = "trading_cards.db", backup_dir: str = "backups", retention: int = 20) -> str:
    """
    Create a timestamped backup copy of the SQLite database.

    - Places backups under `<backup_dir>/` with filename `trading_cards_YYYYmmdd_HHMMSS.db`.
    - Keeps only the latest `retention` backups (older ones are deleted).

    Returns the full path to the created backup file.
    """
    db_file = Path(db_path)
    if not db_file.exists():
        # Nothing to back up
        return ""

    backup_root = Path(backup_dir)
    backup_root.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_name = f"trading_cards_{stamp}.db"
    out_path = backup_root / out_name

    # Use copy2 to preserve timestamps/metadata
    shutil.copy2(db_file, out_path)

    # Retention policy: delete oldest beyond retention count
    backups = sorted(backup_root.glob("trading_cards_*.db"))
    if len(backups) > retention:
        to_delete = backups[: len(backups) - retention]
        for p in to_delete:
            try:
                p.unlink()
            except Exception:
                pass

    # Optional: write/update a 'latest' symlink/copy for convenience
    latest_link = backup_root / "latest.db"
    try:
        if latest_link.exists() or latest_link.is_symlink():
            latest_link.unlink()
        # On platforms without symlink perms, fall back to copying
        try:
            latest_link.symlink_to(out_path.name)
        except Exception:
            shutil.copy2(out_path, latest_link)
    except Exception:
        pass

    return str(out_path)

