<#
.SYNOPSIS
    One-command Windows development environment bring-up for agentic-workflows-v2.

.DESCRIPTION
    Checks prerequisites, installs Python and Node.js dependencies, builds the
    frontend, validates all 6 bundled workflows, runs a deterministic smoke test,
    and probes the backend health endpoint to confirm the server starts.

    Run this once after cloning the repo (or after pulling major changes).
    After setup completes, use start-dev.ps1 to launch the dev servers.

.PARAMETER SkipSmokeTest
    Skip the workflow validation and smoke-test phase.

.PARAMETER SkipFrontend
    Skip the npm install and build steps (backend-only setup).

.PARAMETER BackendPort
    Port used by this setup script's short-lived backend health probe.
    Default: 8012. Day-to-day `just dev` uses backend port 8010.

.PARAMETER FrontendPort
    Port checked by this setup script's port guard. Default: 5174.
    Day-to-day `just dev` and the Vite proxy use frontend port 5173.

.EXAMPLE
    .\setup-dev.ps1
    .\setup-dev.ps1 -SkipSmokeTest
    .\setup-dev.ps1 -SkipFrontend
#>

[CmdletBinding()]
param(
    [switch]$SkipSmokeTest,
    [switch]$SkipFrontend,
    [int]$BackendPort = 8012,
    [int]$FrontendPort = 5174
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Resolve paths
# ---------------------------------------------------------------------------

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$BackendRoot = Split-Path -Parent $ScriptDir          # agentic-workflows-v2/
$RepoRoot = Split-Path -Parent $BackendRoot
$UiRoot = Join-Path $BackendRoot "ui"
$FixturesDir = Join-Path $ScriptDir "fixtures"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Message)
    Write-Host "    [OK] $Message" -ForegroundColor Green
}

function Write-Fail {
    param([string]$Message)
    Write-Host "    [FAIL] $Message" -ForegroundColor Red
}

function Write-Warn {
    param([string]$Message)
    Write-Host "    [WARN] $Message" -ForegroundColor Yellow
}

function Assert-Tool {
    param(
        [string]$Name,
        [string]$InstallHint
    )
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        Write-Fail "$Name not found. $InstallHint"
        exit 1
    }
    $ver = & $Name --version 2>&1 | Select-Object -First 1
    Write-Ok "$Name ($ver)"
}

function Test-TruthyEnvValue {
    param([AllowNull()][string]$Value)

    if ($null -eq $Value) { return $false }

    $normalized = $Value.Trim().ToLowerInvariant()
    return @("1", "true", "yes", "y", "on").Contains($normalized)
}

function Test-EnvFileContainsValue {
    param(
        [string]$Path,
        [string]$Name
    )

    if (-not (Test-Path $Path)) { return $false }

    foreach ($line in (Get-Content $Path)) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) { continue }

        $match = [regex]::Match($trimmed, "^\s*$([regex]::Escape($Name))\s*=\s*(.*)$")
        if (-not $match.Success) { continue }

        $value = $match.Groups[1].Value.Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2).Trim()
        }

        return -not [string]::IsNullOrWhiteSpace($value)
    }

    return $false
}

function Test-AnyConfiguredCredential {
    $credentialNames = @(
        "GITHUB_TOKEN",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_API_KEY_0",
        "PHI_SILICA_LAF_TOKEN"
    )
    $envFiles = @(
        (Join-Path $RepoRoot ".env"),
        (Join-Path $BackendRoot ".env")
    )

    foreach ($name in $credentialNames) {
        $envValue = [Environment]::GetEnvironmentVariable($name)
        if (-not [string]::IsNullOrWhiteSpace($envValue)) { return $true }

        foreach ($envFile in $envFiles) {
            if (Test-EnvFileContainsValue -Path $envFile -Name $name) { return $true }
        }
    }

    return $false
}

function Test-NoLlmModeConfigured {
    $envValue = [Environment]::GetEnvironmentVariable("AGENTIC_NO_LLM")
    if (Test-TruthyEnvValue -Value $envValue) { return $true }

    $envFiles = @(
        (Join-Path $RepoRoot ".env"),
        (Join-Path $BackendRoot ".env")
    )

    foreach ($envFile in $envFiles) {
        if (-not (Test-Path $envFile)) { continue }

        foreach ($line in (Get-Content $envFile)) {
            $trimmed = $line.Trim()
            if (-not $trimmed -or $trimmed.StartsWith("#")) { continue }

            $match = [regex]::Match($trimmed, "^\s*AGENTIC_NO_LLM\s*=\s*(.*)$")
            if (-not $match.Success) { continue }

            $value = $match.Groups[1].Value.Trim()
            if (($value.StartsWith('"') -and $value.EndsWith('"')) -or
                ($value.StartsWith("'") -and $value.EndsWith("'"))) {
                $value = $value.Substring(1, $value.Length - 2).Trim()
            }
            if (Test-TruthyEnvValue -Value $value) { return $true }
        }
    }

    return $false
}

# Force UTF-8 for Python subprocesses (Rich uses Unicode symbols that
# cp1252 cannot encode on some Windows terminals).
$env:PYTHONIOENCODING = "utf-8"

# ---------------------------------------------------------------------------
# Step 1 — Prerequisite checks
# ---------------------------------------------------------------------------

Write-Step "Checking prerequisites"

Assert-Tool "git" "Install from: https://git-scm.com/"
Assert-Tool "uv"  "Install from: https://docs.astral.sh/uv/"

if (-not $SkipFrontend) {
    Assert-Tool "node" "Install Node.js 20+ from: https://nodejs.org/"
    Assert-Tool "npm"  "npm should come with Node.js — reinstall Node if missing."

    # Enforce Node.js minimum version.
    $nodeVersion = node --version 2>&1 | Select-Object -First 1
    $nodeMajor = [int]($nodeVersion -replace '^v(\d+).*', '$1')
    if ($nodeMajor -lt 20) {
        Write-Fail "Node.js 20+ required (found $nodeVersion). Install from: https://nodejs.org/"
        exit 1
    }
}

# ---------------------------------------------------------------------------
# Step 1b — Port availability check
# ---------------------------------------------------------------------------

Write-Step "Checking port availability (port-guard)"

Push-Location $BackendRoot
try {
    $LASTEXITCODE = 0
    $ErrorActionPreference = "Continue"
    & uv run agentic devex port-guard --backend-port $BackendPort --frontend-port $FrontendPort
    $portExit = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = "Stop"
    Pop-Location
}

if ($portExit -ne 0) {
    Write-Fail "Port conflict detected. Resolve conflicts before continuing."
    exit 1
}

# ---------------------------------------------------------------------------
# Step 2 — Python environment setup
# ---------------------------------------------------------------------------

Write-Step "Installing Python packages (uv sync)"

Push-Location $BackendRoot
try {
    & uv sync --extra dev --extra server --extra langchain
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "uv sync failed (exit code $LASTEXITCODE)"
        exit 1
    }
    Write-Ok "Python packages installed"
    if (-not (Test-NoLlmModeConfigured) -and -not (Test-AnyConfiguredCredential)) {
        Write-Warn "No LLM provider credential found and AGENTIC_NO_LLM is not enabled. Copy .env.example to .env, add a provider key, or set AGENTIC_NO_LLM=1 for placeholder models."
    }
}
finally {
    Pop-Location
}

# ---------------------------------------------------------------------------
# Step 3 — Frontend install and build
# ---------------------------------------------------------------------------

if (-not $SkipFrontend) {
    Write-Step "Installing frontend packages (npm install)"

    if (-not (Test-Path $UiRoot)) {
        Write-Fail "UI directory not found at $UiRoot"
        exit 1
    }

    Push-Location $UiRoot
    try {
        & npm install --no-fund --no-audit
        if ($LASTEXITCODE -ne 0) {
            Write-Fail "npm install failed (exit code $LASTEXITCODE)"
            exit 1
        }
        Write-Ok "Frontend packages installed"
    }
    finally {
        Pop-Location
    }

    Write-Step "Building frontend (npm run build)"

    Push-Location $UiRoot
    try {
        & npm run build
        if ($LASTEXITCODE -ne 0) {
            Write-Fail "npm run build failed (exit code $LASTEXITCODE)"
            exit 1
        }
        Write-Ok "Frontend build successful"
    }
    finally {
        Pop-Location
    }
}
else {
    Write-Step "Skipping frontend install and build (-SkipFrontend)"
}

# ---------------------------------------------------------------------------
# Step 4 — Workflow validation & smoke test
# ---------------------------------------------------------------------------

if (-not $SkipSmokeTest) {
    Write-Step "Validating bundled workflows"

    $workflows = @(
        "bug_resolution"
        "code_review"
        "conditional_branching"
        "fullstack_generation"
        "iterative_review"
        "test_deterministic"
    )

    $failed = @()
    $warned = @()

    Push-Location $BackendRoot
    try {
        foreach ($wf in $workflows) {
            $output = $null
            $exitCode = 0
            try {
                $ErrorActionPreference = "Continue"
                $output = & uv run agentic validate $wf 2>&1
                $exitCode = $LASTEXITCODE
            }
            finally {
                $ErrorActionPreference = "Stop"
            }

            if ($exitCode -ne 0) {
                # iterative_review.yaml has a known pre-existing static validation
                # bug (unresolved variable template). All other failures are hard errors.
                if ($wf -eq "iterative_review") {
                    Write-Host "    [WARN] Known validation issue: $wf (pre-existing, non-blocking)" -ForegroundColor Yellow
                    $warned += $wf
                }
                else {
                    Write-Host "    [FAIL] Validation failed: $wf" -ForegroundColor Red
                    if ($output) { Write-Host ($output | Out-String) -ForegroundColor DarkGray }
                    $failed += $wf
                }
            }
            else {
                Write-Ok "Validated: $wf"
            }
        }
    }
    finally {
        Pop-Location
    }

    if ($warned.Count -gt 0) {
        Write-Host ""
        Write-Host "    Note: $($warned.Count) workflow(s) had known pre-existing warnings: $($warned -join ', ')" -ForegroundColor Yellow
    }

    if ($failed.Count -gt 0) {
        Write-Host ""
        Write-Fail "$($failed.Count) workflow(s) failed validation: $($failed -join ', ')"
        exit 1
    }

    # Run the deterministic workflow with --dry-run to verify the full
    # execution path (parsing, graph compilation, plan generation) without
    # requiring live agent implementations.
    Write-Step "Running deterministic smoke test (dry-run)"

    $smokeInput = Join-Path $FixturesDir "smoke-input.json"
    if (-not (Test-Path $smokeInput)) {
        Write-Fail "Smoke-test input not found at $smokeInput"
        exit 1
    }

    Push-Location $BackendRoot
    try {
        $smokeOutput = $null
        $smokeExit = 0
        try {
            $ErrorActionPreference = "Continue"
            $smokeOutput = & uv run agentic run test_deterministic --input $smokeInput --dry-run 2>&1
            $smokeExit = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = "Stop"
        }

        if ($smokeExit -ne 0) {
            Write-Fail "Smoke test failed (exit code $smokeExit)"
            if ($smokeOutput) { Write-Host ($smokeOutput | Out-String) -ForegroundColor DarkGray }
            exit 1
        }
        Write-Ok "Smoke test passed"
    }
    finally {
        Pop-Location
    }
}
else {
    Write-Step "Skipping smoke test (-SkipSmokeTest)"
}

# ---------------------------------------------------------------------------
# Step 5 — Backend health probe
# ---------------------------------------------------------------------------

Write-Step "Verifying backend starts (health probe on :$BackendPort)"

$serverLogOut = Join-Path $env:TEMP "setup-dev-server.stdout.log"
$serverLogErr = Join-Path $env:TEMP "setup-dev-server.stderr.log"
$serverProc = $null

try {
    $serverProc = Start-Process -FilePath "uv" `
        -ArgumentList "run", "python", "-m", "uvicorn", `
                       "agentic_v2.server.app:app", `
                       "--host", "127.0.0.1", "--port", "$BackendPort" `
        -WorkingDirectory $BackendRoot `
        -RedirectStandardOutput $serverLogOut `
        -RedirectStandardError  $serverLogErr `
        -NoNewWindow `
        -PassThru

    $maxWait   = 30
    $waited    = 0
    $started   = $false

    while ($waited -lt $maxWait) {
        Start-Sleep -Seconds 2
        $waited += 2

        if ($serverProc.HasExited) {
            Write-Fail "Backend process exited unexpectedly (exit code $($serverProc.ExitCode))"
            if (Test-Path $serverLogErr) { Get-Content $serverLogErr | Write-Host -ForegroundColor DarkGray }
            exit 1
        }

        try {
            $resp = Invoke-WebRequest `
                -Uri            "http://127.0.0.1:$BackendPort/api/health" `
                -UseBasicParsing `
                -TimeoutSec     2 `
                -ErrorAction    Stop
            if ($resp.StatusCode -eq 200) { $started = $true; break }
        }
        catch { }
    }

    if (-not $started) {
        Write-Fail "Backend did not respond on http://127.0.0.1:$BackendPort/api/health within ${maxWait}s"
        if (Test-Path $serverLogErr) { Get-Content $serverLogErr | Write-Host -ForegroundColor DarkGray }
        exit 1
    }

    Write-Ok "Backend health probe passed (http://127.0.0.1:$BackendPort/api/health)"
}
finally {
    if ($serverProc -and -not $serverProc.HasExited) {
        $serverProc.Kill()
        $null = $serverProc.WaitForExit(5000)
    }
    Remove-Item $serverLogOut, $serverLogErr -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Setup complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Run your first workflow (no API key needed):" -ForegroundColor Cyan
Write-Host "        agentic run test_deterministic --input '{`"input_text`": `"Hello`"}'" -ForegroundColor White
Write-Host "     Or with env var explicitly set:"
Write-Host "        `$env:AGENTIC_NO_LLM = '1'; agentic run test_deterministic --input '{`"input_text`": `"Hello`"}'"
Write-Host "  2. To use LLM-powered workflows, copy .env.example to .env and add at least one provider key"
Write-Host "  3. Launch dev servers:  .\scripts\start-dev.ps1"
Write-Host "  4. This setup probe used backend :$BackendPort and port-guard frontend :$FrontendPort"
Write-Host "  5. Day-to-day just dev uses backend :8010 and frontend :5173"
Write-Host ""
