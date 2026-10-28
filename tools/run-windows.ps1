# Native Windows Godot; run from PowerShell or through `make run` in WSL.
param(
    [string]$Godot = "C:\Godot\Godot_v4.7.2-stable_win64_console.exe",
    [switch]$DebugLogging,
    [switch]$LocalPbf
)
$ErrorActionPreference = "Stop"
$repo = Split-Path $PSScriptRoot -Parent
if (-not (Test-Path -LiteralPath $Godot)) {
    throw "Windows Godot was not found at $Godot. Supply -Godot with its path."
}
$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = Join-Path $repo ".venv-windows\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $python)) {
    throw "Create .venv-windows with Windows Python and install requirements.txt first (see README)."
}
# osmium-tool for local .osm.pbf maps, as the release bundles it (windows-release.yml):
# conda-forge's build through a standalone micromamba, once, into .osmium-windows.
$osmiumEnv = Join-Path $repo ".osmium-windows"
$osmium = Join-Path $osmiumEnv "Library\bin\osmium.exe"
if (-not (Test-Path -LiteralPath $osmium)) {
    Write-Host "Installing osmium-tool 1.19.1 (conda-forge) into $osmiumEnv ..."
    $mamba = Join-Path $env:TEMP "rrt-micromamba"
    New-Item -ItemType Directory -Force $mamba | Out-Null
    Invoke-WebRequest -UseBasicParsing "https://micro.mamba.pm/api/micromamba/win-64/latest" -OutFile (Join-Path $mamba "micromamba.tar.bz2")
    tar -xjf (Join-Path $mamba "micromamba.tar.bz2") -C $mamba Library/bin/micromamba.exe
    & (Join-Path $mamba "Library\bin\micromamba.exe") create --yes --quiet --root-prefix (Join-Path $mamba "root") `
        --prefix $osmiumEnv --override-channels -c conda-forge "osmium-tool=1.19.1"
    if ($LASTEXITCODE -ne 0) { throw "micromamba could not install osmium-tool" }
    Copy-Item (Join-Path $osmiumEnv "*.dll") (Split-Path $osmium)  # the MSVC runtime beside osmium.exe, as in the release
}
$gameArgs = @()
if ($DebugLogging) { $gameArgs += @("--log-level", "DEBUG") }
if ($LocalPbf) { $gameArgs += @("--osm-source", "pbf") }
& $Godot --path (Join-Path $repo "godot") -- @gameArgs
exit $LASTEXITCODE
