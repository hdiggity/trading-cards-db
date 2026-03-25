#!/usr/bin/env zsh
# Sync unprocessed card photos to VM and run the pipeline there.
# Usage: ./infrastructure/sync-cards-to-vm.sh
set -euo pipefail

VM_INSTANCE=trading-cards
VM_ZONE=us-central1-a
VM_CARDS_DIR=/opt/trading_cards_db/cards
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

BULK_BACK="$LOCAL_DIR/cards/unprocessed_bulk_back"

if [[ -z "$(ls -A "$BULK_BACK" 2>/dev/null)" ]]; then
  echo "==> nothing in unprocessed_bulk_back, nothing to process"
  exit 0
fi

echo "==> syncing $(ls "$BULK_BACK" | wc -l | tr -d ' ') photos to VM..."
tar -czf - -C "$LOCAL_DIR/cards" unprocessed_bulk_back \
  | gcloud compute ssh "harlan@$VM_INSTANCE" --zone="$VM_ZONE" --ssh-flag="-T" -- \
    "tar -xzf - -C $VM_CARDS_DIR" 2>&1 | grep -v 'Ignoring unknown' || true

echo "==> running pipeline on VM..."
gcloud compute ssh "harlan@$VM_INSTANCE" --zone="$VM_ZONE" -- \
  "cd /opt/trading_cards_db && source .venv/bin/activate && python -m app.run --grid"

echo "==> done. open https://trading-cards.harlanswitzer.com to verify cards."
