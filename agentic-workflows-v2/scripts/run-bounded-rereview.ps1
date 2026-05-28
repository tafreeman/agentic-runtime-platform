[CmdletBinding()]
param(
    [string]$ApiBase = 'http://127.0.0.1:8012',
    [string]$Workflow = 'fullstack_generation_bounded_rereview',
    [string]$FeatureSpec = 'Build an EventSphere app with intentional quality gaps so reviewer rework path is exercised.',
    # Preset shortcut: pass -Stack dotnet|node|python (overrides Frontend/Backend/Database defaults)
    [ValidateSet('', 'python', 'dotnet', 'node')]
    [string]$Stack = '',
    [string]$Frontend = '',
    [string]$Backend = '',
    [string]$Database = '',
    [int]$PollIntervalSeconds = 2,
    [int]$TimeoutSeconds = 600,
    [switch]$EnableEvaluation,
    [string]$DatasetSource = 'none',
    [string]$DatasetId,
    [int]$SampleIndex = 0
)

$ErrorActionPreference = 'Stop'

# Resolve stack preset → individual values (explicit params take precedence over preset)
$presets = @{
    python = @{ frontend = 'react';    backend = 'fastapi';     database = 'postgresql' }
    dotnet = @{ frontend = 'react';    backend = 'aspnetcore';  database = 'postgresql' }
    node   = @{ frontend = 'react';    backend = 'express';     database = 'postgresql' }
}
$resolvedPreset = if ($Stack -and $presets.ContainsKey($Stack)) { $presets[$Stack] } else { $presets['python'] }
if (-not $Frontend)  { $Frontend  = $resolvedPreset.frontend  }
if (-not $Backend)   { $Backend   = $resolvedPreset.backend   }
if (-not $Database)  { $Database  = $resolvedPreset.database  }

Write-Host "Stack: frontend=$Frontend  backend=$Backend  database=$Database" -ForegroundColor DarkCyan

$runId = "manual-$([DateTimeOffset]::UtcNow.ToString('yyyyMMddHHmmss'))-$([Guid]::NewGuid().ToString('N').Substring(0, 6))"

$payload = @{
    workflow   = $Workflow
    run_id     = $runId
    input_data = @{
        feature_spec = $FeatureSpec
        tech_stack   = @{
            frontend = $Frontend
            backend  = $Backend
            database = $Database
        }
    }
}

if ($EnableEvaluation) {
    $evaluation = @{
        enabled        = $true
        dataset_source = $DatasetSource
        sample_index   = $SampleIndex
    }
    if ($DatasetId) {
        $evaluation.dataset_id = $DatasetId
    }
    $payload.evaluation = $evaluation
}

Write-Host "Submitting run: $runId" -ForegroundColor Cyan
$response = Invoke-RestMethod -Method Post -Uri "$ApiBase/api/run" -ContentType 'application/json' -Body ($payload | ConvertTo-Json -Depth 20)
Write-Host "Accepted run_id: $($response.run_id), status: $($response.status)" -ForegroundColor Green

$start = Get-Date
$terminal = @('success', 'failed', 'error', 'cancelled')
$runSummary = $null

while ($true) {
    Start-Sleep -Seconds $PollIntervalSeconds

    $elapsed = (Get-Date) - $start
    if ($elapsed.TotalSeconds -ge $TimeoutSeconds) {
        throw "Timed out after $TimeoutSeconds seconds waiting for run completion"
    }

    $runs = Invoke-RestMethod -Method Get -Uri "$ApiBase/api/runs?limit=200"
    $runSummary = $runs | Where-Object { $_.run_id -eq $runId } | Select-Object -First 1

    if (-not $runSummary) {
        Write-Host "Waiting for run to appear in /api/runs... ($([int]$elapsed.TotalSeconds)s)"
        continue
    }

    $status = [string]$runSummary.status
    Write-Host "Status: $status ($([int]$elapsed.TotalSeconds)s)"

    if ($terminal -contains $status.ToLowerInvariant()) {
        break
    }
}

if (-not $runSummary.filename) {
    throw "Run completed but filename missing from summary response"
}

$detail = Invoke-RestMethod -Method Get -Uri "$ApiBase/api/runs/$($runSummary.filename)"

Write-Host "`nRun complete: $($runSummary.filename)" -ForegroundColor Green
Write-Host "Workflow: $($detail.workflow_name)"
Write-Host "Overall Status: $($detail.status)"
Write-Host "Success Rate: $($detail.success_rate)"
if ($detail.score -ne $null) {
    Write-Host "Score: $($detail.score)"
}

$stepRows = foreach ($step in $detail.steps) {
    [PSCustomObject]@{
        Step       = $step.step_name
        Status     = $step.status
        DurationMs = $step.duration_ms
        SkipReason = if ($step.metadata -and $step.metadata.skip_reason) { $step.metadata.skip_reason } else { '' }
    }
}

Write-Host "`nStep summary:" -ForegroundColor Cyan
$stepRows | Format-Table -AutoSize

$round1 = $stepRows | Where-Object { $_.Step -eq 'developer_rework_round1' } | Select-Object -First 1
$round2 = $stepRows | Where-Object { $_.Step -eq 'review_code_round2' } | Select-Object -First 1

if ($round1) {
    Write-Host "`nRework round 1: $($round1.Status)" -ForegroundColor Yellow
    if ($round1.SkipReason) {
        Write-Host "  reason: $($round1.SkipReason)"
    }
}
if ($round2) {
    Write-Host "Review round 2: $($round2.Status)" -ForegroundColor Yellow
    if ($round2.SkipReason) {
        Write-Host "  reason: $($round2.SkipReason)"
    }
}
