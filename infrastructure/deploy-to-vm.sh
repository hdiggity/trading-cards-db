#!/usr/bin/env zsh
# Deploy local trading_cards_db to the Google Cloud VM via git push + pull
# Usage: ./infrastructure/deploy-to-vm.sh [--server-only]
#   --server-only  skip React build (use for server.js / Python changes only)
set -euo pipefail

VM_INSTANCE=trading-cards
VM_ZONE=us-central1-a
APP_DIR=/opt/trading_cards_db
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

SERVER_ONLY=0
[[ ${1:-} == "--server-only" ]] && SERVER_ONLY=1

echo "==> pushing to origin..."
git -C "$LOCAL_DIR" push origin main

echo "==> pulling on VM..."
gcloud compute ssh "harlan@$VM_INSTANCE" --zone="$VM_ZONE" -- \
  "cd $APP_DIR && git pull origin main"

echo "==> installing/updating npm deps on VM..."
gcloud compute ssh "harlan@$VM_INSTANCE" --zone="$VM_ZONE" -- \
  "cd $APP_DIR/app/ui && npm ci --omit=dev --silent"

if [[ $SERVER_ONLY -eq 0 ]]; then
  echo "==> building React production bundle on VM..."
  gcloud compute ssh "harlan@$VM_INSTANCE" --zone="$VM_ZONE" -- \
    "cd $APP_DIR/app/ui/client && npm ci --silent && npm run build"
fi

echo "==> restarting service on VM..."
gcloud compute ssh "harlan@$VM_INSTANCE" --zone="$VM_ZONE" -- \
  "sudo systemctl restart trading-cards && sudo systemctl status trading-cards --no-pager"

echo "==> done. health: curl https://cards-origin.harlanswitzer.com/health"
