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
| `manifests/base/` | the `Cluster`: 2 instances, one per zone, synchronous commit to the standby (`dataDurability: preferred`, as RDS Multi-AZ keeps writing while it replaces a standby), switchover-first updates, `vg_planner` + pgvector + PostGIS image volumes, bootstrap SQL (role and database settings, extensions) |
| `manifests/overlays/eks/` | production shape: EKS Auto Mode node pool (Graviton r7g/r8g.2xlarge, tainted), gp3 with 12,000 IOPS / 500 MiB/s, Barman Cloud backups to S3 with an IAM role, an internal NLB for the ECS app. **Every AWS value is a `REPLACE_ME` placeholder; nothing has been applied.** |
| `manifests/overlays/local-kind/` | the same Cluster, small, for a local kind cluster |
| `local/` | `kind-config.yaml` (two workers in two zones), `up.sh` (cluster, operator 1.30.1, images, overlay), `verify.sh` (extensions, parameters, standby, advice applied, a failover drill) |

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
