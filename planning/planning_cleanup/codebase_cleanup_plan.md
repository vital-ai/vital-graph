# VitalGraph Codebase Cleanup & Modernization Plan

**Date:** 2026-06-28
**Status:** Initial draft — discussion phase

---

## Goal

Modernize and clean up the VitalGraph repository to match expectations of a well-organized
AI and database project. This means:

1. **Clear top-level structure** — ~15–20 meaningful directories, not ~79
2. **No dead code or empty directories** in the working tree
3. **Consolidated test infrastructure** under a single `tests/` directory (pytest-based)
4. **Planning docs organized** — consolidated, with stale/completed plans archived
5. **Scripts, data, and tooling** in predictable locations
6. **Build artifacts and generated output** excluded via `.gitignore`

---

## Current State

**Top-level directories:** 79 (including hidden)
**Planning directories:** 18 (including `planning_cleanup`)
**Test-related directories:** 11+ scattered locations
**Empty directories:** ~15 (notes, k8s_config, minioFiles, oxigraph, etc.)
**Stale root-level files:** ~10 (debug scripts, repair logs, data files, empty .py files)

---

## Related Planning Documents

### Recently Updated (last 30 days)

| File | Last Modified | Topic |
|------|---------------|-------|
| `planning_visualization/centralized_kgtypes_space_plan.md` | Jun 18 | Centralized KGTypes space |
| `planning_vector_geo/semantic_search_ui_plan.md` | Jun 17 | Semantic search UI |
| `planning_vector_geo/search_ui_plan.md` | Jun 15 | Search UI |
| `planning_kgdocument/kgdocument_plan.md` | Jun 14 | KGDocument segmentation |
| `planning_vector_geo/geo_fuzzy_search_testing_plan.md` | Jun 14 | Geo/fuzzy testing |
| `planning_vector_geo/text_hybrid_search_plan.md` | Jun 14 | Text/hybrid search |
| `planning_vector_geo/registry_vector_migration_plan.md` | Jun 14 | Registry vector migration |
| `planning_vector_geo/vector_geo_plan.md` | Jun 14 | Vector + geo master plan |
| `planning_vector_geo/geo_fuzzy_search_gaps.md` | Jun 14 | Geo/fuzzy gaps |
| `planning_vector_geo/fuzzy_search_implementation_plan.md` | Jun 14 | Fuzzy search impl |
| `planning_kg_model/kg_model_plan.md` | Jun 14 | KG model |
| `planning_kg_model/kgframes_filter_sort_parity_plan.md` | Jun 14 | KGFrames filter/sort |
| `planning_visualization/kg_types_plan.md` | Jun 14 | KG types visualization |
| `planning_visualization/kg_types_search_plan.md` | Jun 13 | KG types search |
| `planning_visualization/framenet_testing_plan.md` | Jun 13 | FrameNet testing |
| `planning_vector_geo/fuzzy_redis_to_postgresql_plan.md` | Jun 13 | Fuzzy Redis→PG migration |
| `planning_visualization/SPARQL_VALUES_BUG.md` | Jun 12 | VALUES bug |
| `planning_visualization/btree_term_index_plan.md` | Jun 12 | BTree term index |
| `planning_visualization/prototype_kg_types_plan.md` | Jun 12 | KG types prototype |
| `planning_visualization/visualization_config_plan.md` | Jun 11 | Visualization config |
| `planning_ui/ui_completion_plan.md` | Jun 10 | UI completion |
| `planning_auth/authentication_modernization_plan.md` | Jun 10 | Auth modernization |
| `planning_vital_cli/cli_implementation_plan.md` | Jun 10 | CLI implementation |
| `planning_client/client_api_sync_plan.md` | Jun 10 | Client API sync |
| `planning_visualization/graph_visualization_plan.md` | Jun 10 | Graph visualization |
| `planning_import_export/import_export_plan.md` | Jun 10 | Import/export |
| `planning_ui/entity_graph_viewer_plan.md` | Jun 10 | Entity graph viewer |
| `planning_space_analytics/space_analytics_plan.md` | Jun 10 | Space analytics |
| `planning_ui/ui_dev_deployment_plan.md` | Jun 10 | UI dev/deployment |
| `planning_auth/api_key_support_plan.md` | Jun 10 | API key support |
| `planning_auth/auth_audit_logging_plan.md` | Jun 10 | Auth audit logging |
| `planning_space_analytics/query_tracking_plan.md` | Jun 10 | Query tracking |
| `planning_space_analytics/metrics_postgres_migration_plan.md` | Jun 10 | Metrics PG migration |
| `planning_multi_vector/multi_vector_query_plan.md` | Jun 9 | Multi-vector query |
| `planning_client/typescript_client_plan.md` | Jun 9 | TypeScript client |
| `planning_vital_cli/bootstrap_and_migration.md` | Jun 8 | Bootstrap/migration |
| `planning_cleanup/testing_plan.md` | Jun 6 | Formal testing |
| `planning_ui/ui_testing_plan.md` | Jun 6 | UI testing |
| `planning_sql/performance_analysis/mitigation_details.md` | Jun 6 | SQL perf mitigation |
| `planning_sql/performance_analysis/100x_scalability_analysis.md` | Jun 6 | Scalability |
| `planning_sql/kg_query/entity_only_update_plan.md` | May 29 | Entity update plan |
| `planning_sql/kg_query/child_frame_update_duplication_bug.md` | May 29 | Frame update bug |

### Key Completed Plans (reference for what's already done)

| File | Topic | Status |
|------|-------|--------|
| `planning_cleanup/archive_db_postgresql_plan.md` | Archive V1 PostgreSQL backend | ✅ All 4 phases complete |
| `planning_cleanup/codebase_simplification_plan.md` | Delete empty stubs, unused modules | Partially actioned |

### Stale/Legacy Planning Directories

| Directory | Files | Notes |
|-----------|-------|-------|
| `planning/` | 21 items | Mixed — many 0-byte or very old (kg_query_plan.md, oxigraph_redis_search_plan.md) |
| `planning_fuseki/` | 61 items | Massive — many relate to the now-experimental fuseki_postgresql backend |
| `planning_internal/` | 0 items | Empty |

---

## Apps Directory

Use `apps/` at the repo root for standalone applications/scripts that are not
(yet) incorporated into the main CLI entry points (`bin/`). These are functional
tools that import from `vitalgraph` but run independently.

Current contents:
- `apps/entity_registry/` — Entity registry admin, import/export, migration, Weaviate sync
- `apps/agent_registry/` — Agent registry migration scripts

Scripts use `Path(__file__).parent.parent` to resolve the project root for
`sys.path`, so they work from the `apps/` location.

---

## Archive Strategy

Use `archive/` at the repo root as a temporary staging area for files being
reorganized. Items are moved here first, reviewed/reorganized, and then deleted
once confirmed unnecessary. This avoids accidental loss during cleanup and
provides a buffer for files whose fate is unclear.

```
archive/
├── (files moved here temporarily during cleanup)
└── (deleted once reorganization is complete)
```

The existing `archive_vitalgraph_old/` (V1 backend code) should also be moved
into `archive/` for consistency.

---

## Proposed Cleanup Phases

### Phase 1: Immediate Deletions (zero risk)

Delete empty directories and files that provide no value:

- **Empty dirs:** `notes/`, `k8s_config/`, `minioFiles/`, `lead_test_data/`, `lead_test_data_docs/`, `test_data/`, `web_assets/`, `planning_internal/`, `frontend-archive/`, `frontend-old/`, `rdflib_sqlalchemy/`, `oxigraph/`, `registry_generated_vectors/`, `registry_output/`
- **Empty/dead files:** `test_rdflib_parsing.py`, `notes.txt`
- **Build artifacts (gitignore):** `dist/`, `vital_graph.egg-info/`, `__pycache__/`
- **Large stray files:** `crossref_repair_20260410_123010.txt` (9MB), `space_realistic_org_test_quads.nq` (60KB), `vitalhome.zip` (6KB)
- **One-off debug scripts at root:** `_debug_industry.py`, `test_term_uuid_ddl.py`, `test_term_uuid_match.py`

### Phase 2: Consolidate Test Directories

Merge 11+ test directories into a single `tests/` tree (per testing_plan.md):

| Current | Target |
|---------|--------|
| `test_scripts/` (384 items) | Triage → `tests/integration/` or delete |
| `test_scripts_misc/` (49) | Triage → `tests/` or delete |
| `test_script_kg_impl/` (90) | Port → `tests/integration/kg/` |
| `test_sparql/` (3) | Move → `tests/conformance/` |
| `test_sparql_sql_endpoints/` (1) | Delete (empty `__init__.py` only) |
| `test_vs/` (1) | Port → `tests/unit/` or delete |
| `test_client_api/` (3) | Port → `tests/api/` |
| `test_files/` (40) | Move → `tests/fixtures/files/` |
| `test_files_download/` (1) | Delete/gitignore |
| `localTestFiles/` (2) | Delete/gitignore |
| `vitalgraph_client_test/` (212) | Port → `tests/api/` + `tests/integration/` |
| `vitalgraph_mock_client_test/` (33) | Port → `tests/integration/mock/` |
| `vitalgraph_service_tests/` (5) | Port → `tests/integration/service/` |
| `vitalsigns_test_scripts/` (3) | Port → `tests/unit/vitalsigns/` |

### Phase 3: Consolidate Scripts & Tooling

| Current | Target |
|---------|--------|
| `debug_scripts/` (36) | → `scripts/debug/` |
| `sql_scripts/` (34) | → `scripts/sql/` |
| `log_analysis/` (5) | → `scripts/log_analysis/` |
| `agent_registry/` (2) | → `scripts/agent_registry/` or into `vitalgraph/` |
| `tool_utils/` (2) | → `vitalgraph/utils/` or delete |
| `fuseki_deploy_test/` (62) | → `deploy_docs/fuseki/` or archive |
| `generated_instances/` (4) | → `domain_schema/generated/` or gitignore |

### Phase 4: Consolidate Planning Docs

**18 planning directories → 1** unified `planning/` with subdirectories:

```
planning/
├── active/              # Plans for current/upcoming work
│   ├── search/          # vector_geo, multi_vector
│   ├── ui/              # ui plans
│   ├── auth/            # auth plans
│   ├── client/          # client plans
│   ├── testing/         # testing plans
│   ├── cli/             # CLI plans
│   ├── model/           # KG model plans
│   └── sql/             # SPARQL-to-SQL plans
├── completed/           # Finished work (reference only)
│   ├── service/         # archive_db_postgresql, codebase_simplification
│   ├── fuseki/          # bulk of planning_fuseki/
│   └── ...
└── cleanup/             # This plan + cleanup tracking
```

Alternatively, keep a flat `planning/` with a `_completed/` subfolder and clear naming.

### Phase 5: Target Directory Structure

```
vital-graph/
├── vitalgraph/              # Shipped Python package
├── vitalgraph-jena-sidecar/ # Java sidecar (separate build)
├── vitalgraph-client-ts/    # TypeScript client SDK
├── frontend/                # Web UI (React)
├── tests/                   # ALL formal tests (pytest)
├── scripts/                 # Operational scripts
├── docs/                    # Active documentation
├── domain_schema/           # Ontology schemas
├── entity_registry/         # Entity registry tooling
├── planning/                # Planning docs (consolidated)
├── examples/                # Usage examples
├── deploy_docs/             # Deployment guides
├── bin/                     # Shell entry points
├── .github/                 # CI workflows
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── README.md
└── LICENSE
```

**Result:** ~79 top-level entries → ~18

---

## Execution Strategy

| Phase | Effort | Risk | Dependencies |
|-------|--------|------|--------------|
| Phase 1: Deletions | 30 min | Zero | None |
| Phase 2: Test consolidation | 2–3 days | Low | Decide test structure first |
| Phase 3: Scripts consolidation | 1 day | Low | None |
| Phase 4: Planning consolidation | 1–2 hours | Zero | None |
| Phase 5: Final structure | Part of Phases 2–4 | — | All above |

---

## Discussion Points

1. **Test directory triage** — The 384 items in `test_scripts/` need manual review. Some are valuable integration tests worth porting; many are one-off experiments. Should we do a quick automated pass (check for imports of deprecated modules, check file size, check last-modified) to categorize them?

2. **Planning doc strategy** — Should we consolidate all 18 planning dirs into one, or keep the current split but prune aggressively (delete empty/completed plans)?

3. **`vitalgraph_sparql_sql/`** (142 items) — This is the V2 SPARQL-to-SQL dev/test workspace (DAWG tests, benchmarks). It's not part of the shipped package but is actively used. Should it stay at root, move under `tests/conformance/`, or become a separate repo?

4. **`archive_vitalgraph_old/`** (51 items) — Already labeled as archive. Delete entirely (git history preserves it) or keep?

5. **`planning_fuseki/`** (61 items) — Largest planning directory by far. The fuseki_postgresql backend is now "experimental". Archive these docs or keep for reference?

6. **`entity_registry/`** — Active tooling but 20 items at root level. Keep as-is or move under `vitalgraph/`?

7. **Priority** — Should cleanup happen before or in parallel with the formal testing plan (Phase 0 of testing_plan.md already specifies cleanup)?

---

## References

- `planning_cleanup/testing_plan.md` — Formal testing plan (includes "Project Cleanup" section)
- `planning_cleanup/codebase_simplification_plan.md` — Internal package cleanup (partially done)
- `planning_cleanup/archive_db_postgresql_plan.md` — V1 backend archive (✅ complete)
