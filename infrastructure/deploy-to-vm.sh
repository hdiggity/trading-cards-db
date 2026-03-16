#!/usr/bin/env zsh
# Deploy local trading_cards_db to the Google Cloud VM
# Usage: ./infrastructure/deploy-to-vm.sh <vm-user@vm-host> [--server-only]
#   --server-only  skip React build (use for server.js / Python changes only)
set -euo pipefail

# VM instance name and zone for gcloud
VM_INSTANCE=trading-cards
VM_ZONE=us-central1-a

SERVER_ONLY=0
[[ ${1:-} == "--server-only" ]] && SERVER_ONLY=1

APP_DIR=/opt/trading_cards_db
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [[ $SERVER_ONLY -eq 0 ]]; then
  echo "==> building React production bundle locally..."
  (cd "$LOCAL_DIR/app/ui/client" && npm run build)
else
  echo "==> skipping React build (--server-only)"
fi

echo "==> syncing code to VM..."
tar -czf - -C "$LOCAL_DIR" \
  --exclude='./app/ui/node_modules' \
  --exclude='./app/ui/client/node_modules' \
  --exclude='./.git' \
  --exclude='./cards' \
  --exclude='./data' \
  --exclude='./logs' \
  --exclude='./backups' \
  --exclude='./.venv' \
  --exclude='./__pycache__' \
  --exclude='./*.pyc' \
  . | gcloud compute ssh "harlan@$VM_INSTANCE" --zone="$VM_ZONE" -- "tar -xzf - -C $APP_DIR" 2>&1 | grep -v 'Ignoring unknown'

echo "==> installing/updating npm deps on VM..."
gcloud compute ssh "harlan@$VM_INSTANCE" --zone="$VM_ZONE" -- "cd $APP_DIR/app/ui && npm ci --omit=dev --silent"

echo "==> restarting service on VM..."
gcloud compute ssh "harlan@$VM_INSTANCE" --zone="$VM_ZONE" -- "sudo systemctl restart trading-cards && sudo systemctl status trading-cards --no-pager"

echo "==> done. health: curl https://cards-origin.harlanswitzer.com/health"
