# Deployment documents

| document | what |
|---|---|
| [`ECS_DEPLOYMENT_GUIDE.md`](ECS_DEPLOYMENT_GUIDE.md) | the application on AWS ECS: configuration, image, sidecar, task definition |
| [`../eks-cnpg/README.md`](../eks-cnpg/README.md) | PostgreSQL on EKS with CloudNativePG, which can load the `vg_planner` extension (RDS cannot) |
| [`RELEASE_DEPLOY_TEMPLATE.md`](RELEASE_DEPLOY_TEMPLATE.md) | how to write a release's deployment document, and the rules every release's steps follow (ordering against the rollout, the app role, timeouts, dry runs, rollback order) |
| [`examples/`](examples/) | releases written to the template; [`release_2026_11_issue293_query_perf.md`](examples/release_2026_11_issue293_query_perf.md) covers both targets, with post-rollout migrations and a rollback that must start before the image changes |

These are the product side: what a release needs, and how to describe it.
