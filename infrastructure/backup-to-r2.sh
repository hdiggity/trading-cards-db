#!/bin/bash
# Backs up all VM card data to Cloudflare R2.
# Verified images are only on VM (not local), so R2 is their offsite backup.
# Runs nightly via cron. ~1GB images + ~22MB DBs, well within 10GB free tier.
set -euo pipefail

BASE="/opt/trading_cards_db"
BUCKET="r2:trading-cards-backup"
LOG="/opt/trading_cards_db/logs/r2-backup.log"

mkdir -p "$(dirname "$LOG")"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting backup" >> "$LOG"

# Databases and models (critical — cannot be regenerated)
rclone copy "$BASE/cards/verified/trading_cards.db" "$BUCKET/cards/verified/" --checksum --exclude '._*' >> "$LOG" 2>&1
rclone copy "$BASE/data/corrections.db"             "$BUCKET/data/"           --checksum --exclude '._*' >> "$LOG" 2>&1
rclone copy "$BASE/data/canonical_names.db"         "$BUCKET/data/"           --checksum --exclude '._*' >> "$LOG" 2>&1
rclone sync "$BASE/data/ml_models/"                 "$BUCKET/data/ml_models/" --checksum --exclude '._*' >> "$LOG" 2>&1

# Verified images (only copy on VM — not stored locally after processing)
rclone sync "$BASE/cards/verified/verified_cropped_backs/" "$BUCKET/cards/verified/verified_cropped_backs/" --checksum --exclude '._*' >> "$LOG" 2>&1
rclone sync "$BASE/cards/verified/verified_bulk_back/"     "$BUCKET/cards/verified/verified_bulk_back/"     --checksum --exclude '._*' >> "$LOG" 2>&1

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup complete" >> "$LOG"
