[CmdletBinding()]
param(
    [switch]$Reload,
    [string]$BackendHost = '127.0.0.1',
    [int]$BackendPort = 8012,
    [string]$FrontendHost = '127.0.0.1',
    [int]$FrontendPort = 5174,
    [string]$ApiProxyTarget = 'http://127.0.0.1:8012',
    [switch]$AutoTierFromProbe,
    [int[]]$StopPorts = @(8012, 5174)
)

$ErrorActionPreference = 'Stop'

$scriptsDir = Split-Path -Parent $PSCommandPath
$stopScript = Join-Path $scriptsDir 'stop-dev.ps1'
$startScript = Join-Path $scriptsDir 'start-dev.ps1'
$statusScript = Join-Path $scriptsDir 'status-dev.ps1'

Write-Host 'Restarting dev services...' -ForegroundColor Cyan

& $stopScript -Ports $StopPorts
Start-Sleep -Seconds 1

$startParams = @{
    BackendHost = $BackendHost
    BackendPort = $BackendPort
    FrontendHost = $FrontendHost
    FrontendPort = $FrontendPort
    ApiProxyTarget = $ApiProxyTarget
}
if ($Reload) {
    $startParams.Reload = $true
}
if ($AutoTierFromProbe) {
    $startParams.AutoTierFromProbe = $true
}

& $startScript @startParams
Start-Sleep -Seconds 1

& $statusScript -BackendUrl "http://$BackendHost`:$BackendPort/api/health" -FrontendUrl "http://$FrontendHost`:$FrontendPort" -Ports @($BackendPort, $FrontendPort)

Write-Host 'Restart complete.' -ForegroundColor Green
