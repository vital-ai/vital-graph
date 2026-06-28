#!/bin/bash
# Live tail of important log events (stalls, GC, locks, errors)
# Usage: ./tail_live.sh

docker logs vitalgraph-app --follow --since "1m" 2>&1 | grep -E "EVENT LOOP STALL|GC PAUSE|GC:.*took|Lock held|Lock acquired.*wait|ERROR|500 Internal|mismatch|FRAME_UPDATE total"
