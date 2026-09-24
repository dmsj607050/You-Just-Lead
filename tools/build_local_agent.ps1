# 构建 Windows 本地执行器：把后端冻成单文件 dist/competition-agent-api.exe。
#
# 这是 app/release_service.py 发布清单里 required_for_release 的那件产物，也是
# 端侧应用在本机连的那个本地 Agent —— 起它等价于 `python main.py serve`，
# 给没有 Python 环境的机器用。
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File tools\build_local_agent.ps1
param(
    [string]$Python = ""
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
    & $Python -m pip install "PyYAML>=6" "pypdf>=5.0" "keyring>=25" "pyinstaller>=6.11"
    & $Python -m PyInstaller --noconfirm --clean --onefile --name "competition-agent-api" "--paths=$projectRoot" (Join-Path $projectRoot "app\local_agent_entry.py")
} finally {
    Pop-Location
}
