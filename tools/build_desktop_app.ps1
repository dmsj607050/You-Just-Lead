# Build the Windows desktop app: freeze the backend and the built-in UI into
# one file at dist/YouJustLead.exe.
#
# Difference from build_local_agent.ps1: that one builds the headless local
# service (what the HarmonyOS app connects to on a PC). This one builds the
# complete app a user double-clicks: it starts the backend and opens a window,
# with the UI files bundled inside the exe.
#
# The window uses the system Edge in `--app` mode (no address bar), so no
# browser engine is shipped and the package stays two orders of magnitude
# smaller than an embedded-runtime approach.
#
# NOTE: keep this file pure ASCII. Windows PowerShell 5.1 decodes a UTF-8
# script without a BOM as ANSI, which turns non-ASCII comments into mojibake
# and breaks parsing.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File tools\build_desktop_app.ps1
#   powershell -ExecutionPolicy Bypass -File tools\build_desktop_app.ps1 -Python "C:\...\python.exe"
param(
    [string]$Python = "",
    [string]$Name = "YouJustLead"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if ([string]::IsNullOrWhiteSpace($Python)) {
    $venvPython = Join-Path $projectRoot ".local-agent-build-venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython)) {
        & python -m venv (Join-Path $projectRoot ".local-agent-build-venv")
    }
    $Python = $venvPython
}

Push-Location $projectRoot
try {
    & $Python -m pip install "PyYAML>=6" "pypdf>=5.0" "pyinstaller>=6.11"

    # Exclude the training stack. PyInstaller walks imports, and api_server
    # reaches training/catalog and the schedulers, which pull in torch, numpy,
    # matplotlib, PIL and jinja2 unconditionally. Shipping them would turn a
    # ~20 MB app into a multi-GB download, and this app never trains in-process:
    # training runs as a separate process (or on another machine entirely).
    $excludeModules = @(
        "torch", "torchvision", "torchaudio",
        "numpy", "pandas", "scipy", "sklearn",
        "matplotlib", "PIL", "cv2",
        "mlflow", "jinja2", "IPython", "notebook", "tornado"
    )

    # Pass arguments as an array instead of using backtick line continuations:
    # PowerShell parses a leading `--xxx` at the start of a continued line as an
    # operator and fails with "Missing expression after unary operator '--'".
    #
    # web/ must be bundled: after freezing, WEB_ROOT points at sys._MEIPASS/web
    # (see app/api_server.py). Windows separates source and destination with a
    # semicolon in --add-data.
    $pyInstallerArgs = @(
        "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile",
        "--name", $Name,
        "--paths", $projectRoot,
        "--add-data", "web;web",
        "--hidden-import", "yaml",
        "--hidden-import", "pypdf"
    )
    foreach ($module in $excludeModules) {
        $pyInstallerArgs += @("--exclude-module", $module)
    }
    $pyInstallerArgs += (Join-Path $projectRoot "app\desktop_entry.py")
    & $Python @pyInstallerArgs
} finally {
    Pop-Location
}

$artifact = Join-Path $projectRoot "dist\$Name.exe"
if (Test-Path -LiteralPath $artifact) {
    $size = [math]::Round((Get-Item -LiteralPath $artifact).Length / 1MB, 1)
    Write-Output "built: $artifact ($size MB)"
} else {
    Write-Error "PyInstaller did not produce $artifact"
}
