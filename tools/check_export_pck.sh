#!/usr/bin/env bash
# Export the Windows pck and check it holds every GLB model under godot/assets
# and the animal palette textures. Usage: tools/check_export_pck.sh [GODOT]
set -euo pipefail
GODOT="${1:-${GODOT:-godot}}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
"$GODOT" --headless --path "$ROOT/godot" --export-pack "Windows Desktop" "$TMP/x.pck"
mkdir "$TMP/empty" && echo 'config_version=5' > "$TMP/empty/project.godot"  # a bare project: res:// holds only the pck
cp "$ROOT/tools/check_export_pck.gd" "$TMP/empty/"
cd "$ROOT/godot"
"$GODOT" --headless --path "$TMP/empty" --script res://check_export_pck.gd -- "$TMP/x.pck" \
  $(find assets -name '*.glb' -o -path 'assets/animals/*.png' | sort | sed 's|^|res://|')
