# Plan: Review and Reorganize `docs/` Directory

**Date:** 2026-06-28
**Status:** ✅ Complete

---

## Goal

Review each file in `docs/` to determine whether it:
1. Describes old work that is already implemented (and may have changed or been removed)
2. Contains content still relevant to the current system
3. Should be moved to an appropriate `planning/` subdirectory, updated, or deleted

For files with still-relevant content, create an updated version in the
appropriate planning directory. For pure historical records of completed work,
move to `archive/` or delete.

---

## Files to Review

| # | File | Size | Initial Category (to confirm) |
|---|------|------|-------------------------------|
| 1 | `ARCHITECTURE_COMPLIANCE_REPORT.md` | 7K | Likely outdated — compliance against old arch |
| 2 | `BIND_OPTIONAL_BUG.md` | 7K | Bug fix doc — likely resolved |
| 3 | `CLIENT_SERVER_MODEL_UNIFICATION_PLAN.md` | 12K | Model unification — check if done |
| 4 | `COLUMN_SCOPING_BUG.md` | 4K | Bug fix doc — likely resolved |
| 5 | `CONSTRUCT_IMPLEMENTATION.md` | 9K | SPARQL CONSTRUCT — likely implemented |
| 6 | `DATA_MANAGEMENT_TABLES_DESIGN.md` | 43K | Import/export tables — check current state |
| 7 | `EFFICIENT_IMPORT_PROCESS_DESIGN.md` | 59K | Import pipeline — check against current impl |
| 8 | `NOTES.md` | 4K | Scratch notes — triage |
| 9 | `OPTIONAL_IMPLEMENTATION.md` | 12K | SPARQL OPTIONAL — likely implemented |
| 10 | `PROD_STALL_ANALYSIS_20260416.md` | 7K | Production incident analysis — historical |
| 11 | `SUBQUERY_IMPLEMENTATION_PLAN.md` | 11K | SPARQL subqueries — likely implemented |
| 12 | `VITALGRAPH_ARCHITECTURE.md` | 14K | Architecture overview — may be current |
| 13 | `auth-plan.md` | 17K | Auth implementation plan — likely done |
| 14 | `client-model-signatures.md` | 33K | Client method signatures — check if current |
| 15 | `client-plan.md` | 79 bytes | Nearly empty — delete |
| 16 | `entity_registry.md` | 19K | Entity registry docs — check if current |
| 17 | `graph_uri_naming_conventions.md` | 7K | Naming conventions — likely still relevant |
| 18 | `jwt-client-updates.md` | 7K | JWT client updates — likely done |
| 19 | `jwt-secret-generation.md` | 3K | JWT secret generation — likely done |
| 20 | `kg-services-migration-plan.md` | 45K | KG services migration — likely done |
| 21 | `kgentities_refactoring_completion_report.md` | 10K | Refactoring report — historical |
| 22 | `kgtypes_correction_plan.md` | 27K | KGTypes corrections — check if done |
| 23 | `mock-graph-impl.md` | 11K | Mock graph impl — being removed (see remove_mock plan) |
| 24 | `mock_client_vitalsigns_plan.md` | 33K | Mock client plan — being removed |
| 25 | `object-impl-plan.md` | 52K | Object implementation — likely done |
| 26 | `planned_rest_api_endpoints.md` | 13K | REST API plan — compare against current |
| 27 | `property_paths_integration_design.md` | 9K | SPARQL property paths — check if implemented |
| 28 | `sparql_property_paths_implementation_plan.md` | 14K | Property paths impl — check if done |
| 29 | `sparql_update_implementation_plan.md` | 17K | SPARQL UPDATE — likely implemented |
| 30 | `vitalgraph-import-process.md` | 14K | Import process — check against current |
| 31 | `vitalgraph_service_impl_plan.md` | 35K | Service impl plan — likely done |

---

## End State

Once this review is complete, the `docs/` directory should be **empty** and can
be removed. All content will have been either archived, moved to the appropriate
planning directory, or deleted.

---

## Review Process (per file)

1. Read the file
2. Compare against current codebase to determine implementation status
3. Categorize:
   - **Delete** — Fully implemented, no longer useful as reference
   - **Archive** — Historical value, move to `archive/docs/`
   - **Update & Move** — Has relevant content, create updated version in appropriate `planning/` subdir
   - **Keep in docs/** — Still accurate and useful as active documentation
4. Execute the action

---

## Expected Outcomes

### Likely deletions / archive (implemented work)
- Bug fix docs: `BIND_OPTIONAL_BUG.md`, `COLUMN_SCOPING_BUG.md`
- Implementation plans for completed features: `CONSTRUCT_IMPLEMENTATION.md`, `OPTIONAL_IMPLEMENTATION.md`, `SUBQUERY_IMPLEMENTATION_PLAN.md`, `sparql_update_implementation_plan.md`
- Mock-related: `mock-graph-impl.md`, `mock_client_vitalsigns_plan.md`
- Migration/refactoring reports: `kgentities_refactoring_completion_report.md`, `kg-services-migration-plan.md`
- Auth plans (done): `auth-plan.md`, `jwt-client-updates.md`, `jwt-secret-generation.md`
- Incident reports: `PROD_STALL_ANALYSIS_20260416.md`
- Empty: `client-plan.md`

### Likely keep / update
- `VITALGRAPH_ARCHITECTURE.md` — Keep if current, update if stale
- `graph_uri_naming_conventions.md` — Reference doc, likely still relevant
- `planned_rest_api_endpoints.md` — Update to reflect current API
- `entity_registry.md` — Update if entity registry is still active
- `DATA_MANAGEMENT_TABLES_DESIGN.md` — Check against current import/export tables
- `client-model-signatures.md` — Update if client signatures have changed

### Possible moves to planning dirs
- `property_paths_integration_design.md` → `planning/planning_sql/` (if not yet implemented)
- `EFFICIENT_IMPORT_PROCESS_DESIGN.md` → `planning/planning_import_export/` (if still relevant)

---

## Dependencies

- Should be done after mock removal plan is confirmed (determines fate of mock docs)
- Can be done incrementally — one file at a time

---

## Results

All 31 files processed. `docs/` is now empty and can be deleted.

### Archived → `archive/docs/` (25 files)
Historical/completed implementation docs:
- `ARCHITECTURE_COMPLIANCE_REPORT.md`, `BIND_OPTIONAL_BUG.md`, `CLIENT_SERVER_MODEL_UNIFICATION_PLAN.md`
- `CONSTRUCT_IMPLEMENTATION.md`, `DATA_MANAGEMENT_TABLES_DESIGN.md`, `EFFICIENT_IMPORT_PROCESS_DESIGN.md`
- `NOTES.md`, `OPTIONAL_IMPLEMENTATION.md`, `PROD_STALL_ANALYSIS_20260416.md`
- `SUBQUERY_IMPLEMENTATION_PLAN.md`, `VITALGRAPH_ARCHITECTURE.md`, `auth-plan.md`
- `client-model-signatures.md`, `jwt-client-updates.md`, `jwt-secret-generation.md`
- `kg-services-migration-plan.md`, `kgentities_refactoring_completion_report.md`
- `kgtypes_correction_plan.md`, `mock-graph-impl.md`, `mock_client_vitalsigns_plan.md`
- `object-impl-plan.md`, `planned_rest_api_endpoints.md`
- `property_paths_integration_design.md`, `sparql_property_paths_implementation_plan.md`
- `sparql_update_implementation_plan.md`, `vitalgraph-import-process.md`
- `vitalgraph_service_impl_plan.md`

### Moved → `planning/planning_features/` (3 files)
Active reference docs:
- `entity_registry.md` — Entity registry usage/reference (paths need updating)
- `graph_uri_naming_conventions.md` — URI naming spec (still active)

### Moved → `planning/planning_sql/` (1 file)
Open bugs:
- `COLUMN_SCOPING_BUG.md` — Open bug in V2 SPARQL-to-SQL (~13 DAWG tests affected)

### Deleted (1 file)
- `client-plan.md` — 1-line question, already answered
