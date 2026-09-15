#!/usr/bin/env bash
# On-server: rebuild and restart production stack.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/frequency-lead-agent}"
cd "$APP_DIR"

if [[ ! -f .env ]]; then
  echo "ERROR: $APP_DIR/.env missing. Copy from laptop or .env.example and fill secrets."
  exit 1
fi

# Ensure encryption secrets exist (idempotent).
# Prefer existing FREQUENCY_SECRETS_KEY. If missing but CLERK_SECRET_KEY is set,
# leave unset so Fernet matches local (accounts.py falls back to Clerk) — do NOT
# invent a random key that would brick encrypted user Tavily keys.
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

DOMAIN="$(grep -E '^FREQUENCY_DOMAIN=' .env 2>/dev/null | head -n1 | cut -d= -f2- | tr -d '\r' | xargs || true)"
ACME_EMAIL="$(grep -E '^CADDY_ACME_EMAIL=' .env 2>/dev/null | head -n1 | cut -d= -f2- | tr -d '\r' | xargs || true)"
ACME_EMAIL="${ACME_EMAIL:-ops@frequency.cx}"

mkdir -p deploy

# Bake Caddyfile (literal host) so empty env vars cannot break Caddy.
if [[ -n "$DOMAIN" ]]; then
  echo "==> Caddy HTTPS for domain: $DOMAIN (IP :80 kept as HTTP fallback)"
  cat > deploy/Caddyfile <<EOF
{
	email ${ACME_EMAIL}
}

:80 {
	encode gzip zstd
	header {
		X-Content-Type-Options nosniff
		Referrer-Policy strict-origin-when-cross-origin
		-Server
	}
	reverse_proxy agent:8501 {
		flush_interval -1
		header_up Host {host}
		header_up X-Real-IP {remote_host}
		header_up X-Forwarded-For {remote_host}
		header_up X-Forwarded-Proto {scheme}
	}
}

${DOMAIN} {
	encode gzip zstd
	header {
		X-Content-Type-Options nosniff
		Referrer-Policy strict-origin-when-cross-origin
		-Server
	}
	reverse_proxy agent:8501 {
		flush_interval -1
		header_up Host {host}
		header_up X-Real-IP {remote_host}
		header_up X-Forwarded-For {remote_host}
		header_up X-Forwarded-Proto {scheme}
	}
}
EOF
else
  echo "==> Caddy HTTP on :80 (no FREQUENCY_DOMAIN)"
  cp -f deploy/Caddyfile.http deploy/Caddyfile 2>/dev/null || true
  if [[ ! -f deploy/Caddyfile ]] || ! grep -q '^:80' deploy/Caddyfile; then
    cat > deploy/Caddyfile <<EOF
{
	email ${ACME_EMAIL}
}

:80 {
	encode gzip zstd
	header {
		X-Content-Type-Options nosniff
		Referrer-Policy strict-origin-when-cross-origin
		-Server
	}
	reverse_proxy agent:8501 {
		flush_interval -1
		header_up Host {host}
		header_up X-Real-IP {remote_host}
		header_up X-Forwarded-For {remote_host}
		header_up X-Forwarded-Proto {scheme}
	}
}
EOF
  fi
fi

# Normalize line endings if synced from Windows
sed -i 's/\r$//' deploy/Caddyfile scripts/*.sh 2>/dev/null || true

echo "==> Building & starting production stack"
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build --remove-orphans

echo "==> Status"
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
echo
echo "Health (via Caddy):"
sleep 2
curl -fsS -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1/_stcore/health || \
  curl -fsS -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1/ || true
if [[ -n "$DOMAIN" ]]; then
  echo "Domain HTTPS (may fail until DNS A -> this server):"
  curl -fsSk -o /dev/null -w "HTTPS %{http_code}\n" "https://${DOMAIN}/_stcore/health" || true
fi
echo "Done."
