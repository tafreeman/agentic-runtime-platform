[CmdletBinding()]
param(
    [switch]$Reload,
    [string]$BackendHost = '127.0.0.1',
    [int]$BackendPort = 8012,
    [string]$FrontendHost = '127.0.0.1',
    [int]$FrontendPort = 5174,
    [string]$ApiProxyTarget = 'http://127.0.0.1:8012',
    [switch]$AutoTierFromProbe
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent $projectRoot
$uiRoot = Join-Path $projectRoot 'ui'
$logsDir = Join-Path $projectRoot '.run-logs'
New-Item -ItemType Directory -Path $logsDir -Force | Out-Null

$backendOutLog = Join-Path $logsDir 'backend.out.log'
$backendErrLog = Join-Path $logsDir 'backend.err.log'
$frontendOutLog = Join-Path $logsDir 'frontend.out.log'
$frontendErrLog = Join-Path $logsDir 'frontend.err.log'
$backendPidFile = Join-Path $logsDir 'backend.pid'
$frontendPidFile = Join-Path $logsDir 'frontend.pid'

$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    $python = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $python) {
    throw "Python was not found in .venv or on PATH"
}

$npmCmd = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
if (-not $npmCmd) {
    throw "npm.cmd was not found on PATH"
}
$npxCmd = (Get-Command npx.cmd -ErrorAction SilentlyContinue).Source

function Invoke-PythonStep {
    param(
        [string[]]$Args,
        [string]$StepName
    )

    & $python @Args
    $cmdSucceeded = $?
    $exitCode = if ($null -eq $LASTEXITCODE) {
        if ($cmdSucceeded) { 0 } else { 1 }
    } else {
        [int]$LASTEXITCODE
    }

    if (-not $cmdSucceeded -or $exitCode -ne 0) {
        throw "$StepName failed with exit code $exitCode"
    }
}

function Normalize-ModelId {
    param(
        [string]$ProviderName,
        [string]$ModelId
    )

    if (-not $ModelId) { return $null }
    $trimmed = $ModelId.Trim()
    if (-not $trimmed) { return $null }

    if ($trimmed -match '^[a-zA-Z0-9_-]+:') {
        return $trimmed
    }

    switch ($ProviderName) {
        'openai' { return "openai:$trimmed" }
        'github_models' { return "gh:$trimmed" }
        'anthropic' { return "claude:$trimmed" }
        'ollama' { return "ollama:$trimmed" }
        'local_onnx' { return "local:$trimmed" }
        'ai_toolkit' { return "aitk:$trimmed" }
        'lmstudio' { return "lmstudio:$trimmed" }
        default { return $trimmed }
    }
}

function Select-PreferredModel {
    param(
        [string[]]$Models,
        [string[]]$PreferTokens,
        [string[]]$DenyTokens
    )

    foreach ($model in $Models) {
        $lower = $model.ToLowerInvariant()
        $isDenied = $false
        foreach ($deny in $DenyTokens) {
            if ($lower.Contains($deny.ToLowerInvariant())) {
                $isDenied = $true
                break
            }
        }
        if ($isDenied) { continue }

        foreach ($token in $PreferTokens) {
            if ($lower.Contains($token.ToLowerInvariant())) {
                return $model
            }
        }
    }
    return $null
}

if ($AutoTierFromProbe) {
    Write-Host "Building dynamic tier routing from model probe + ranking..." -ForegroundColor Cyan

    $probeScript = Join-Path $repoRoot 'tools\llm\model_probe.py'
    $limitsScript = Join-Path $repoRoot 'tools\llm\check_provider_limits.py'
    $rankScript = Join-Path $repoRoot 'tools\llm\rank_models.py'
    $probeOutput = Join-Path $repoRoot 'tools\llm\filename.json'
    $limitsOutput = Join-Path $logsDir 'provider_limits.json'
    $rankingOutput = Join-Path $logsDir 'model_ranking.json'

    New-Item -ItemType Directory -Path (Split-Path $limitsOutput -Parent) -Force | Out-Null

    Push-Location $repoRoot
    try {
        Invoke-PythonStep -Args @($probeScript, '--discover', '--output', $probeOutput) -StepName 'model_probe discovery'

        & $python $limitsScript --probe-file $probeOutput --out $limitsOutput
        $limitsSucceeded = $?
        $limitsExitCode = if ($null -eq $LASTEXITCODE) {
            if ($limitsSucceeded) { 0 } else { 1 }
        } else {
            [int]$LASTEXITCODE
        }
        if (-not $limitsSucceeded -or $limitsExitCode -ne 0) {
            Write-Warning "Provider limits check failed; continuing with probe discovery only."
        }

        Invoke-PythonStep -Args @(
            $rankScript,
            '--probe-file', $probeOutput,
            '--limits-file', $limitsOutput,
            '--out', $rankingOutput
        ) -StepName 'rank_models'
    } catch {
        Write-Warning "Dynamic tier routing refresh failed: $($_.Exception.Message)"
    } finally {
        Pop-Location
    }

    if (Test-Path $rankingOutput) {
        try {
            $ranking = Get-Content $rankingOutput -Raw | ConvertFrom-Json
            $providerEntries = @()
            if ($ranking -and $ranking.providers) {
                foreach ($providerProp in $ranking.providers.PSObject.Properties) {
                    $providerName = $providerProp.Name
                    $providerInfo = $providerProp.Value
                    $rankValue = 999.0
                    if ($providerInfo.PSObject.Properties.Name -contains 'rank') {
                        [void][double]::TryParse("$($providerInfo.rank)", [ref]$rankValue)
                    }
                    $providerModels = @()
                    if ($providerInfo.PSObject.Properties.Name -contains 'models') {
                        $providerModels = @($providerInfo.models)
                    }
                    $providerEntries += [pscustomobject]@{
                        Name = $providerName
                        Rank = $rankValue
                        Models = $providerModels
                    }
                }
            }

            $orderedModels = @()
            $seen = @{}
            foreach ($entry in ($providerEntries | Sort-Object Rank)) {
                foreach ($rawModel in $entry.Models) {
                    $normalized = Normalize-ModelId -ProviderName $entry.Name -ModelId "$rawModel"
                    if ($normalized -and -not $seen.ContainsKey($normalized)) {
                        $seen[$normalized] = $true
                        $orderedModels += $normalized
                    }
                }
            }

            if ($orderedModels.Count -gt 0) {
                $denyTokens = @('embedding', 'embed', 'vision', 'image', 'audio', 'tts')
                $fallbackModels = @(
                    $orderedModels | Where-Object {
                        $lower = $_.ToLowerInvariant()
                        -not ($denyTokens | Where-Object { $lower.Contains($_) })
                    }
                )
                if ($fallbackModels.Count -eq 0) { $fallbackModels = $orderedModels }

                $tierModels = @{}
                $tierModels[1] = Select-PreferredModel -Models $orderedModels -PreferTokens @('mini', 'lite', 'haiku', 'flash') -DenyTokens $denyTokens
                $tierModels[2] = Select-PreferredModel -Models $orderedModels -PreferTokens @('gpt-4o', 'sonnet', 'deepseek-r1', 'phi4', 'qwen', 'flash') -DenyTokens $denyTokens
                $tierModels[3] = Select-PreferredModel -Models $orderedModels -PreferTokens @('sonnet', 'gpt-4o', 'deepseek-r1', 'qwen3-coder', 'phi4-reasoning', 'gemini-2.5-flash') -DenyTokens $denyTokens
                $tierModels[4] = Select-PreferredModel -Models $orderedModels -PreferTokens @('opus', 'o3', 'deepseek-r1', 'sonnet', 'gpt-4o', 'gemini-2.5-pro', 'gemini-2.5-flash') -DenyTokens $denyTokens
                $tierModels[5] = Select-PreferredModel -Models $orderedModels -PreferTokens @('opus', 'o3', 'deepseek-r1', 'sonnet', 'gpt-4o', 'gemini-2.5-pro') -DenyTokens $denyTokens

                foreach ($tier in 1..5) {
                    if (-not $tierModels[$tier]) {
                        $idx = [Math]::Min([Math]::Max($tier - 1, 0), $fallbackModels.Count - 1)
                        $tierModels[$tier] = $fallbackModels[$idx]
                    }
                    $envName = "AGENTIC_MODEL_TIER_$tier"
                    Set-Item -Path "Env:$envName" -Value $tierModels[$tier]
                }

                Set-Item -Path 'Env:AGENTIC_MODEL_SOURCE' -Value 'ranking'
                Set-Item -Path 'Env:AGENTIC_MODEL_RANKING_FILE' -Value $rankingOutput
                Write-Host "Dynamic tier routing applied from $rankingOutput" -ForegroundColor Green
                foreach ($tier in 1..5) {
                    $resolved = (Get-Item -Path "Env:AGENTIC_MODEL_TIER_$tier").Value
                    Write-Host ("  AGENTIC_MODEL_TIER_{0}={1}" -f $tier, $resolved)
                }
            } else {
                Write-Warning "No ranked models found in $rankingOutput; keeping existing tier env values."
            }
        } catch {
            Write-Warning "Failed to parse/apply model ranking: $($_.Exception.Message)"
        }
    } else {
        Write-Warning "Ranking output not found at $rankingOutput; keeping existing tier env values."
    }
}

Write-Host "Starting backend..." -ForegroundColor Cyan
$backendArgs = @('-m','uvicorn','agentic_v2.server.app:app','--host',$BackendHost,'--port',"$BackendPort",'--app-dir','.')
if ($Reload) { $backendArgs += '--reload' }

$backendProc = Start-Process -FilePath $python -ArgumentList $backendArgs -WorkingDirectory $projectRoot -PassThru -RedirectStandardOutput $backendOutLog -RedirectStandardError $backendErrLog
Set-Content -Path $backendPidFile -Value $backendProc.Id

Write-Host "Starting frontend..." -ForegroundColor Cyan
$env:VITE_API_PROXY_TARGET = $ApiProxyTarget
$frontendProc = Start-Process -FilePath $npmCmd -ArgumentList @('run','dev','--','--host',$FrontendHost,'--port',"$FrontendPort") -WorkingDirectory $uiRoot -PassThru -RedirectStandardOutput $frontendOutLog -RedirectStandardError $frontendErrLog
Set-Content -Path $frontendPidFile -Value $frontendProc.Id

Start-Sleep -Seconds 2

if ($frontendProc.HasExited) {
    $frontendErrText = ""
    if (Test-Path $frontendErrLog) {
        $frontendErrText = Get-Content $frontendErrLog -Raw
    }

    if (($frontendErrText -match "vite' is not recognized") -and $npxCmd) {
        Write-Warning "npm run dev could not resolve vite; retrying with npx vite."
        $frontendProc = Start-Process -FilePath $npxCmd -ArgumentList @('vite','--host',$FrontendHost,'--port',"$FrontendPort") -WorkingDirectory $uiRoot -PassThru -RedirectStandardOutput $frontendOutLog -RedirectStandardError $frontendErrLog
        Set-Content -Path $frontendPidFile -Value $frontendProc.Id
        Start-Sleep -Seconds 2
    }
}

try {
    $health = Invoke-RestMethod -Uri "http://$BackendHost`:$BackendPort/api/health" -TimeoutSec 5
    Write-Host "Backend health: $($health.status)" -ForegroundColor Green
} catch {
    Write-Warning "Backend health check failed. See $backendErrLog"
}

try {
    $resp = Invoke-WebRequest -UseBasicParsing -Uri "http://$FrontendHost`:$FrontendPort" -TimeoutSec 5
    Write-Host "Frontend HTTP: $($resp.StatusCode)" -ForegroundColor Green
} catch {
    Write-Warning "Frontend check failed. See $frontendErrLog"
}

Write-Host "Started." -ForegroundColor Green
Write-Host "Backend:  http://$BackendHost`:$BackendPort"
Write-Host "Frontend: http://$FrontendHost`:$FrontendPort"
Write-Host "Logs: $logsDir"
