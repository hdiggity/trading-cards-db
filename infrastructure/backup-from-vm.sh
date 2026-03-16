#!/usr/bin/env zsh
# Pull critical data from the VM back to local for git backup.
# Backs up: all SQLite DBs + pending verification JSON files.
# Card images are NOT pulled (too large) - they exist on both sides already.
# Usage: ./infrastructure/backup-from-vm.sh
set -euo pipefail

VM_INSTANCE=trading-cards
VM_ZONE=us-central1-a
VM_DIR=/opt/trading_cards_db
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> pulling databases from VM..."

# pull all .db files preserving directory structure
gcloud compute ssh "harlan@$VM_INSTANCE" --zone="$VM_ZONE" --ssh-flag="-T" -- \
  "cd $VM_DIR && find . -name '*.db' ! -path './.git/*' -print0 | tar -czf - --null -T -" \
  | tar -xzf - -C "$LOCAL_DIR" 2>&1 | grep -v 'Ignoring unknown'

echo "==> pulling pending verification JSON from VM..."
gcloud compute ssh "harlan@$VM_INSTANCE" --zone="$VM_ZONE" --ssh-flag="-T" -- \
  "cd $VM_DIR/cards && find pending_verification -name '*.json' -print0 2>/dev/null | tar -czf - --null -T - 2>/dev/null || tar -czf - -T /dev/null" \
  | tar -xzf - -C "$LOCAL_DIR/cards" 2>&1 | grep -v 'Ignoring unknown' || true

echo "==> done. commit to git to complete backup:"
echo "    cd $LOCAL_DIR && git add -A && git commit -m 'backup: db + pending json from vm'"
