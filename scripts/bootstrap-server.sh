#!/usr/bin/env bash
# First-time Contabo / VPS bootstrap (run as root on the server).
# Usage: bash bootstrap-server.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/frequency-lead-agent}"

echo "==> Installing Docker if needed"
if ! command -v docker >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y ca-certificates curl gnupg
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi

echo "==> Docker: $(docker --version)"
docker compose version

echo "==> Firewall (UFW): SSH + HTTP/HTTPS only"
if command -v ufw >/dev/null 2>&1; then
  ufw allow OpenSSH
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw --force enable || true
  ufw status || true
else
  apt-get update -y && apt-get install -y ufw
  ufw allow OpenSSH
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw --force enable
fi

mkdir -p "$APP_DIR"
echo "==> App directory: $APP_DIR"
echo "Bootstrap complete. Deploy code with scripts/deploy.ps1 from your laptop."
