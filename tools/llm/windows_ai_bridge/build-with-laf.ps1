# Build PhiSilicaBridge with LAF Identity
# This script compiles the RC file and injects it into the executable

Write-Host "🔨 Building PhiSilicaBridge with LAF Identity..." -ForegroundColor Cyan
Write-Host ""

# Step 1: Build the C# project
Write-Host "1️⃣  Building C# project..." -ForegroundColor Yellow
dotnet build -c Release
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Build failed" -ForegroundColor Red
    exit 1
}
Write-Host "✅ Build successful" -ForegroundColor Green
Write-Host ""

# Step 2: Compile the RC file to RES
Write-Host "2️⃣  Compiling LAF identity resource..." -ForegroundColor Yellow
$rcExe = "rc.exe"
$rcFile = "laf_identity.rc"
$resFile = "laf_identity.res"

# Check if rc.exe is available (comes with Visual Studio)
$rcPath = & where.exe rc.exe 2>$null
if (-not $rcPath) {
    Write-Host "⚠️  rc.exe not found. Trying to locate Visual Studio..." -ForegroundColor Yellow
    
    # Common paths for rc.exe
    $vsPaths = @(
        "${env:ProgramFiles}\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\*\bin\Hostx64\x64\rc.exe",
        "${env:ProgramFiles}\Microsoft Visual Studio\2022\Professional\VC\Tools\MSVC\*\bin\Hostx64\x64\rc.exe",
        "${env:ProgramFiles}\Microsoft Visual Studio\2022\Enterprise\VC\Tools\MSVC\*\bin\Hostx64\x64\rc.exe",
        "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\rc.exe"
    )
    
    foreach ($pattern in $vsPaths) {
        $found = Get-Item $pattern -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) {
            $rcExe = $found.FullName
            Write-Host "  Found: $rcExe" -ForegroundColor Green
            break
        }
    }
    
    if (-not (Test-Path $rcExe)) {
        Write-Host "❌ rc.exe not found. Please install Visual Studio with C++ tools." -ForegroundColor Red
        Write-Host "   Or use Developer Command Prompt for VS" -ForegroundColor Yellow
        exit 1
    }
}

# Compile RC to RES
& $rcExe /fo $resFile $rcFile
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ RC compilation failed" -ForegroundColor Red
    exit 1
}
Write-Host "✅ Resource compiled" -ForegroundColor Green
Write-Host ""

# Step 3: Inject resource into executable
Write-Host "3️⃣  Injecting LAF identity into executable..." -ForegroundColor Yellow
$exePath = "bin\x64\Release\net8.0-windows10.0.22621.0\win-x64\PhiSilicaBridge.exe"

if (-not (Test-Path $exePath)) {
    Write-Host "❌ Executable not found at: $exePath" -ForegroundColor Red
    exit 1
}

# Check for ResourceHacker
$resHacker = "reshacker\ResourceHacker.exe"
if (-not (Test-Path $resHacker)) {
    Write-Host "⚠️  ResourceHacker not found. Downloading..." -ForegroundColor Yellow
    
    # Download ResourceHacker
    $downloadUrl = "https://www.angusj.com/resourcehacker/resource_hacker.zip"
    $zipFile = "resource_hacker.zip"
    
    try {
        Invoke-WebRequest -Uri $downloadUrl -OutFile $zipFile -UseBasicParsing
        Expand-Archive -Path $zipFile -DestinationPath "reshacker" -Force
        Remove-Item $zipFile
        Write-Host "✅ ResourceHacker downloaded" -ForegroundColor Green
    } catch {
        Write-Host "❌ Failed to download ResourceHacker" -ForegroundColor Red
        Write-Host "   Please download manually from: http://www.angusj.com/resourcehacker/" -ForegroundColor Yellow
        Write-Host "   Extract to: reshacker\" -ForegroundColor Yellow
        exit 1
    }
}

# Inject resource
& $resHacker -open $exePath -save $exePath -action addoverwrite -res $resFile -log inject.log
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Resource injection failed" -ForegroundColor Red
    Get-Content inject.log | Write-Host
    exit 1
}

Write-Host "✅ LAF identity injected" -ForegroundColor Green
Write-Host ""

# Step 4: Verify
Write-Host "4️⃣  Testing LAF unlock..." -ForegroundColor Yellow
dotnet run -c Release -- --unlock
Write-Host ""

Write-Host "=" * 60 -ForegroundColor Cyan
Write-Host "✅ BUILD COMPLETE" -ForegroundColor Green
Write-Host "=" * 60 -ForegroundColor Cyan
Write-Host ""
Write-Host "Executable: $exePath" -ForegroundColor Cyan
Write-Host "LAF Identity: Prompts-a.prompting.learning.tool_z2bh13qew7ej0" -ForegroundColor Cyan
Write-Host ""
Write-Host "Test with: dotnet run -c Release -- --info" -ForegroundColor Yellow
