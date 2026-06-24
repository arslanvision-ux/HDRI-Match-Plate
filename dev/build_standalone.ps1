# Build HDRI Match Plate standalone executable
Write-Host "Building HDRI Match Plate standalone executable..."

# Check if pyinstaller is installed
if (-not (Get-Command "pyinstaller" -ErrorAction SilentlyContinue)) {
    Write-Host "Installing PyInstaller..."
    python -m pip install pyinstaller
}

Write-Host "Ensuring all required dependencies are installed..."
python -m pip install google-genai pydantic pillow

# Ensure ocio_configs directory exists, user can place config.ocio here
if (-not (Test-Path "ocio_configs")) {
    New-Item -ItemType Directory -Force -Path "ocio_configs" | Out-Null
    Write-Host "Created ocio_configs directory. You can place your OCIO configs here before building to bundle them."
}

# Run PyInstaller using the spec file
Write-Host "Running PyInstaller..."
python -m PyInstaller HDRI_Match.spec

Write-Host "Build complete! Check the 'dist/HDRI_Match_Plate' folder."
