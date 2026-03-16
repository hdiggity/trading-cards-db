#!/usr/bin/env bash
# VM setup script — run once on the Google Cloud VM as root or with sudo
# Prerequisites: Debian/Ubuntu Linux with systemd
set -euo pipefail

APP_DIR=/opt/trading_cards_db
APP_USER=harlan   # change to actual VM user if different
DOMAIN=cards-origin.harlanswitzer.com

echo "=== 1. System packages ==="
apt-get update -y
apt-get install -y curl git rsync python3 python3-pip python3-venv \
  nginx certbot python3-certbot-nginx \
  build-essential libffi-dev libssl-dev libjpeg-dev libpng-dev

echo "=== 2. Node.js (LTS via NodeSource) ==="
if ! command -v node &>/dev/null; then
  curl -fsSL https://deb.nodesource.com/setup_lts.x | bash -
  apt-get install -y nodejs
fi
node --version
npm --version

echo "=== 3. App directory ==="
mkdir -p "$APP_DIR"
chown "$APP_USER":"$APP_USER" "$APP_DIR"

echo "=== 4. Python venv + dependencies ==="
# Run as app user
sudo -u "$APP_USER" bash -c "
  cd $APP_DIR
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
"

echo "=== 5. npm install ==="
sudo -u "$APP_USER" bash -c "
  cd $APP_DIR/app/ui && npm ci --omit=dev
  cd $APP_DIR/app/ui/client && npm ci
"

echo "=== 6. React production build ==="
sudo -u "$APP_USER" bash -c "
  cd $APP_DIR/app/ui/client && npm run build
"

echo "=== 7. Nginx config ==="
cp "$APP_DIR/infrastructure/nginx-cards-origin.conf" /etc/nginx/sites-available/cards-origin.conf
ln -sf /etc/nginx/sites-available/cards-origin.conf /etc/nginx/sites-enabled/cards-origin.conf
nginx -t
systemctl reload nginx

echo "=== 8. TLS certificate ==="
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m admin@harlanswitzer.com
systemctl enable certbot.timer || true  # auto-renew

echo "=== 9. systemd service ==="
cp "$APP_DIR/infrastructure/trading-cards.service" /etc/systemd/system/trading-cards.service
systemctl daemon-reload
systemctl enable trading-cards
systemctl start trading-cards
systemctl status trading-cards --no-pager

echo ""
echo "=== DONE ==="
echo "Health check: curl https://$DOMAIN/health"
echo "Logs: journalctl -u trading-cards -f"
