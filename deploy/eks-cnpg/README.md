# Profile K: VitalGraph's PostgreSQL on EKS with CloudNativePG

A self-managed PostgreSQL 18.4 that can load the `vg_planner` extension
(`pg_extensions/vg_planner`), which managed RDS cannot. CloudNativePG does what
RDS does for us: failover to a synchronous standby in another zone, backups and
WAL to S3 with point-in-time restore, rolling updates by switchover, TLS, and
declarative configuration.

The configuration itself is shared with the EC2 profile and lives in
`deploy/postgres/` (`postgresql.vitalgraph.yaml` + `render_config.py`). Edit it
there, then run `render_all.sh`; `render_all.sh --check` fails when a manifest
was edited instead.

| path | what |
|---|---|
| `images/vg-planner/` | the extension as a CloudNativePG **image volume**: built and regression-tested inside the 18.4 operand image, a `FROM scratch` image with `lib/`, `share/extension/` and `BUILD-INFO` |
| `manifests/base/` | the `Cluster`: 2 instances, one per zone, synchronous commit to the standby (`dataDurability: preferred`, as RDS Multi-AZ keeps writing while it replaces a standby), switchover-first updates, `vg_planner` + pgvector + PostGIS image volumes, bootstrap SQL (role and database settings, extensions); the PgBouncer `Pooler` every client connects through (below) |
| `manifests/overlays/eks/` | production shape: EKS Auto Mode node pool (Graviton r7g/r8g.2xlarge, tainted), gp3 with 12,000 IOPS / 500 MiB/s, Barman Cloud backups to S3 with an IAM role, the internal NLB for the ECS app **in front of the pooler** (`pooler-eks.yaml`). **Every AWS value is a `REPLACE_ME` placeholder; nothing has been applied.** |
| `manifests/overlays/local-kind/` | the same Cluster and pooler, small, for a local kind cluster; the pooler on `localhost:5443` |
| `local/` | `kind-config.yaml` (two workers in two zones, the pooler's port), `up.sh` (cluster, operator 1.30.1, images, overlay), `verify.sh` (extensions, parameters, standby, advice applied, a failover drill, the pooler, TLS only, a switchover drill through the pooler) |

## Clients connect through the pooler

The app on ECS, its maintenance job and operator scripts connect to a PgBouncer
`Pooler` (`manifests/base/pooler.yaml`), never to the primary. The internal NLB
points at the pooler.

**Why.** On a switchover the old primary is demoted in place. An NLB pointed
at the primary keeps sending new connections to it for ~30 s, and each one
fails with `read-only transaction` (SQLSTATE 25006). That was measured on AWS,
and reproduced on kind with a Service that follows the primary 30 s late: 27
such errors in 30 s. The pooler's pods never change role, so the NLB's lag no
longer matters, and PgBouncer reaches the primary through the operator's rw
Service, which follows it at once.

| probe: a fresh connection + INSERT every 0.5 s, switchover in the middle | read-only errors | refused connections |
|---|---:|---:|
| straight to the primary, behind an address that lags 30 s | 27 | the 30 s window |
| through the pooler, default settings | 0 | 17.8 s |
| through the pooler, `server_login_retry` 1 s | 0 | 3-8 s |

**Settings that matter:**
* `poolMode: session`. VitalGraph needs session state: the signal listener
  holds LISTEN, SPARQL updates take `pg_advisory_xact_lock`, asyncpg caches
  prepared statements per connection, and the executor uses `SET LOCAL`.
  Transaction pooling would break these.
* `server_login_retry: 1`. After one failed server login PgBouncer refuses new
  clients for this long. The 15 s default doubled the switchover outage.
* `client_tls_sslmode: require`. Without it PgBouncer accepts plain
  connections even though the database refuses them. Set `PGSSLMODE=require`
  on the app task as well: asyncpg's default `prefer` would otherwise allow a
  fallback to plain text.
* `default_pool_size` (per overlay; 150 on EKS). In session mode each client
  connection holds a server connection, and the limit is per pooler pod.
  Size it for a rolling deploy, when old and new tasks run together and the
  NLB may send most of them to one pod: tasks x (`DB_POOL_SIZE` +
  `DB_INTERNAL_POOL_SIZE` + LISTEN connections) at the peak, with margin,
  under `max_connections`.
* `query_wait_timeout: 20`. A client that finds the pool full fails after
  20 s, instead of waiting PgBouncer's default 120 s.
* TCP keepalives (`tcp_keepidle` 60, `tcp_keepintvl` 10, `tcp_keepcnt` 6).
  LISTEN-only connections sit idle for hours. Past the NLB's idle timeout
  the flow is dropped without notice, and without probes PgBouncer holds
  that session's server slot for over 2 hours.
* `application_name_add_host: 1`. The server sees PgBouncer's address; this
  puts the client's address in `application_name` for `pg_stat_activity`.
* Two pooler pods, one per zone and never on one node (`DoNotSchedule` plus
  required anti-affinity), on the database nodes. Memory 128Mi requested
  and limited, so they are not the first evicted; CPU 250m requested, up to
  one CPU, because PgBouncer is single-threaded and does TLS on both sides
  (a 0.1 CPU limit throttles it). A PodDisruptionBudget of
  `minAvailable: 1` (the operator creates PDBs for the instances, not for a
  Pooler). Rollouts never surge (`maxSurge: 0, maxUnavailable: 1`): a surge
  pod would need a third database node. On EKS the NLB is cross-zone,
  health-checked every 5 s, with a 10 s deregistration delay and a 3,600 s
  idle timeout, because pooled connections live long.
* **Session settings go in a `SET` after connecting, never in startup
  parameters.** PgBouncer drops libpq's `options` (the operator always lists
  it in `ignore_startup_parameters`) and refuses any other parameter it does
  not track, such as asyncpg's `server_settings`. A session-level `SET`
  holds in session mode. VitalGraph's maintenance connections and scripts do
  this; any other client must too.
* TLS: the pooler presents the cluster's server certificate. The app uses
  `PGSSLMODE=require`. A client that wants `verify-full` against the NLB's
  name needs that name in the Cluster's `certificates.serverAltDNSNames`.
* Latency: one more hop, NLB to PgBouncer to the primary, which can cross
  zones twice.

On a switchover the signal listener's session is closed, as a direct
connection's would be, and it reconnects.

`local/verify.sh` drills it. It runs a switchover (by patching the Cluster's
`status.targetPrimary`, no plugin needed) while a probe connects and writes
every 0.5 s through the pooler, and it FAILS on any read-only error.

## Local

    docker build -f deploy/eks-cnpg/images/vg-planner/Dockerfile -t vg-planner-ext:0.2.0-18.4-trixie .
    deploy/eks-cnpg/local/up.sh
    deploy/eks-cnpg/local/verify.sh
    kind delete cluster --name vg-cnpg

Needs kind (Kubernetes >= 1.35 for ImageVolume; kind 0.33 runs 1.37), helm and
kubectl, and a few GB of free memory.

## Upgrading PostgreSQL

`vg_planner` is pinned to a minor: `src/pg18_joinsearch.c` is generated from the
release tag. A minor upgrade is: regenerate it for the new tag, rebuild this
image against the new operand image (the build refuses a mismatch), run the
regression suite and the planner contract corpus, then move `imageName` and the
extension image together.

Planning: `planning/planning_rds/` (local, not in the repository).
