# Deploy Frequency Lead Agent to Contabo (or any VPS) from Windows.
# Examples:
#   .\scripts\deploy.ps1
#   .\scripts\deploy.ps1 -Bootstrap
#   .\scripts\deploy.ps1 -Domain app.frequency.cx
[CmdletBinding()]
param(
    [string]$HostName = "178.212.35.46",
    [string]$User = "root",
    [string]$RemoteDir = "/opt/frequency-lead-agent",
    [switch]$Bootstrap,
    [switch]$SkipEnv,
    [switch]$Sidecar,
    [string]$Domain = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot

$sshTarget = "${User}@${HostName}"
$sshOpts = @("-o", "StrictHostKeyChecking=accept-new")

function Invoke-Remote {
    param([Parameter(Mandatory = $true)][string]$Command)
    & ssh @sshOpts $sshTarget $Command
    if ($LASTEXITCODE -ne 0) {
        throw ("Remote command failed: " + $Command)
    }
}

Write-Host ("==> Checking SSH to " + $sshTarget + " ...") -ForegroundColor Cyan
& ssh @sshOpts $sshTarget "echo ok"
if ($LASTEXITCODE -ne 0) {
    Write-Host "SSH failed. Fix access first, then re-run." -ForegroundColor Yellow
    Write-Host "  See DEPLOY.md for SSH key install steps."
    Write-Host "  Then: .\scripts\deploy.ps1 -Bootstrap"
    exit 1
}

if ($Bootstrap) {
    Write-Host "==> Bootstrapping server (Docker + firewall) ..." -ForegroundColor Cyan
    $bootPath = Join-Path $PSScriptRoot "bootstrap-server.sh"
    # Strip Windows CRLF so bash on Linux does not see $'\r'
    $boot = (Get-Content -Raw $bootPath) -replace "`r`n", "`n" -replace "`r", "`n"
    $boot | & ssh @sshOpts $sshTarget "bash -s"
    if ($LASTEXITCODE -ne 0) {
        throw "Bootstrap failed"
    }
}

Write-Host "==> Packing project ..." -ForegroundColor Cyan
$stamp = Get-Date -Format "yyyyMMddHHmmss"
$archive = Join-Path $env:TEMP ("frequency-agent-deploy-" + $stamp + ".tgz")

& tar -czf $archive --exclude=.git --exclude=.venv --exclude=venv --exclude=__pycache__ --exclude=.pytest_cache --exclude=.env --exclude=.env.local --exclude=var --exclude=output --exclude=.cursor -C $ProjectRoot .
if ($LASTEXITCODE -ne 0) {
    throw "tar failed"
}

try {
    Write-Host ("==> Uploading to " + $sshTarget + ":" + $RemoteDir + " ...") -ForegroundColor Cyan
    Invoke-Remote ("mkdir -p " + $RemoteDir)
    & scp @sshOpts $archive ($sshTarget + ":/tmp/frequency-agent-deploy.tgz")
    if ($LASTEXITCODE -ne 0) {
        throw "scp archive failed"
    }
    $extractCmd = 'tar -xzf /tmp/frequency-agent-deploy.tgz -C ' + $RemoteDir + '; rm -f /tmp/frequency-agent-deploy.tgz; sed -i "s/\r$//" ' + $RemoteDir + '/scripts/*.sh; chmod +x ' + $RemoteDir + '/scripts/*.sh'
    Invoke-Remote $extractCmd
}
finally {
    Remove-Item -Force $archive -ErrorAction SilentlyContinue
}

if (-not $SkipEnv) {
    $envPath = Join-Path $ProjectRoot ".env"
    if (Test-Path $envPath) {
        Write-Host "==> Uploading .env (secrets stay off git) ..." -ForegroundColor Cyan
        & scp @sshOpts $envPath ($sshTarget + ":" + $RemoteDir + "/.env")
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to upload .env"
        }
    }
    else {
        Write-Host ("WARNING: no local .env - server must already have " + $RemoteDir + "/.env") -ForegroundColor Yellow
    }
}

if ($Domain -and -not $Sidecar) {
    Write-Host ("==> Setting FREQUENCY_DOMAIN=" + $Domain) -ForegroundColor Cyan
    $qDomain = ($Domain -replace "[^A-Za-z0-9._-]", "")
    $py = @'
import pathlib,re,sys
p=pathlib.Path(".env")
text=p.read_text(encoding="utf-8") if p.exists() else ""
dom=sys.argv[1]
line="FREQUENCY_DOMAIN="+dom
if re.search(r"(?m)^FREQUENCY_DOMAIN=.*$", text):
    text=re.sub(r"(?m)^FREQUENCY_DOMAIN=.*$", line, text)
else:
    if text and not text.endswith("\n"):
        text+="\n"
    text+=line+"\n"
p.write_text(text, encoding="utf-8")
'@
    $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($py))
    $setDomain = "cd " + $RemoteDir + "; echo " + $b64 + " | base64 -d > /tmp/set_domain.py; python3 /tmp/set_domain.py " + $qDomain
    Invoke-Remote $setDomain
}

Write-Host "==> Remote rebuild ..." -ForegroundColor Cyan
$upScript = if ($Sidecar) { "remote-up-sidecar.sh" } else { "remote-up.sh" }
Invoke-Remote ('sed -i "s/\r$//" ' + $RemoteDir + '/scripts/*.sh; chmod +x ' + $RemoteDir + '/scripts/*.sh; bash ' + $RemoteDir + '/scripts/' + $upScript)

Write-Host ""
Write-Host "Deployed." -ForegroundColor Green
Write-Host ("  Open:  http://" + $HostName + "/")
if ($Domain) {
    Write-Host ("  HTTPS: https://" + $Domain + "/   (DNS A record must point here)")
}
Write-Host "  Updates: .\scripts\deploy.ps1"
