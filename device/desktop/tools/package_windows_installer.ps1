# 打包 Windows 安装包：后端 sidecar -> 桌面端前端 -> Tauri release -> NSIS 安装包。
# 后端仓库位置解析规则见 build_desktop_sidecar.ps1。
param(
    [string]$BackendRoot = ""
)

$ErrorActionPreference = "Stop"

$desktopRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if ([string]::IsNullOrWhiteSpace($BackendRoot)) { $BackendRoot = $env:YJL_BACKEND_ROOT }
if ([string]::IsNullOrWhiteSpace($BackendRoot)) {
    $BackendRoot = Join-Path (Split-Path (Split-Path $desktopRoot -Parent) -Parent) "You Just Lead\competition-agent"
}

$cargo = Join-Path $env:USERPROFILE ".cargo\bin\cargo.exe"
$nsisCandidates = @(
    (Join-Path ${env:ProgramFiles(x86)} "NSIS\makensis.exe"),
    (Join-Path $env:ProgramFiles "NSIS\makensis.exe")
)
$makensis = $nsisCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

if (-not (Test-Path -LiteralPath $cargo)) {
    throw "Rust Cargo was not found at $cargo. Install Rust before packaging."
}
if (-not $makensis) {
    throw "NSIS was not found. Install NSIS before packaging."
}

& (Join-Path $PSScriptRoot "build_desktop_sidecar.ps1") -BackendRoot $BackendRoot
Push-Location $desktopRoot
try {
    npm run desktop:build
    if ($LASTEXITCODE -ne 0) { throw "Desktop frontend build failed." }
    & $cargo build --manifest-path "src-tauri\Cargo.toml" --release --features custom-protocol
    if ($LASTEXITCODE -ne 0) { throw "Desktop application build failed." }
} finally {
    Pop-Location
}

$installerOutput = Join-Path $desktopRoot "src-tauri\target\release\bundle\nsis"
New-Item -ItemType Directory -Path $installerOutput -Force | Out-Null
& $makensis /V2 (Join-Path $PSScriptRoot "you-just-lead-installer.nsi")
if ($LASTEXITCODE -ne 0) { throw "NSIS installer build failed." }
