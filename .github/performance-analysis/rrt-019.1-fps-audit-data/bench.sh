#!/usr/bin/env bash
# usage: bench.sh OUT.json RAIN(0|1) [godot user args...]
set -u
out=$1; rain=$2; shift 2
repo=/home/ubuntu/work/roadragetaxi
S=$(cd "$(dirname "$0")" && pwd)
port=$("$repo/.venv/bin/python" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
cd "$repo"
RRT_RAIN=$rain PYTHONPATH=src .venv/bin/python $S/rainserver.py --port "$port" --preset Oulu --start-time ${START:-2026-10-23T22:00} --no-historical-weather --no-intercity-fares > "$out.log" 2>&1 &
server=$!
trap 'kill "$server" 2>/dev/null; wait "$server" 2>/dev/null' EXIT
.venv/bin/python tools/wait_for_port.py 127.0.0.1 "$port" 300 || { tail "$out.log"; exit 1; }
timeout 200 /mnt/c/Godot/Godot_v4.7.2-stable_win64_console.exe --path "$(wslpath -w $repo/godot)" ${GFLAGS:-} -- --port "$port" "$@" 2>&1 | grep -E "^BENCH|SCRIPT ERROR|Using Device" | sed 's/^BENCH //' > "$out"
grep -v "Using Device" "$out" | python3 -c "
import json,sys
d=json.loads(sys.stdin.read()); f=d['frames']; print('avg %.1f ms (%.1f fps) p95 %.1f  draw_calls %s'%(f['avg_ms'],f['avg_fps'],f['p95_ms'],d['counters'].get('draw_calls')))
for k,v in sorted(d['sections'].items(), key=lambda kv:-kv[1]['avg_ms'])[:14]: print('  %-34s %.2f ms'%(k,v['avg_ms']))
"; grep "Using Device" "$out"
