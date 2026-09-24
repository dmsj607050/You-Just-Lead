param(
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$frontendRoot = Join-Path $projectRoot "frontend"
$targetTriple = "x86_64-pc-windows-msvc"
$outputDir = Join-Path $frontendRoot "src-tauri\binaries"

if ([string]::IsNullOrWhiteSpace($Python)) {
    $venvPython = Join-Path $projectRoot ".desktop-build-venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython)) {
        & python -m venv (Join-Path $projectRoot ".desktop-build-venv")
    }
    $Python = $venvPython
}

Push-Location $projectRoot
try {
    & $Python -m pip install "PyYAML>=6" "pypdf>=5.0" "keyring>=25" "pyinstaller>=6.11"
    & $Python -m PyInstaller --noconfirm --clean --onefile --name "competition-agent-api" "--paths=$projectRoot" (Join-Path $projectRoot "app\desktop_entry.py")
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $projectRoot "dist\competition-agent-api.exe") -Destination (Join-Path $outputDir "competition-agent-api-$targetTriple.exe") -Force
} finally {
    Pop-Location
}
