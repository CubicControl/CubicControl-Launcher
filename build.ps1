# Build script for CubicControl.exe
# This script uses PyInstaller with the spec file to build the executable

Write-Host "Building CubicControl.exe..." -ForegroundColor Green

# Check if PyInstaller is installed
try {
    $pyinstallerVersion = pyinstaller --version 2>&1
    Write-Host "PyInstaller version: $pyinstallerVersion" -ForegroundColor Cyan
} catch {
    Write-Host "PyInstaller not found. Installing..." -ForegroundColor Yellow
    pip install pyinstaller
}

# Clean previous builds
if (Test-Path "build") {
    Write-Host "Cleaning build directory..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force "build"
}
if (Test-Path "dist\CubicControl.exe") {
    Write-Host "Cleaning old executable..." -ForegroundColor Yellow
    Remove-Item -Force "dist\CubicControl.exe"
}

# Build with spec file
Write-Host "Running PyInstaller..." -ForegroundColor Green
pyinstaller control_panel.spec --clean

if ($LASTEXITCODE -eq 0) {
    Write-Host "`nBuild completed successfully!" -ForegroundColor Green
    Write-Host "Executable location: dist\CubicControl.exe" -ForegroundColor Cyan

    # Check if executable exists
    if (Test-Path "dist\CubicControl.exe") {
        $fileSize = (Get-Item "dist\CubicControl.exe").Length / 1MB
        Write-Host "File size: $([math]::Round($fileSize, 2)) MB" -ForegroundColor Cyan
    }
} else {
    Write-Host "`nBuild failed!" -ForegroundColor Red
    exit 1
}

