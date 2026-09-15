# Contabo / VPS production deploy

## What you get

- **agent** — Streamlit app in Docker (non-root, healthcheck, 6 GB mem limit, persistent SQLite + output volumes)
- **caddy** — reverse proxy on **:80 / :443** (Streamlit is **not** exposed on the public internet)
- One-command updates from your Windows machine after Cursor edits

Server: `178.212.35.46` (Contabo Cloud VPS 4)  
App path on server: `/opt/frequency-lead-agent`

---

## 1) One-time: SSH key (required)

Password SSH from this environment is blocked until a key is installed.

```powershell
# Create key if needed
ssh-keygen -t ed25519 -N '""' -f $env:USERPROFILE\.ssh\id_ed25519

# Install on Contabo (enter root password from Contabo / VNC once)
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh root@178.212.35.46 "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"

# Verify
ssh root@178.212.35.46 "echo ok"
```

---

## 2) One-time: bootstrap + first deploy

From the project folder:

```powershell
cd "C:\Users\Dell\Documents\frequency cx\frequency-lead-agent"
.\scripts\deploy.ps1 -Bootstrap
```

This will:

1. Install Docker + Compose on the VPS  
2. Open UFW for SSH / 80 / 443 only  
3. Sync this repo (except `.venv` / DB / `.git`)  
4. Upload your local `.env`  
5. Build & start **agent + Caddy**

Open: **http://178.212.35.46/**

---

## 3) Everyday updates (after Cursor changes)

```powershell
.\scripts\deploy.ps1
```

No need to commit first — deploy packs your working tree.

---

## 4) Optional HTTPS (domain)

1. DNS **A** record → `178.212.35.46`  
2. Deploy with domain:

```powershell
.\scripts\deploy.ps1 -Domain app.yourdomain.com
```

Caddy will issue a Let’s Encrypt certificate automatically.

---

## 5) Production notes

| Item | Detail |
|------|--------|
| Data | Docker volume `agent-var` → SQLite + encrypted user Tavily keys |
| Secrets | `.env` on server only (never git). Deploy auto-adds `FREQUENCY_SECRETS_KEY` / `AUTH_SESSION_SECRET` if missing |
| Local vs prod | Local: `docker compose up` (bind-mount). Prod: image build, no source mount |
| Logs | `ssh root@178.212.35.46 "cd /opt/frequency-lead-agent && docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f"` |
| Contabo backup | Keep Auto Backup on — covers the VM disk |

---

## Manual server commands

```bash
cd /opt/frequency-lead-agent
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f agent
bash scripts/remote-up.sh
```
