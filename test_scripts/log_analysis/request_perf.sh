#!/bin/bash
# Analyze per-endpoint response times from access logs
# Usage: ./request_perf.sh [--since TIME]  (default: last 5 minutes)

SINCE="${2:-5m}"
if [ "$1" = "--since" ] && [ -n "$2" ]; then
    SINCE="$2"
fi

docker logs vitalgraph-app --since "$SINCE" 2>&1 | python3 -c "
import sys, re
from collections import defaultdict

lines = sys.stdin.readlines()

# Parse request timestamps and match with response times
# Look for lines like: 'INFO: 172.67.186.1:23987 - \"POST /api/graphs/kgentities/kgframes?...&operation_mode=update HTTP/1.1\" 200 OK'
# And preceding timing lines

# Classify requests by endpoint type
endpoint_times = defaultdict(list)

for i, line in enumerate(lines):
    # Match access log lines
    m = re.search(r'\"(GET|POST|PUT|DELETE) ([^\?\"]+)(\?[^\"]*)? HTTP/1\.1\" (\d+)', line)
    if not m:
        continue
    method = m.group(1)
    path = m.group(2).strip()
    query = m.group(3) or ''
    status = m.group(4)

    # Classify endpoint
    if 'kgframes' in path and method == 'POST':
        mode = re.search(r'operation_mode=(\w+)', query)
        mode_str = mode.group(1).upper() if mode else 'CREATE'
        key = f'/kgframes [{mode_str}]'
    elif 'kgentities' in path and method == 'GET':
        if 'include_entity_graph=true' in query.lower():
            key = '/api/kgentities [GET+GRAPH]'
        else:
            # Check for list vs single entity
            if re.search(r'page_size=', query):
                key = '/api/kgentities [LIST]'
            else:
                key = '/api/kgentities [GET]'
    elif 'kgentities' in path and method == 'POST':
        key = f'/api/kgentities [POST]'
    elif 'kgentities' in path and method == 'PUT':
        key = f'/api/kgentities [PUT]'
    elif 'kgentities' in path and method == 'DELETE':
        key = f'/api/kgentities [DELETE]'
    else:
        key = f'{path} [{method}]'

    # Look for timing in nearby preceding lines (within 5 lines)
    timing = None
    for j in range(max(0, i-5), i):
        tm = re.search(r'FRAME_UPDATE total: (\d+\.\d+)s', lines[j])
        if tm:
            timing = float(tm.group(1)) * 1000
            break

    endpoint_times[key].append({'status': status, 'timing_ms': timing})

print('=== Endpoint Summary ===')
print(f'{\"Endpoint\":<35} {\"Count\":>6} {\"2xx\":>5} {\"4xx\":>5} {\"5xx\":>5}')
print('-' * 60)
for key in sorted(endpoint_times, key=lambda x: -len(endpoint_times[x])):
    entries = endpoint_times[key]
    count = len(entries)
    s2 = sum(1 for e in entries if e['status'].startswith('2'))
    s4 = sum(1 for e in entries if e['status'].startswith('4'))
    s5 = sum(1 for e in entries if e['status'].startswith('5'))
    print(f'{key:<35} {count:>6} {s2:>5} {s4:>5} {s5:>5}')

# Frame update timing breakdown
print()
for key in sorted(endpoint_times):
    timings = [e['timing_ms'] for e in endpoint_times[key] if e['timing_ms'] is not None]
    if timings:
        s = sorted(timings)
        print(f'{key}: n={len(s)}  min={min(s):.0f}ms  med={s[len(s)//2]:.0f}ms  avg={sum(s)/len(s):.0f}ms  p90={s[int(len(s)*0.9)]:.0f}ms  max={max(s):.0f}ms')
"
