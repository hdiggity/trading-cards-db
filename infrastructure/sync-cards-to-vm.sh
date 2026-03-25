#!/usr/bin/env zsh
# Sync unprocessed card photos to VM for pipeline processing.
# Pipeline runs on VM — local only stores original unprocessed HEICs.
# Usage: ./infrastructure/sync-cards-to-vm.sh
set -euo pipefail

VM_INSTANCE=trading-cards
VM_ZONE=us-central1-a
VM_CARDS_DIR=/opt/trading_cards_db/cards
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

BULK_BACK="$LOCAL_DIR/cards/unprocessed_bulk_back"

if [[ -z "$(ls -A "$BULK_BACK" 2>/dev/null)" ]]; then
  echo "==> nothing in unprocessed_bulk_back, nothing to sync"
  exit 0
fi

echo "==> syncing unprocessed_bulk_back to VM..."
tar -czf - -C "$LOCAL_DIR/cards" unprocessed_bulk_back \
  | gcloud compute ssh "harlan@$VM_INSTANCE" --zone="$VM_ZONE" --ssh-flag="-T" -- \
    "tar -xzf - -C $VM_CARDS_DIR" 2>&1 | grep -v 'Ignoring unknown' || true

echo "==> done. SSH to VM and run: python -m app.run --grid"
echo "    then open https://trading-cards.harlanswitzer.com to verify."
