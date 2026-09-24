# 构建桌面端需要的后端 sidecar：用 PyInstaller 把后端的 app/desktop_entry.py 打成
# 单文件 competition-agent-api.exe，再拷进本项目的 src-tauri/binaries/ 供 Tauri 打包。
#
# 后端仓库位置按以下顺序解析：
#   1. -BackendRoot 参数
#   2. 环境变量 YJL_BACKEND_ROOT
#   3. 本机布局：<盘符>\YouJustLead\desktop 与 <盘符>\You Just Lead\competition-agent 同级
param(
    [string]$BackendRoot = "",
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"

$desktopRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if ([string]::IsNullOrWhiteSpace($BackendRoot)) { $BackendRoot = $env:YJL_BACKEND_ROOT }
if ([string]::IsNullOrWhiteSpace($BackendRoot)) {
    $BackendRoot = Join-Path (Split-Path (Split-Path $desktopRoot -Parent) -Parent) "You Just Lead\competition-agent"
}
if (-not (Test-Path -LiteralPath (Join-Path $BackendRoot "app\desktop_entry.py"))) {
    throw "Backend repository not found at '$BackendRoot'. Pass -BackendRoot or set YJL_BACKEND_ROOT."
}
$BackendRoot = (Resolve-Path $BackendRoot).Path

$targetTriple = "x86_64-pc-windows-msvc"
$outputDir = Join-Path $desktopRoot "src-tauri\binaries"

if ([string]::IsNullOrWhiteSpace($Python)) {
    $venvPython = Join-Path $BackendRoot ".desktop-build-venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython)) {
        & python -m venv (Join-Path $BackendRoot ".desktop-build-venv")
    }
    $Python = $venvPython
}

Push-Location $BackendRoot
try {
    & $Python -m pip install "PyYAML>=6" "pypdf>=5.0" "keyring>=25" "pyinstaller>=6.11"
    & $Python -m PyInstaller --noconfirm --clean --onefile --name "competition-agent-api" "--paths=$BackendRoot" (Join-Path $BackendRoot "app\desktop_entry.py")
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $BackendRoot "dist\competition-agent-api.exe") -Destination (Join-Path $outputDir "competition-agent-api-$targetTriple.exe") -Force
} finally {
    Pop-Location
}
