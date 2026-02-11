#!/bin/bash
# Check for race conditions: duplicate FUSEKI deletes of the same value
# Usage: ./race_check.sh [--since TIME]  (default: last 5 minutes)

SINCE="${2:-5m}"
if [ "$1" = "--since" ] && [ -n "$2" ]; then
    SINCE="$2"
fi

docker logs vitalgraph-app --since "$SINCE" 2>&1 | python3 -c "
import sys, re
from collections import Counter

lines = sys.stdin.readlines()

# Find all FUSEKI_DELETE values
deletes = []
for line in lines:
    m = re.search(r'FUSEKI_DELETE.*hasTextSlotValue.*\"(LoadTest_\w+)\"', line)
    if m: deletes.append(m.group(1))

dups = {k: v for k, v in Counter(deletes).items() if v > 1}
if dups:
    print(f'⚠️  RACE CONDITIONS DETECTED: {len(dups)} duplicate deletes')
    for val, cnt in dups.items():
        print(f'    {val}: deleted {cnt} times')
else:
    print(f'✅ No race conditions detected ({len(deletes)} deletes, all unique)')
"
