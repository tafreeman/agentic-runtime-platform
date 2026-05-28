[CmdletBinding()]
param(
  [string]$Topic = "agentic AI for software engineers and architects",
  [string]$Goal = "",
  [string]$Domain = "ai_software",
  [double]$MinCi = 0.85,
  [int]$MaxRounds = 4,
  [int]$MinRecentSources = 12,
  [int]$RecencyWindowDays = 183,
  [string]$OutDir = "reports/deep-research",
  [string]$SmallModel = "",
  [string]$HeavyModel = "",
  [string]$Tier2Model = "",
  [string]$Tier3Model = "",
  [string]$Tier4Model = "",
  [switch]$BootstrapDeps
)

$ErrorActionPreference = "Stop"

$scriptsDir = Split-Path -Parent $PSCommandPath
$projectRoot = Resolve-Path (Join-Path $scriptsDir "..")
$repoRoot = Resolve-Path (Join-Path $projectRoot "..")
Set-Location $repoRoot

$pythonExe = $null
$pythonPrefix = @()

$venvCandidates = @(
  (Join-Path $repoRoot ".venv314\Scripts\python.exe"),
  (Join-Path $repoRoot ".venv\Scripts\python.exe")
)
foreach ($candidate in $venvCandidates) {
  if (Test-Path $candidate) {
    $pythonExe = $candidate
    break
  }
}

if (-not $pythonExe) {
  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py) {
    $pythonExe = "py"
    $pythonPrefix = @("-3.14")
  } else {
    $pythonExe = "python"
  }
}

function Invoke-SelectedPython {
  param([string[]]$PyArgs)
  & $pythonExe @pythonPrefix @PyArgs
}

$checkArgs = @(
  "-c",
  "import pydantic, langchain_core, langgraph, langchain_openai"
)
Invoke-SelectedPython $checkArgs
if ($LASTEXITCODE -ne 0) {
  if (-not $BootstrapDeps) {
    throw "Missing Python dependencies for deep research workflow. Re-run with -BootstrapDeps or install: pip install -e .\agentic-workflows-v2"
  }
  Write-Host "Installing workflow dependencies into selected Python..." -ForegroundColor Yellow
  $installCommands = @(
    @("-m", "pip", "install", "-e", ".\agentic-workflows-v2"),
    @(
      "-m", "pip", "install",
      "langchain",
      "langchain-openai",
      "langchain-ollama",
      "langchain-anthropic",
      "langchain-google-genai",
      "langgraph-checkpoint-sqlite"
    )
  )
  foreach ($cmd in $installCommands) {
    Invoke-SelectedPython $cmd
    if ($LASTEXITCODE -ne 0) {
      throw "Dependency bootstrap failed."
    }
  }
}

$argsList = @(
  "agentic-workflows-v2\scripts\run_deep_research.py",
  "--domain", $Domain,
  "--min-ci", "$MinCi",
  "--max-rounds", "$MaxRounds",
  "--min-recent-sources", "$MinRecentSources",
  "--recency-window-days", "$RecencyWindowDays",
  "--out-dir", $OutDir
)

if ($Goal) {
  $argsList += @("--goal", $Goal)
} else {
  $argsList += @("--topic", $Topic)
}

if ($SmallModel) {
  $argsList += @("--small-model", $SmallModel)
}
if ($HeavyModel) {
  $argsList += @("--heavy-model", $HeavyModel)
}

if ($Tier2Model) {
  $env:AGENTIC_MODEL_TIER_2 = $Tier2Model
}
if ($Tier3Model) {
  $env:AGENTIC_MODEL_TIER_3 = $Tier3Model
}
if ($Tier4Model) {
  $env:AGENTIC_MODEL_TIER_4 = $Tier4Model
}

Invoke-SelectedPython $argsList
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}
