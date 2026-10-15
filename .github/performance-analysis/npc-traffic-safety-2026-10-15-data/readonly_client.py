"""Read-only trace/episode collector; run alongside observe_npc_traffic.py."""
import sys
import gzip
import json
from pathlib import Path
import socket
import time
from datetime import datetime, timezone

out = Path(sys.argv[1] if len(sys.argv) > 1 else '/tmp/rrt-traffic-observation-2026-10-15')
meta = json.loads((out / 'metadata.json').read_text())
origin = datetime.fromisoformat(meta['started_utc']).timestamp()
sock = socket.create_connection(('127.0.0.1', meta['port']), timeout=3)
sock.settimeout(3)
buffer = b''
next_sample = 0
episodes = {}
finished = []
samples = 0
first_t = None
with gzip.open(out / 'client-trace.jsonl.gz', 'wt') as trace:
    try:
        while True:
            data = sock.recv(1 << 20)
            if not data:
                break
            *lines, buffer = (buffer + data).split(b'\n')
            for line in lines:
                if not line.startswith(b'{"type":"state"'):
                    continue
                now = time.time() - origin
                if now < next_sample:
                    continue
                next_sample = now + 1
                message = json.loads(line)
                state = message.get('state', message)
                first_t = now if first_t is None else first_t
                rows = []
                seen = set()
                for kind, objects in [('npc', state['npcs']), ('pedestrian', state['pedestrians'])]:
                    for obj in objects:
                        row = {key: obj.get(key) for key in ('id','x','y','heading','speed','state','debug_waiting_for','layer','is_cyclist')}
                        row['kind'] = kind
                        rows.append(row)
                        key = f'{kind}:{obj["id"]}'
                        seen.add(key)
                        active = episodes.get(key)
                        stationary = active is not None and (obj['x']-active['start_pose']['x'])**2+(obj['y']-active['start_pose']['y'])**2 < 4
                        if active is not None and not stationary:
                            if now-active['start_s'] >= 30:
                                finished.append(active)
                            active = None
                        if active is None:
                            active = {'entity': key, 'start_s': now, 'start_pose': row, 'samples': 0, 'states': {}, 'reasons': {}}
                            episodes[key] = active
                        active['last_s'] = now
                        active['last_pose'] = row
                        active['samples'] += 1
                        for target, value in [('states', row['state']), ('reasons', row.get('debug_waiting_for') or '')]:
                            active[target][str(value)] = active[target].get(str(value), 0)+1
                for key in list(episodes):
                    if key not in seen:
                        active = episodes.pop(key)
                        if active['last_s']-active['start_s'] >= 30:
                            finished.append(active)
                trace.write(json.dumps({'t': now, 'entities': rows})+'\n')
                samples += 1
    except (TimeoutError, ConnectionError):
        pass
sock.close()
for active in episodes.values():
    if active['last_s']-active['start_s'] >= 30:
        finished.append(active)
for active in finished:
    active['duration_s'] = active['last_s']-active['start_s']
finished.sort(key=lambda e: e['duration_s'], reverse=True)
(out / 'client-episodes.json').write_text(json.dumps({'samples': samples, 'first_s': first_t, 'last_s': time.time()-origin, 'episodes': finished}, indent=2))
print('CLIENT_DONE',samples,'episodes',len(finished),flush=True)
