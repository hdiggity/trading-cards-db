#!/usr/bin/env bash
# Sync all card images from VM to R2 trading-cards bucket.
# Run from repo root: ./workers/migrate/sync-images-to-r2.sh
set -euo pipefail

TMP=$(mktemp -d)
echo "==> downloading images from VM to $TMP..."

gcloud compute ssh "harlan@trading-cards" --zone=us-central1-a -- \
  "tar -czf /tmp/card-images.tar.gz -C /opt/trading_cards_db/cards verified pending_verification 2>/dev/null || tar -czf /tmp/card-images.tar.gz -C /opt/trading_cards_db/cards verified" \
  2>&1 | grep -v 'Ignoring unknown'

gcloud compute scp "harlan@trading-cards:/tmp/card-images.tar.gz" "$TMP/" \
  --zone=us-central1-a 2>&1 | grep -v 'Ignoring unknown'

echo "==> extracting..."
tar -xzf "$TMP/card-images.tar.gz" -C "$TMP"

cd workers/api

echo "==> uploading verified images..."
find "$TMP/verified" -type f \( -name "*.jpg" -o -name "*.jpeg" -o -name "*.png" \) 2>/dev/null | while read f; do
  key="verified/images/$(basename "$f")"
  npx wrangler r2 object put "trading-cards/$key" --file="$f" --content-type="image/jpeg" 2>/dev/null && echo "  $key"
done

echo "==> uploading pending images..."
find "$TMP/pending_verification" -type f \( -name "*.jpg" -o -name "*.jpeg" -o -name "*.png" \) 2>/dev/null | while read f; do
  key="pending/images/$(basename "$f")"
  npx wrangler r2 object put "trading-cards/$key" --file="$f" --content-type="image/jpeg" 2>/dev/null && echo "  $key"
done

echo "==> cleanup $TMP"
rm -rf "$TMP"
echo "==> done"
