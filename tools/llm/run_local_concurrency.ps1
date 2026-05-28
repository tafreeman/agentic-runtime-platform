param(
  [string]$CpuModel = "local:phi4-cpu",
  [string]$GpuModel = "local:phi4-gpu",
  [int]$Rounds = 1,
  [int]$MaxTokens = 300,
  [double]$Temperature = 0.1,
  [string]$OutDir = "reports/model-bakeoff",
  [switch]$SkipSequential,
  [switch]$Fast
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
Set-Location $RepoRoot

$PyLauncher = Get-Command py -ErrorAction SilentlyContinue

$ScriptArgs = @(
  "tools\llm\run_local_concurrency.py",
  "--cpu-model", $CpuModel,
  "--gpu-model", $GpuModel,
  "--rounds", "$Rounds",
  "--max-tokens", "$MaxTokens",
  "--temperature", "$Temperature",
  "--out-dir", $OutDir
)
if ($SkipSequential) { $ScriptArgs += "--skip-sequential" }
if ($Fast) { $ScriptArgs += "--fast" }

if ($PyLauncher) {
  & py -3.14 @ScriptArgs
}
else {
  & python @ScriptArgs
}
