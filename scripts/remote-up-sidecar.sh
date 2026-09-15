#!/usr/bin/env bash
# On-server: rebuild the agent beside an existing app (no Caddy, no :80/:443).
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/frequency-lead-agent}"
cd "$APP_DIR"

if [[ ! -f .env ]]; then
  echo "ERROR: $APP_DIR/.env missing."
  exit 1
fi

# Do not steal the dating site's HTTPS domain on this VPS.
sed -i '/^FREQUENCY_DOMAIN=/d' .env

# Tovyq white-label (this VPS only — primary Frequency server is untouched).
if grep -qE '^APP_BRAND=' .env 2>/dev/null; then
  sed -i 's/^APP_BRAND=.*/APP_BRAND=Tovyq/' .env
else
  echo "APP_BRAND=Tovyq" >> .env
fi
if grep -qE '^APP_BRAND_DOMAIN=' .env 2>/dev/null; then
  sed -i 's/^APP_BRAND_DOMAIN=.*/APP_BRAND_DOMAIN=tovyq.swameda.com/' .env
else
  echo "APP_BRAND_DOMAIN=tovyq.swameda.com" >> .env
fi
if grep -qE '^APP_BRAND_URL=' .env 2>/dev/null; then
  sed -i 's|^APP_BRAND_URL=.*|APP_BRAND_URL=https://tovyq.swameda.com|' .env
else
  echo "APP_BRAND_URL=https://tovyq.swameda.com" >> .env
fi
# Keep the same Resend from-address (verified domain); change display name only.
sed -i 's/^RESET_EMAIL_FROM=Frequency /RESET_EMAIL_FROM=Tovyq /' .env || true

if ! grep -qE '^FREQUENCY_SECRETS_KEY=.+' .env 2>/dev/null; then
  if grep -qE '^CLERK_SECRET_KEY=.+' .env 2>/dev/null; then
    echo "FREQUENCY_SECRETS_KEY: unset (will use CLERK_SECRET_KEY fallback for Fernet)"
  else
    echo "FREQUENCY_SECRETS_KEY=$(openssl rand -hex 32)" >> .env
    echo "Added FREQUENCY_SECRETS_KEY"
  fi
fi
if ! grep -qE '^AUTH_SESSION_SECRET=.+' .env 2>/dev/null; then
  echo "AUTH_SESSION_SECRET=$(openssl rand -hex 32)" >> .env
  echo "Added AUTH_SESSION_SECRET"
fi

sed -i 's/\r$//' scripts/*.sh 2>/dev/null || true
chmod +x scripts/*.sh 2>/dev/null || true

echo "==> Building & starting sidecar stack (agent on :8501, no Caddy)"
docker compose -f docker-compose.yml -f docker-compose.sidecar.yml up -d --build --remove-orphans

echo "==> Status"
docker compose -f docker-compose.yml -f docker-compose.sidecar.yml ps
echo
echo "Health:"
sleep 2
curl -fsS -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8501/_stcore/health || true
echo "Done. Open https://tovyq.swameda.com/  (or http://$(hostname -I | awk '{print $1}'):8501/ until DNS/TLS)"
