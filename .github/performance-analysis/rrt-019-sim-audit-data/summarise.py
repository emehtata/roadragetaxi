"""Print bench_sim.py result JSONs as a compact table: summarise.py raw/*.json"""
import json
import sys

for path in sys.argv[1:]:
    d = json.load(open(path))
    w, c = d["wall_ms"], d["counts_mean"]
    print(f"\n== {path}")
    print(f"tick ms p50 {w['p50']:.2f} p95 {w['p95']:.2f} p99 {w['p99']:.2f} max {w['max']:.1f} | "
          f"mean wall {d['wall_mean_ms']:.2f} cpu {d['cpu_mean_ms']:.2f} | >33ms {d['over_budget_pct']:.2f}% "
          f">16.7ms {d['over_half_budget_pct']:.2f}%")
    print(f"encode mean {d['encode_ms']['mean']:.2f} max {d['encode_ms']['max']:.2f} ms, state {d['state_bytes']['mean'] / 1024:.1f} KiB "
          f"(max {d['state_bytes']['max'] / 1024:.1f}) | rss {d['rss_mb'][0]:.0f}->{d['rss_mb'][1]:.0f} MB | "
          f"gc objs {d['gc_objects'][0]}->{d['gc_objects'][1]}")
    print("counts mean " + ", ".join(f"{k} {v:.1f}" for k, v in c.items()))
    print("gc " + " ".join(f"g{g}: n={v['count']} tot={v['total_ms']:.0f}ms max={v['max_ms']:.1f}" for g, v in d["gc"].items()))
    for k, v in sorted(d["sections_mean_ms"].items(), key=lambda kv: -kv[1]):
        if v >= 0.01 or d["sections_max_ms"][k] >= 1:
            print(f"   {k:38s} mean {v:7.3f}  max {d['sections_max_ms'][k]:7.2f}")
    for x in d["worst"][:4]:
        print(f"   worst {x['wall_ms']:.1f} ms (cpu {x['cpu_ms']:.1f}) gc {[(g, round(t * 1000, 1)) for g, t in x['gc']]} {x['sec_ms']}")
