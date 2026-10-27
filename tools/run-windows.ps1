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
$gameArgs = @()
if ($DebugLogging) { $gameArgs += @("--log-level", "DEBUG") }
if ($LocalPbf) { $gameArgs += @("--osm-source", "pbf") }
& $Godot --path (Join-Path $repo "godot") -- @gameArgs
exit $LASTEXITCODE
