Database Backups - Canonical Name Fixes (2026-01-01)

These backups were created during the fix_canonical_names.py script execution.

Fixes Applied:
1. Non-player cards (team checklists, multiple players) set to canonical_name=NULL, is_player=0
2. Parentheses in player names handled correctly (e.g., "rogelio moret (torres)" -> "rogelio moret")
3. Removed incorrect entries from canonical_names cache

Affected Cards:
- Card 84: "texas rangers team checklist" - Fixed
- Card 97: "bill grief, james rodney richard, ray busse" - Fixed
- Card 264: "enos cabell, pat bourque, gonzalo marquez" - Fixed
- Card 130: "rogelio moret (torres)" - Fixed
- Card 131: "enzo octavio hernandez (martinez)" - Fixed

Backup Files:
- trading_cards_backup_20260101_102727.db - Before first fix run
- trading_cards_backup_20260101_102814.db - Before second fix run (final)

Both backups preserved for recovery if needed.
