$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$frontendRoot = Join-Path $projectRoot "frontend"
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

& (Join-Path $projectRoot "tools\build_desktop_sidecar.ps1")
Push-Location $frontendRoot
try {
    npm run desktop:build
    if ($LASTEXITCODE -ne 0) { throw "Desktop frontend build failed." }
    & $cargo build --manifest-path "src-tauri\Cargo.toml" --release
    if ($LASTEXITCODE -ne 0) { throw "Desktop application build failed." }
} finally {
    Pop-Location
}

$installerOutput = Join-Path $frontendRoot "src-tauri\target\release\bundle\nsis"
New-Item -ItemType Directory -Path $installerOutput -Force | Out-Null
& $makensis /V2 (Join-Path $projectRoot "tools\you-just-lead-installer.nsi")
if ($LASTEXITCODE -ne 0) { throw "NSIS installer build failed." }
