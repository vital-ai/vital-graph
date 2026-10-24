#!/bin/sh
# Verify profile K on the local cluster, then drill a failover.
#   1. the plugin and the extensions are loaded from their image volumes
#   2. the rendered parameters are in force
#   3. a synchronous standby in the other zone
#   4. the plugin applies advice (a vg:plan statement reports its items)
#   5. FAILOVER: a committed row survives deleting the primary pod; the new
#      primary has the plugin; time to a writable primary
set -e
NS=vitalgraph-db; CL=vitalgraph-pg
primary() { kubectl -n $NS get cluster $CL -o jsonpath='{.status.currentPrimary}'; }
psql_on() { kubectl -n $NS exec "$1" -c postgres -- psql -X -At -d sparql_sql_graph -c "$2"; }
fail=0; check() { if [ "$2" = "$3" ]; then echo "  PASS  $1"; else echo "  FAIL  $1: got [$2] want [$3]"; fail=1; fi; }

P="$(primary)"; echo "primary: $P"
echo "1. extensions"
check "vg_planner loaded with hooks" "$(psql_on "$P" "SELECT vg_planner_info() LIKE '%hooks=installed%'")" "t"
check "shared_preload_libraries" "$(psql_on "$P" "SHOW shared_preload_libraries")" "pg_stat_statements,pg_prewarm,vg_planner"
check "extensions created" "$(psql_on "$P" "SELECT string_agg(extname, ',' ORDER BY extname) FROM pg_extension WHERE extname <> 'plpgsql'")" \
      "pg_prewarm,pg_stat_statements,pg_trgm,pgcrypto,postgis,vector,vg_planner"
echo "   versions: $(psql_on "$P" "SELECT string_agg(extname || ' ' || extversion, ', ' ORDER BY extname) FROM pg_extension")"
check "vg_planner library from its image volume" \
      "$(psql_on "$P" "SHOW dynamic_library_path" | grep -c '/extensions/vg_planner/lib')" "1"
echo "2. parameters"
check "shared_buffers" "$(psql_on "$P" "SHOW shared_buffers")" "512MB"
check "app role statement_timeout" "$(psql_on "$P" "SELECT setconfig FROM pg_db_role_setting s JOIN pg_roles r ON r.oid = s.setrole WHERE r.rolname = 'vitalgraph_user'")" "{statement_timeout=60s}"
echo "3. synchronous standby"
check "one sync standby streaming" "$(psql_on "$P" "SELECT count(*) FROM pg_stat_replication WHERE state = 'streaming' AND sync_state IN ('sync','quorum')")" "1"
zones="$(kubectl -n $NS get pods -l cnpg.io/cluster=$CL -o jsonpath='{range .items[*]}{.spec.nodeName}{"\n"}{end}' \
  | xargs -I{} kubectl get node {} -o jsonpath='{.metadata.labels.topology\.kubernetes\.io/zone}{"\n"}' | sort -u | wc -l | tr -d ' ')"
check "instances in two zones" "$zones" "2"
echo "4. advice applied"
psql_on "$P" "CREATE TABLE IF NOT EXISTS vgp_t1 (a int, b int); CREATE TABLE IF NOT EXISTS vgp_t2 (a int, b int);" >/dev/null
psql_on "$P" "/*vg:plan 1
size k0 1234 x y
*/ EXPLAIN SELECT 1 FROM vgp_t1 x JOIN vgp_t2 y ON x.a = y.a" >/dev/null
check "size item applied" "$(psql_on "$P" "SELECT vg_planner_last_report()" | grep -c 'k0.*applied')" "1"
psql_on "$P" "DROP TABLE vgp_t1, vgp_t2" >/dev/null
echo "5. failover"
psql_on "$P" "CREATE TABLE IF NOT EXISTS vgp_failover (id int, at timestamptz DEFAULT now()); INSERT INTO vgp_failover VALUES (1)" >/dev/null
t0=$(date +%s)
kubectl -n $NS delete pod "$P" --wait=false >/dev/null
while :; do
  N="$(primary)"
  if [ -n "$N" ] && [ "$N" != "$P" ] && psql_on "$N" "INSERT INTO vgp_failover VALUES (2)" >/dev/null 2>&1; then break; fi
  [ $(( $(date +%s) - t0 )) -gt 300 ] && { echo "  FAIL  no writable primary within 300 s"; exit 1; }
  sleep 1
done
echo "   new primary $N writable after $(( $(date +%s) - t0 )) s"
check "the committed row survived" "$(psql_on "$N" "SELECT count(*) FROM vgp_failover WHERE id = 1")" "1"
check "plugin on the new primary" "$(psql_on "$N" "SELECT vg_planner_info() LIKE '%hooks=installed%'")" "t"
kubectl -n $NS wait cluster/$CL --for=condition=Ready --timeout=10m >/dev/null
check "old primary back as a standby" "$(psql_on "$N" "SELECT count(*) FROM pg_stat_replication WHERE state = 'streaming'")" "1"
psql_on "$N" "DROP TABLE vgp_failover" >/dev/null
[ $fail -eq 0 ] && echo "ALL PASS" || { echo "FAILURES"; exit 1; }
