# NPU Diagnostic Script
# Checks if NPU hardware is detected and Phi Silica requirements are met

Write-Host "🔍 NPU & Phi Silica Diagnostic" -ForegroundColor Cyan
Write-Host "=" * 60 -ForegroundColor Cyan
Write-Host ""

# Check Windows version
Write-Host "📋 System Information:" -ForegroundColor Yellow
$os = Get-CimInstance Win32_OperatingSystem
Write-Host "  OS: $($os.Caption)" -ForegroundColor White
Write-Host "  Build: $($os.BuildNumber)" -ForegroundColor White
Write-Host "  Version: $($os.Version)" -ForegroundColor White
Write-Host ""

# Check for NPU devices
Write-Host "🧠 NPU Detection:" -ForegroundColor Yellow
$npuDevices = Get-PnpDevice | Where-Object { 
    $_.FriendlyName -match "NPU|Neural|AI Accelerator|Snapdragon|Qualcomm" -or
    $_.Class -eq "NeuralProcessingUnit"
}

if ($npuDevices) {
    Write-Host "  ✅ NPU device(s) found:" -ForegroundColor Green
    foreach ($device in $npuDevices) {
        Write-Host "     - $($device.FriendlyName) [$($device.Status)]" -ForegroundColor White
    }
} else {
    Write-Host "  ⚠️  No NPU devices detected" -ForegroundColor Yellow
    Write-Host "     Checking GPU for AI capabilities..." -ForegroundColor Gray
    
    $gpus = Get-PnpDevice -Class Display
    foreach ($gpu in $gpus) {
        Write-Host "     - $($gpu.FriendlyName)" -ForegroundColor White
    }
}
Write-Host ""

# Check Windows AI SDK/Runtime
Write-Host "📦 Windows AI SDK:" -ForegroundColor Yellow
$appSdkPath = "${env:ProgramFiles}\WindowsApps"
$aiPackages = Get-ChildItem $appSdkPath -ErrorAction SilentlyContinue | 
    Where-Object { $_.Name -match "Microsoft.WindowsAppSDK|AI|Phi" }

if ($aiPackages) {
    Write-Host "  ✅ Windows App SDK packages found:" -ForegroundColor Green
    $aiPackages | Select-Object -First 5 | ForEach-Object {
        Write-Host "     - $($_.Name)" -ForegroundColor White
    }
} else {
    Write-Host "  ⚠️  No Windows App SDK AI packages detected" -ForegroundColor Yellow
}
Write-Host ""

# Check LAF configuration
Write-Host "🔐 LAF Configuration:" -ForegroundColor Yellow
$lafConfigured = $env:PHI_SILICA_LAF_TOKEN -ne $null
if ($lafConfigured) {
    Write-Host "  ✅ LAF Token: Configured" -ForegroundColor Green
    Write-Host "     Feature ID: $env:PHI_SILICA_LAF_FEATURE_ID" -ForegroundColor White
} else {
    Write-Host "  ❌ LAF Token: Not configured" -ForegroundColor Red
}
Write-Host ""

# Test Phi Silica availability
Write-Host "🧪 Phi Silica Test:" -ForegroundColor Yellow
if (Test-Path "bin\x64\Release\net8.0-windows10.0.22621.0\win-x64\PhiSilicaBridge.exe") {
    $result = dotnet run -c Release -- --info 2>&1 | ConvertFrom-Json
    
    if ($result.available) {
        Write-Host "  ✅ Phi Silica: AVAILABLE" -ForegroundColor Green
    } else {
        Write-Host "  ❌ Phi Silica: UNAVAILABLE" -ForegroundColor Red
        Write-Host "     Error: $($result.error)" -ForegroundColor Gray
        Write-Host "     LAF Status: $($result.laf.status)" -ForegroundColor Gray
    }
} else {
    Write-Host "  ⚠️  Bridge not built" -ForegroundColor Yellow
}
Write-Host ""

# Recommendations
Write-Host "💡 Recommendations:" -ForegroundColor Cyan
Write-Host ""

if (-not $npuDevices) {
    Write-Host "  ⚠️  No NPU detected. Phi Silica requires:" -ForegroundColor Yellow
    Write-Host "     - Copilot+ PC with Qualcomm Snapdragon X Elite/Plus" -ForegroundColor White
    Write-Host "     - OR Intel Core Ultra (Series 2)" -ForegroundColor White
    Write-Host "     - OR AMD Ryzen AI (Series 3)" -ForegroundColor White
    Write-Host ""
}

if ($result.laf.status -eq "Unavailable") {
    Write-Host "  📝 LAF Status 'Unavailable' could mean:" -ForegroundColor Yellow
    Write-Host "     1. Hardware doesn't meet requirements (no NPU)" -ForegroundColor White
    Write-Host "     2. Feature not yet released for your Windows build" -ForegroundColor White
    Write-Host "     3. App needs to be packaged as MSIX with proper manifest" -ForegroundColor White
    Write-Host "     4. NPU drivers not installed" -ForegroundColor White
    Write-Host ""
    Write-Host "  🔗 Next steps:" -ForegroundColor Cyan
    Write-Host "     - Check NPU drivers in Device Manager" -ForegroundColor White
    Write-Host "     - Update Windows to latest insider build if on preview" -ForegroundColor White
    Write-Host "     - See: https://learn.microsoft.com/windows/ai/apis/phi-silica" -ForegroundColor White
}

Write-Host ""
Write-Host "=" * 60 -ForegroundColor Cyan
