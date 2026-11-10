#!/bin/sh
# Verify profile K on the local cluster, then drill a failover.
#   1. the plugin and the extensions are loaded from their image volumes
#   2. the rendered parameters are in force
#   3. a synchronous standby in the other zone
#   4. the plugin applies advice (a vg:plan statement reports its items)
#   5. FAILOVER: a committed row survives deleting the primary pod; the new
#      primary has the plugin; time to a writable primary; the pooler's address
#      follows it
#   6. the pooler: two PgBouncer pods, session mode, server_login_retry 1 s
#   7. TLS only through the pooler (localhost:5443 here, the NLB on EKS): a client
#      without TLS is refused; with TLS it connects as the app role
#   8. SWITCHOVER through the pooler: a fresh connection and INSERT every 0.5 s from
#      outside the cluster; no "read-only transaction" (25006) error, and the
#      outage reported
# On another cluster built from these manifests: LOCAL_PORT= skips 5, 7 and 8's
# client side (no local port), and EXPECT_SHARED_BUFFERS sets the expected size.
set -e
NS=vitalgraph-db; CL=vitalgraph-pg; POOLER=vitalgraph-pg-pooler-rw
LOCAL_PORT="${LOCAL_PORT-5443}"
EXPECT_SHARED_BUFFERS="${EXPECT_SHARED_BUFFERS:-512MB}"
# The app role's password: CloudNativePG's generated secret for the database owner.
PW="$(kubectl -n $NS get secret ${CL}-app -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null || true)"
pooler_conn() { echo "host=127.0.0.1 port=$LOCAL_PORT dbname=sparql_sql_graph user=vitalgraph_user sslmode=${1:-require} connect_timeout=${2:-5}"; }
have_client() { [ -n "$LOCAL_PORT" ] && [ -n "$PW" ] && command -v psql >/dev/null; }
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
check "shared_buffers" "$(psql_on "$P" "SHOW shared_buffers")" "$EXPECT_SHARED_BUFFERS"
check "app role statement_timeout" "$(psql_on "$P" "SELECT setconfig FROM pg_db_role_setting s JOIN pg_roles r ON r.oid = s.setrole WHERE r.rolname = 'vitalgraph_user'")" "{statement_timeout=60s}"
echo "3. synchronous standby"
check "one sync standby streaming" "$(psql_on "$P" "SELECT count(*) FROM pg_stat_replication WHERE state = 'streaming' AND sync_state IN ('sync','quorum')")" "1"
zones="$(kubectl -n $NS get pods -l cnpg.io/cluster=$CL,cnpg.io/podRole=instance -o jsonpath='{range .items[*]}{.spec.nodeName}{"\n"}{end}' \
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
if have_client; then
  check "the pooler's address follows it" "$(PGPASSWORD="$PW" psql -X -At "$(pooler_conn)" -c 'select not pg_is_in_recovery()')" "t"
fi
kubectl -n $NS wait cluster/$CL --for=condition=Ready --timeout=10m >/dev/null
check "old primary back as a standby" "$(psql_on "$N" "SELECT count(*) FROM pg_stat_replication WHERE state = 'streaming'")" "1"
psql_on "$N" "DROP TABLE vgp_failover" >/dev/null

echo "6. the pooler"
check "two PgBouncer pods ready" "$(kubectl -n $NS get deployment $POOLER -o jsonpath='{.status.readyReplicas}')" "2"
check "session mode" "$(kubectl -n $NS get pooler $POOLER -o jsonpath='{.spec.pgbouncer.poolMode}')" "session"
check "server_login_retry 1 s" "$(kubectl -n $NS get pooler $POOLER -o jsonpath='{.spec.pgbouncer.parameters.server_login_retry}')" "1"
check "client TLS required" "$(kubectl -n $NS get pooler $POOLER -o jsonpath='{.spec.pgbouncer.parameters.client_tls_sslmode}')" "require"

if have_client; then
  echo "7. TLS only, through the pooler on localhost:$LOCAL_PORT"
  check "without TLS: refused" "$(PGPASSWORD="$PW" psql -X -At "$(pooler_conn disable)" -c 'select 1' 2>&1 | grep -c 'no encryption\|reject\|SSL required\|SSL\|TLS')" "1"
  check "with TLS: connects as the app role" "$(PGPASSWORD="$PW" psql -X -At "$(pooler_conn)" -c 'select current_user')" "vitalgraph_user"

  echo "8. switchover through the pooler"
  conn="$(pooler_conn require 2)"
  PGPASSWORD="$PW" psql -X -At "$conn" -c "CREATE TABLE IF NOT EXISTS vgp_switchover (at timestamptz)" >/dev/null
  log="$(mktemp)"
  ( end=$(( $(date +%s) + 60 )); while [ $(date +%s) -lt $end ]; do
      PGPASSWORD="$PW" psql -X -At "$conn" -c "INSERT INTO vgp_switchover VALUES (now()) RETURNING 'ok'" 2>&1 | head -1 >> "$log"; sleep 0.5
    done ) &
  probe=$!; sleep 10
  # A switchover is the operator acting on status.targetPrimary (what `kubectl cnpg
  # promote` sets), so no plugin is needed.
  T="$(kubectl -n $NS get pods -l cnpg.io/cluster=$CL,cnpg.io/instanceRole=replica -o jsonpath='{.items[0].metadata.name}')"
  kubectl -n $NS patch cluster $CL --subresource=status --type=merge \
    -p "{\"status\":{\"targetPrimary\":\"$T\",\"targetPrimaryTimestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}}" >/dev/null
  wait $probe
  total=$(wc -l < "$log" | tr -d ' '); failed=$(grep -vc '^ok$' "$log" || true)
  echo "   switchover to $T: $failed of $total attempts failed (about $(( failed / 2 )) s)"
  check "no read-only (25006) errors" "$(grep -c 'read-only' "$log" || true)" "0"
  check "writing again at the end" "$(tail -1 "$log")" "ok"
  check "the new primary is $T" "$(primary)" "$T"
  rm -f "$log"; kubectl -n $NS wait cluster/$CL --for=condition=Ready --timeout=10m >/dev/null
  PGPASSWORD="$PW" psql -X -At "$conn" -c "DROP TABLE vgp_switchover" >/dev/null
else
  echo "7-8. skipped: needs psql, LOCAL_PORT and the ${CL}-app secret"
fi
[ $fail -eq 0 ] && echo "ALL PASS" || { echo "FAILURES"; exit 1; }
