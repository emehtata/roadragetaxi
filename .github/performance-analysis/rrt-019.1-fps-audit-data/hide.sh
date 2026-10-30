for v in "$@"; do $(dirname "$0")/bench.sh $(dirname "$0")/h.json 1 --bench ${BENCH_S:-15} --bench-hide $v >/dev/null 2>&1; python3 -c "
import json;d=json.loads([l for l in open('$(dirname "$0")/h.json') if l.startswith('{')][0]);s=d['sections']
print('%-34s %.1f ms  dc %d  pre-render %.1f  render %.1f'%('$v',d['frames']['avg_ms'],d['counters']['draw_calls'],s['phase_process_to_render']['avg_ms'],s['phase_render']['avg_ms']))"; done
