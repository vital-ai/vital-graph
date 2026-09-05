#!/usr/bin/env bash
# issues/163: does adding context_uuid to the rdf_stats GROUP BY change the
# number of stored rows? For a single-graph space it must not.
PSQL="docker exec vitalgraph-test-pg psql -U postgres -d sparql_sql_graph -Atc"
printf "  %-24s %7s %12s %12s  %s\n" space graphs "pairs (p,o)" "(p,o,ctx)" delta
for s in "$@"; do
  r=$($PSQL "
SELECT (SELECT count(DISTINCT context_uuid) FROM ${s}_rdf_quad)
   ||E'\t'||(SELECT count(*) FROM (SELECT 1 FROM ${s}_rdf_quad GROUP BY predicate_uuid,object_uuid HAVING count(*)>=2) x)
   ||E'\t'||(SELECT count(*) FROM (SELECT 1 FROM ${s}_rdf_quad GROUP BY predicate_uuid,object_uuid,context_uuid HAVING count(*)>=2) y)
" 2>/dev/null)
  [ -z "$r" ] && { printf "  %-24s  (failed)\n" "$s"; continue; }
  echo "$s	$r" | awk -F'\t' '{d=$4-$3; printf "  %-24s %7s %12s %12s  %+d%s\n",$1,$2,$3,$4,d,(d==0?"   IDENTICAL":"")}'
done
