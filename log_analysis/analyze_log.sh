#!/bin/bash
# Full docker log analysis: requests, frame updates, stalls, GC, locking, errors
# Usage: ./analyze_log.sh [--since TIME]  (default: last 5 minutes)

SINCE="${2:-5m}"
if [ "$1" = "--since" ] && [ -n "$2" ]; then
    SINCE="$2"
fi

docker logs vitalgraph-app --since "$SINCE" 2>&1 | python3 -c "
import sys, re
from collections import defaultdict, Counter

lines = sys.stdin.readlines()

# --- Requests ---
req_counts = defaultdict(lambda: {'count': 0, 'statuses': defaultdict(int)})
for line in lines:
    m = re.search(r'\"(GET|POST|PUT|DELETE) ([^\?\"]+)', line)
    s = re.search(r'HTTP/1\.1\" (\d+)', line)
    if m and s:
        key = f'{m.group(1)} {m.group(2).strip()}'
        req_counts[key]['count'] += 1
        req_counts[key]['statuses'][s.group(1)] += 1

total = sum(v['count'] for v in req_counts.values())
print(f'=== Requests: {total} total ===')
for k in sorted(req_counts, key=lambda x: -req_counts[x]['count']):
    c = req_counts[k]
    status_str = ', '.join(f'{s}:{n}' for s,n in sorted(c['statuses'].items()))
    print(f'  {c[\"count\"]:5d}  {k}  [{status_str}]')

# --- Frame Updates ---
fu = []
for line in lines:
    m = re.search(r'FRAME_UPDATE total: (\d+\.\d+)s', line)
    if m: fu.append(float(m.group(1)))
if fu:
    s = sorted(fu)
    p90 = s[int(len(s)*0.9)]
    p95 = s[int(len(s)*0.95)]
    print(f'\n=== Frame Updates: {len(s)} ===')
    print(f'  Min={min(s)*1000:.0f}ms  Med={s[len(s)//2]*1000:.0f}ms  Avg={sum(s)/len(s)*1000:.0f}ms  p90={p90*1000:.0f}ms  p95={p95*1000:.0f}ms  Max={max(s)*1000:.0f}ms')

# --- Lock contention ---
lock_held = []
for line in lines:
    m = re.search(r'Lock held.*for (\d+)ms', line)
    if m: lock_held.append(int(m.group(1)))
if lock_held:
    print(f'\n=== Lock contention (>100ms holds): {len(lock_held)} ===')
    for lh in sorted(lock_held, reverse=True)[:10]:
        print(f'    {lh}ms')

# --- Event loop stalls ---
stalls = []
for line in lines:
    m = re.search(r'EVENT LOOP STALL.*blocked for (\d+)ms', line)
    if m: stalls.append(int(m.group(1)))
print(f'\n=== Event Loop Stalls: {len(stalls)} ===')
if stalls:
    for st in sorted(stalls, reverse=True)[:10]:
        print(f'    {st}ms')

# --- GC pauses (>100ms) ---
gc_pauses = []
for line in lines:
    m = re.search(r'GC PAUSE: gen(\d+) took (\d+)ms.*collected=(\d+)', line)
    if m: gc_pauses.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
print(f'\n=== GC Pauses (>100ms): {len(gc_pauses)} ===')
for gen, dur, coll in sorted(gc_pauses, key=lambda x: -x[1]):
    print(f'    gen{gen}: {dur}ms ({coll} objects)')

# --- GC minor (10-100ms) ---
gc_minor = []
for line in lines:
    m = re.search(r'GC: gen(\d+) took (\d+\.\d+)ms.*collected=(\d+)', line)
    if m: gc_minor.append((int(m.group(1)), float(m.group(2)), int(m.group(3))))
if gc_minor:
    print(f'\n=== GC Minor (10-100ms): {len(gc_minor)} ===')
    for gen, dur, coll in sorted(gc_minor, key=lambda x: -x[1])[:10]:
        print(f'    gen{gen}: {dur:.1f}ms ({coll} objects)')

# --- Duplicate deletes (race condition indicator) ---
deletes = []
for line in lines:
    m = re.search(r'FUSEKI_DELETE.*hasTextSlotValue.*\"(LoadTest_\w+)\"', line)
    if m: deletes.append(m.group(1))
dups = {k: v for k, v in Counter(deletes).items() if v > 1}
print(f'\n=== Duplicate Deletes (race condition): {len(dups)} ===')
for val, cnt in dups.items():
    print(f'    {val}: deleted {cnt} times')

# --- Errors ---
errs = [l.strip() for l in lines if re.search(r'(ERROR|Traceback|500 Internal)', l)]
print(f'\n=== Errors: {len(errs)} ===')
for e in errs[:10]:
    print(f'    {e[:120]}')
"
