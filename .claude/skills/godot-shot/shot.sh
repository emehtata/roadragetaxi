#!/usr/bin/env bash
# Render the real game and save a screenshot.
#
# usage: shot.sh OUT.png [--wait SECONDS] [--godot-arg ARG]... [SERVER ARGS...]
#   OUT.png          where the screenshot goes (an absolute path is safest)
#   --wait S         seconds of play before the screenshot (default 15)
#   --godot-arg ARG  extra user argument for the game (after --), e.g. --godot-arg --zoom --godot-arg 2
#   SERVER ARGS      passed to `python -m theroadragetrip.server`, e.g.
#                    --preset Helsinki --start-time 2026-09-27T00:30 --no-historical-weather
#
# The server's log is written next to the screenshot (OUT.png.log). The
# server is stopped by its own PID - never by a pattern, which can match
# the calling shell.
set -u
if [ $# -lt 1 ]; then
  sed -n '2,13p' "$0"
  exit 2
fi
out=$1; shift
wait_s=15
godot_args=()
server_args=()
while [ $# -gt 0 ]; do
  case "$1" in
    --wait) wait_s=$2; shift 2 ;;
    --godot-arg) godot_args+=("$2"); shift 2 ;;
    *) server_args+=("$1"); shift ;;
  esac
done

repo=$(cd "$(dirname "$0")/../../.." && pwd)
godot=${GODOT:-$(ls "$HOME"/tools/godot/Godot_v*-stable_linux.x86_64 2>/dev/null | sort | tail -1)}
if [ ! -x "$godot" ]; then
  echo "Godot binary not found (set GODOT=/path/to/godot)" >&2
  exit 1
fi
# A free port, so a running game or another shot is never disturbed.
port=$("$repo/.venv/bin/python" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')

mkdir -p "$(dirname "$out")"
rm -f "$out"
cd "$repo"
PYTHONPATH=src .venv/bin/python -m theroadragetrip.server --port "$port" "${server_args[@]}" > "$out.log" 2>&1 &
server=$!
trap 'kill "$server" 2>/dev/null; wait "$server" 2>/dev/null' EXIT

if ! .venv/bin/python tools/wait_for_port.py 127.0.0.1 "$port" 300; then
  echo "The server did not start; its log: $out.log" >&2
  tail -20 "$out.log" >&2
  exit 1
fi
timeout $((wait_s + 120)) "$godot" --path godot --display-driver x11 --rendering-driver opengl3 \
  -- --port "$port" --screenshot "$out" --screenshot-wait "$wait_s" "${godot_args[@]}" 2>&1 \
  | grep -E "SCRIPT ERROR|Parse Error|screenshot saved" >&2

if [ -f "$out" ]; then
  echo "$out"
else
  echo "No screenshot was saved; server log: $out.log" >&2
  exit 1
fi
