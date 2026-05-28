[CmdletBinding()]
param(
    [int[]]$Ports = @(8012, 5174)
)

$ErrorActionPreference = 'SilentlyContinue'

$projectRoot = Split-Path -Parent $PSScriptRoot
$logsDir = Join-Path $projectRoot '.run-logs'
$backendPidFile = Join-Path $logsDir 'backend.pid'
$frontendPidFile = Join-Path $logsDir 'frontend.pid'

Write-Host "Stopping dev services..." -ForegroundColor Yellow

function Stop-ProcessRobust {
    param(
        [int]$TargetPid,
        [string]$Context
    )

    if ($TargetPid -eq $PID) {
        Write-Host "Skipping current shell PID $TargetPid ($Context)"
        return
    }

    try {
        Stop-Process -Id $TargetPid -Force -ErrorAction Stop
        Write-Host "Stopped PID $TargetPid ($Context)"
        return
    } catch {
        # Fallback to taskkill for process trees and stubborn children.
        $tk = Start-Process -FilePath 'taskkill.exe' -ArgumentList @('/PID', "$TargetPid", '/T', '/F') -PassThru -Wait -NoNewWindow
        if ($tk.ExitCode -eq 0) {
            Write-Host "Stopped PID $TargetPid via taskkill ($Context)"
        } else {
            $procName = 'unknown'
            try {
                $procName = (Get-Process -Id $TargetPid -ErrorAction Stop).ProcessName
            } catch {
                # Best effort.
            }
            Write-Host "Could not stop PID $TargetPid ($procName) ($Context). It may be protected or owned by another session/user."
        }
    }
}

function Stop-IfRunningPidFile {
    param([string]$PidFile)
    if (Test-Path $PidFile) {
        $pidText = (Get-Content $PidFile -Raw).Trim()
        if ($pidText -match '^\d+$') {
            $targetPid = [int]$pidText
            Stop-ProcessRobust -TargetPid $targetPid -Context "from $(Split-Path $PidFile -Leaf)"
        }
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    }
}

Stop-IfRunningPidFile -PidFile $backendPidFile
Stop-IfRunningPidFile -PidFile $frontendPidFile

foreach ($port in $Ports) {
    $listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique

    foreach ($p in $listeners) {
        Stop-ProcessRobust -TargetPid $p -Context "on port $port"
    }
}

Write-Host "Done. Ports cleaned: $($Ports -join ', ')" -ForegroundColor Green
