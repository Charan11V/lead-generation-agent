# Migrate local SQLite workspace DB to Contabo production volume.
# Usage: .\scripts\migrate-db-to-prod.ps1
[CmdletBinding()]
param(
    [string]$HostName = "178.212.35.46",
    [string]$User = "root",
    [string]$RemoteDir = "/opt/frequency-lead-agent",
    [string]$LocalDb = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot

if (-not $LocalDb) {
    $candidate = Join-Path $ProjectRoot "var\frequency_agent.db"
    if (-not (Test-Path $candidate)) {
        $candidate = Join-Path $ProjectRoot "frequency_agent.db"
    }
    $LocalDb = $candidate
}
if (-not (Test-Path $LocalDb)) {
    throw "Local DB not found: $LocalDb"
}

$sshTarget = $User + "@" + $HostName
$sshOpts = @("-o", "StrictHostKeyChecking=accept-new")
$dbName = "frequency_agent.db"
$remoteTmp = "/tmp/" + $dbName

Write-Host ("==> Local DB: " + $LocalDb) -ForegroundColor Cyan
Write-Host ("==> Size: " + (Get-Item $LocalDb).Length + " bytes")

Write-Host "==> Stopping production containers (brief) ..." -ForegroundColor Cyan
& ssh @sshOpts $sshTarget ("cd " + $RemoteDir + "; docker compose -f docker-compose.yml -f docker-compose.prod.yml stop agent caddy")
if ($LASTEXITCODE -ne 0) { throw "Failed to stop containers" }

Write-Host "==> Uploading database ..." -ForegroundColor Cyan
& scp @sshOpts $LocalDb ($sshTarget + ":" + $remoteTmp)
if ($LASTEXITCODE -ne 0) { throw "scp DB failed" }

Write-Host "==> Installing into Docker volume agent-var ..." -ForegroundColor Cyan
$install = @'
set -e
REMOTE_TMP=/tmp/frequency_agent.db
# Clear any prior FREQUENCY_SECRETS_KEY so Fernet matches local (CLERK fallback)
if [ -f /opt/frequency-lead-agent/.env ]; then
  sed -i '/^FREQUENCY_SECRETS_KEY=/d' /opt/frequency-lead-agent/.env
fi
docker run --rm \
  -v frequency-lead-agent_agent-var:/data \
  -v /tmp:/tmp:ro \
  alpine:3.20 \
  sh -c "mkdir -p /data && cp /tmp/frequency_agent.db /data/frequency_agent.db && chmod 664 /data/frequency_agent.db && chown 1000:1000 /data/frequency_agent.db && ls -la /data/frequency_agent.db"
rm -f /tmp/frequency_agent.db
'@
$install = $install -replace "`r`n", "`n"
$install | & ssh @sshOpts $sshTarget "bash -s"
if ($LASTEXITCODE -ne 0) { throw "Volume install failed" }

Write-Host "==> Restarting stack ..." -ForegroundColor Cyan
& ssh @sshOpts $sshTarget ("cd " + $RemoteDir + "; sed -i 's/\r$//' scripts/remote-up.sh; bash scripts/remote-up.sh")
if ($LASTEXITCODE -ne 0) { throw "Restart failed" }

Write-Host "==> Verifying row counts on server ..." -ForegroundColor Cyan
& ssh @sshOpts $sshTarget 'docker run --rm -v frequency-lead-agent_agent-var:/data python:3.11-slim-bookworm python -c "import sqlite3; c=sqlite3.connect(\"/data/frequency_agent.db\");
tables=[\"user_profiles\",\"user_api_keys\",\"query_sessions\",\"runs\",\"leads\",\"query_leads\",\"send_queue\"];
[print(t+\": \"+str(c.execute(\"select count(*) from \"+t).fetchone()[0])) for t in tables]"'

Write-Host ""
Write-Host "Migration complete." -ForegroundColor Green
Write-Host "Open https://agent-internal.frequency.cx/ and sign in - local searches/leads should be there."
