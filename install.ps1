# Installs the agent long-term memory skill (Windows, PowerShell).
# Run:  powershell -ExecutionPolicy Bypass -File .\install.ps1

param(
    [ValidateSet('claude','amp','gemini','all')]
    [string]$Agent
)

$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Src  = Join-Path $Here 'skill'
$Name = 'ltm-vault'

# Without this, non-ASCII output in the Windows console is mangled.
try { chcp 65001 > $null } catch {}
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

# --- Python ------------------------------------------------------------------
$Py = $null
foreach ($c in @('python','python3','py')) {
    $cmd = Get-Command $c -ErrorAction SilentlyContinue
    if ($cmd) {
        try {
            & $c -c 'import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)' 2>$null
            if ($LASTEXITCODE -eq 0) { $Py = $c; break }
        } catch {}
    }
}
if (-not $Py) {
    Fail "Python 3.8 or newer is required.
  Install from https://www.python.org/downloads/
  or run: winget install Python.Python.3.12
  During setup make sure 'Add Python to PATH' is checked."
}

Write-Host "Python: $(& $Py --version 2>&1)"
if (-not (Test-Path $Src)) { Fail "skill\ directory not found next to this script" }

# --- install targets ---------------------------------------------------------
$Targets = @()
function Add-Target($label, $path) {
    $script:Targets += [pscustomobject]@{ Label = $label; Path = $path }
}

$ClaudeDir = Join-Path $env:USERPROFILE '.claude\skills'
$AmpDir    = Join-Path $env:APPDATA    'amp\skills'
$GeminiDir = Join-Path $env:USERPROFILE '.gemini\skills'

switch ($Agent) {
    'claude' { Add-Target 'Claude Code' $ClaudeDir }
    'amp'    { Add-Target 'AMP Code'    $AmpDir }
    'gemini' { Add-Target 'Gemini CLI'  $GeminiDir }
    'all'    {
        Add-Target 'Claude Code' $ClaudeDir
        Add-Target 'AMP Code'    $AmpDir
        Add-Target 'Gemini CLI'  $GeminiDir
    }
    default {
        if (Test-Path (Join-Path $env:USERPROFILE '.claude')) { Add-Target 'Claude Code' $ClaudeDir }
        if (Test-Path (Join-Path $env:APPDATA 'amp'))         { Add-Target 'AMP Code'    $AmpDir }
        if (Test-Path (Join-Path $env:USERPROFILE '.gemini')) { Add-Target 'Gemini CLI'  $GeminiDir }
    }
}

if ($Targets.Count -eq 0) {
    Write-Host "No installed agent found."
    Write-Host "Force install with: .\install.ps1 -Agent all"
    exit 1
}

# --- install -----------------------------------------------------------------
foreach ($t in $Targets) {
    $dest = Join-Path $t.Path $Name
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    Copy-Item -Path (Join-Path $Src '*') -Destination $dest -Recurse -Force
    Write-Host "installed: $($t.Label) -> $dest"
}

# --- verify ------------------------------------------------------------------
$first = Join-Path $Targets[0].Path $Name
$need = @('SKILL.md','scripts\ltm_detect.py','scripts\ltm_init.py','scripts\ltm_doctor.py')
$missing = $need | Where-Object { -not (Test-Path (Join-Path $first $_)) }
if ($missing) { Fail "missing files: $($missing -join ', ')" }
Write-Host "verify: all files present"

Write-Host ""
Write-Host "Done. Next:"
Write-Host "  1. Restart your agent so it picks up the new skill."
Write-Host "  2. Ask it: 'set up long-term memory'."
Write-Host "  3. Or run detection manually:"
Write-Host "     $Py `"$first\scripts\ltm_detect.py`""
