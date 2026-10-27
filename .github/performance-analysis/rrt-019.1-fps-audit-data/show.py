import json,sys
d=json.loads([l for l in open(sys.argv[1]) if l.startswith('{')][0]); n=d['frames']['frames']
print('avg %.1f ms p95 %.1f frames %d draw_calls %s'%(d['frames']['avg_ms'],d['frames']['p95_ms'],n,d['counters'].get('draw_calls')))
for k,v in sorted(d['sections'].items(), key=lambda kv:-kv[1]['total_ms'])[:int(sys.argv[2]) if len(sys.argv)>2 else 25]:
  print('  %-46s n/frame %-7.1f avg %.3f  ms/frame %.2f'%(k,v['count']/n,v['avg_ms'],v['total_ms']/n))
print('draw_z total ms/frame %.2f'%(sum(v['total_ms'] for k,v in d['sections'].items() if k.startswith('draw_z'))/n))
