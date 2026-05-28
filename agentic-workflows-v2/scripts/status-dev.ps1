[CmdletBinding()]
param(
    [string]$BackendUrl = 'http://127.0.0.1:8012/api/health',
    [string]$FrontendUrl = 'http://127.0.0.1:5174',
    [int[]]$Ports = @(8012, 5174)
)

$ErrorActionPreference = 'Continue'

Write-Host "Dev status" -ForegroundColor Cyan
Write-Host "----------"

foreach ($port in $Ports) {
    $listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object LocalAddress, LocalPort, OwningProcess -Unique

    if (-not $listeners) {
        Write-Host "Port ${port}: not listening" -ForegroundColor Yellow
        continue
    }

    foreach ($listener in $listeners) {
        $procName = ''
        try {
            $proc = Get-Process -Id $listener.OwningProcess -ErrorAction Stop
            $procName = $proc.ProcessName
        } catch {
            $procName = 'unknown'
        }

        Write-Host "Port $($listener.LocalPort): PID $($listener.OwningProcess) ($procName)" -ForegroundColor Green
    }
}

try {
    $health = Invoke-RestMethod -Uri $BackendUrl -TimeoutSec 5
    Write-Host "Backend health: $($health.status)" -ForegroundColor Green
} catch {
    Write-Host "Backend health check failed: $($_.Exception.Message)" -ForegroundColor Red
}

try {
    $resp = Invoke-WebRequest -UseBasicParsing -Uri $FrontendUrl -TimeoutSec 5
    Write-Host "Frontend HTTP: $($resp.StatusCode)" -ForegroundColor Green
} catch {
    Write-Host "Frontend check failed: $($_.Exception.Message)" -ForegroundColor Red
}
