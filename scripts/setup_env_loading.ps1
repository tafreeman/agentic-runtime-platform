<#
.Synopsis
Setup automatic .env loading for the Python virtual environment.

.Description
Modifies the venv activation script to automatically load environment variables
from the .env file. This ensures API keys and credentials are available whenever
the venv is activated.

.Example
.\scripts\setup_env_loading.ps1

.Notes
This script should be run once after creating or recreating the virtual environment.
#>

param(
    [string]$VenvPath = ".venv"
)

$ActivateScript = Join-Path -Path $VenvPath -ChildPath "Scripts\Activate.ps1"

if (-not (Test-Path -Path $ActivateScript)) {
    Write-Error "Activation script not found: $ActivateScript"
    Write-Error "Make sure your venv exists at: $(Resolve-Path -Path $VenvPath -ErrorAction SilentlyContinue)"
    exit 1
}

# Check if .env loading code already exists
$content = Get-Content -Path $ActivateScript -Raw
if ($content -match "Load .env file if it exists") {
    Write-Host "✓ .env loading already configured in activation script"
    exit 0
}

# Find the insertion point (after PATH setup)
$insertPoint = "# Add the venv to the PATH`r`nCopy-Item -Path Env:PATH -Destination Env:_OLD_VIRTUAL_PATH`r`n`$Env:PATH = `"`$VenvExecDir`$([System.IO.Path]::PathSeparator)`$Env:PATH`""

$envLoadingCode = @"

# Load .env file if it exists (for LLM API keys and provider credentials)
`$EnvFilePath = Join-Path -Path `$VenvDir -ChildPath '..\..\.env' | Resolve-Path -ErrorAction SilentlyContinue
if (`$EnvFilePath -and (Test-Path -Path `$EnvFilePath)) {
    Write-Verbose "Loading environment variables from: `$EnvFilePath"
    Get-Content -Path `$EnvFilePath | Where-Object { `$_ -match '^\s*[^#\s]' } | ForEach-Object {
        `$line = `$_.Trim()
        if (`$line -and -not `$line.StartsWith('#')) {
            `$key, `$value = `$line -split '=', 2
            if (`$key -and `$value) {
                `$key = `$key.Trim()
                `$value = `$value.Trim()
                [System.Environment]::SetEnvironmentVariable(`$key, `$value)
                Write-Verbose "  Set `$key"
            }
        }
    }
}
"@

if ($content -match [regex]::Escape($insertPoint)) {
    $newContent = $content -replace [regex]::Escape($insertPoint), "$insertPoint$envLoadingCode"
    Set-Content -Path $ActivateScript -Value $newContent -Encoding UTF8
    Write-Host "✓ Successfully added .env auto-loading to activation script: $ActivateScript"
} else {
    Write-Error "Could not find insertion point in activation script. Manual update may be required."
    exit 1
}
