# run-tests.ps1 — convenience wrapper for the workspace-test-runner devex tool.
# Usage: .\scripts\run-tests.ps1 [--no-skip-integration] [--coverage] [--package <name>]
#
# Delegates all arg parsing to the Typer CLI — pass flags through unchanged.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = Split-Path -Parent $ScriptDir

Push-Location $BackendRoot
try {
    & uv run agentic devex workspace-test-runner @args
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
