# Plan Tree Fixtures

JSON fixtures captured from the Jena sidecar's `/v1/sparql/compile` endpoint.

## How it works

1. `generate_fixtures.py` sends SPARQL queries to a running sidecar and saves
   the compile responses as JSON files.
2. Unit tests load these JSON files, run `map_compile_response()` + `collect()`
   to reconstruct real `PlanV2` trees, then test optimizer passes against them.
3. **No sidecar dependency at test time** — only when regenerating fixtures.

## When to regenerate

- When the Jena sidecar version changes (new algebra shapes)
- When `jena_ast_mapper.py` or `collect.py` change their input contract
- When adding new SPARQL query patterns to the test corpus

## Regenerate

```bash
# Requires running sidecar on localhost:8081
python tests/fixtures/plan_trees/generate_fixtures.py
```
