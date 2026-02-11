#!/bin/bash
# Show event loop stalls and GC pauses only
# Usage: ./stalls_only.sh [--since TIME]  (default: last 5 minutes)

SINCE="${2:-5m}"
if [ "$1" = "--since" ] && [ -n "$2" ]; then
    SINCE="$2"
fi

docker logs vitalgraph-app --since "$SINCE" 2>&1 | grep -E "EVENT LOOP STALL|GC PAUSE|GC:.*took"
