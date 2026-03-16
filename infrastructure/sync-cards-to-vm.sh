#!/usr/bin/env zsh
# Sync locally-processed cards to the VM for verification via the web UI.
# Usage: ./infrastructure/sync-cards-to-vm.sh [--all]
#   (default) syncs pending_verification/ and unprocessed_bulk_back/ only
#   --all      also syncs verified/ (large, use only when needed)
set -euo pipefail

VM_INSTANCE=trading-cards
VM_ZONE=us-central1-a
VM_CARDS_DIR=/opt/trading_cards_db/cards
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> syncing pending cards to VM..."

# sync pending_verification
echo "   pending_verification/"
tar -czf - -C "$LOCAL_DIR/cards" pending_verification \
  | gcloud compute ssh "harlan@$VM_INSTANCE" --zone="$VM_ZONE" --ssh-flag="-T" -- \
    "tar -xzf - -C $VM_CARDS_DIR" 2>&1 | grep -v 'Ignoring unknown' || true

# sync unprocessed_bulk_back (so the VM has the originals too if needed)
if [[ -d "$LOCAL_DIR/cards/unprocessed_bulk_back" ]] && [[ "$(ls -A "$LOCAL_DIR/cards/unprocessed_bulk_back" 2>/dev/null)" ]]; then
  echo "   unprocessed_bulk_back/"
  tar -czf - -C "$LOCAL_DIR/cards" unprocessed_bulk_back \
    | gcloud compute ssh "harlan@$VM_INSTANCE" --zone="$VM_ZONE" -- \
      "tar -xzf - -C $VM_CARDS_DIR" 2>&1 | grep -v 'Ignoring unknown' || true
fi

if [[ ${1:-} == "--all" ]]; then
  echo "   verified/ (--all flag)"
  tar -czf - -C "$LOCAL_DIR/cards" verified \
    | gcloud compute ssh "harlan@$VM_INSTANCE" --zone="$VM_ZONE" -- \
      "tar -xzf - -C $VM_CARDS_DIR" 2>&1 | grep -v 'Ignoring unknown' || true
fi

echo "==> done. open https://trading-cards.harlanswitzer.com to verify."
