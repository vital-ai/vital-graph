# Async Test Conversion Plan

All VitalGraphClient endpoint methods are now `async`. Every test file that calls
client methods needs `await` added and its calling function made `async def`.

## Change Pattern (per file)

1. `def run_tests(...)` → `async def run_tests(...)`
2. Every `self.client.<endpoint>.<method>(...)` → `await self.client.<endpoint>.<method>(...)`
3. Every `client.<endpoint>.<method>(...)` → `await client.<endpoint>.<method>(...)`
4. Every `client.open()` / `client.close()` → `await client.open()` / `await client.close()`
5. Callers of `run_tests()` must also `await` the call

---

## A. Test Runners (top-level scripts)

These contain `main()` functions that create clients and call tester classes.

| # | File | Status |
|---|------|--------|
| A1 | `test_crud_stress.py` | ✅ DONE |
| A2 | `test_multiple_organizations_crud.py` | TODO |
| A3 | `test_lead_entity_graph.py` | TODO |
| A4 | `test_lead_entity_graph_dataset.py` | TODO |
| A5 | `test_kgentities_endpoint.py` | TODO |
| A6 | `test_kgframes_endpoint.py` | TODO |
| A7 | `test_kgrelations_crud.py` | TODO |
| A8 | `test_kgtypes_endpoint.py` | TODO |
| A9 | `test_kgqueries_endpoint.py` | TODO |
| A10 | `test_spaces_endpoint.py` | TODO |
| A11 | `test_objects_endpoint.py` | TODO |
| A12 | `test_sparql_endpoints.py` | TODO |
| A13 | `test_graphs_endpoint.py` | TODO |
| A14 | `test_files_endpoint.py` | TODO |
| A15 | `test_query_endpoint.py` | TODO |
| A16 | `test_realistic_persistent.py` | TODO |
| A17 | `test_realistic_organization_workflow.py` | TODO |
| A18 | `test_jwt_auth.py` | TODO |
| A19 | `test_clean_spaces.py` | TODO |
| A20 | `create_test_space_with_data.py` | TODO |
| A21 | `delete_test_space.py` | TODO |

---

## B. multi_kgentity/ tester classes

Each has a class with `run_tests()` that calls `self.client.*`.

| # | File | Client calls | Status |
|---|------|-------------|--------|
| B1 | `case_create_organizations.py` | ~6 | TODO |
| B2 | `case_create_business_events.py` | ~3 | TODO |
| B3 | `case_create_relations.py` | ~3 | TODO |
| B4 | `case_list_entities.py` | ~2 | TODO |
| B5 | `case_list_entity_graphs.py` | ~2 | TODO |
| B6 | `case_list_business_events.py` | ~2 | TODO |
| B7 | `case_list_graphs.py` | ~2 | TODO |
| B8 | `case_get_entities.py` | ~3 | TODO |
| B9 | `case_get_business_events.py` | ~3 | TODO |
| B10 | `case_reference_id_operations.py` | ~5 | TODO |
| B11 | `case_update_entities.py` | ~2 | TODO |
| B12 | `case_verify_updates.py` | ~2 | TODO |
| B13 | `case_frame_operations.py` | ~10 | TODO |
| B14 | `case_frame_operations_reset.py` | ~11 | TODO |
| B15 | `case_entity_graph_operations.py` | ~4 | TODO |
| B16 | `case_delete_entities.py` | ~3 | TODO |
| B17 | `case_kgtypes_operations.py` | ~3 | TODO |
| B18 | `case_kgquery_entity_queries.py` | ~8 | TODO |
| B19 | `case_kgquery_frame_queries.py` | ~6 | TODO |
| B20 | `case_kgquery_relation_queries.py` | ~9 | TODO |
| B21 | `case_upload_files.py` | ~2 | TODO |
| B22 | `case_download_files.py` | ~2 | TODO |
| B23 | `case_delete_files.py` | ~2 | TODO |

---

## C. entity_graph_lead/ tester classes

| # | File | Client calls | Status |
|---|------|-------------|--------|
| C1 | `case_load_lead_graph.py` | ~3 | TODO |
| C2 | `case_verify_lead_graph.py` | ~3 | TODO |
| C3 | `case_query_lead_graph.py` | ~2 | TODO |
| C4 | `case_frame_operations.py` | ~17 | TODO |
| C5 | `case_delete_lead_graph.py` | ~3 | TODO |

---

## D. entity_graph_lead_dataset/ tester classes

| # | File | Client calls | Status |
|---|------|-------------|--------|
| D1 | `case_bulk_load_dataset.py` | ~3 | TODO |
| D2 | `case_list_and_query_entities.py` | ~4 | TODO |
| D3 | `case_retrieve_entity_graphs.py` | ~4 | TODO |
| D4 | `case_kgquery_lead_queries.py` | ~13 | TODO |

---

## E. kgentities/ tester classes

| # | File | Client calls | Status |
|---|------|-------------|--------|
| E1 | `case_kgentity_create.py` | ~6 | TODO |
| E2 | `case_kgentity_get.py` | ~4 | TODO |
| E3 | `case_kgentity_list.py` | ~5 | TODO |
| E4 | `case_kgentity_update.py` | ~6 | TODO |
| E5 | `case_kgentity_delete.py` | ~7 | TODO |
| E6 | `case_kgentity_query.py` | ~6 | TODO |
| E7 | `case_kgentity_frame_create.py` | ~10 | TODO |
| E8 | `case_kgentity_frame_get.py` | ~14 | TODO |
| E9 | `case_kgentity_frame_update.py` | ~18 | TODO |
| E10 | `case_kgentity_frame_delete.py` | ~14 | TODO |
| E11 | `case_kgentity_frame_hierarchical.py` | ~20 | TODO |

---

## F. graphs/ tester classes

| # | File | Client calls | Status |
|---|------|-------------|--------|
| F1 | `case_graph_list.py` | ~3 | TODO |
| F2 | `case_graph_create.py` | ~5 | TODO |
| F3 | `case_graph_get.py` | ~3 | TODO |
| F4 | `case_graph_delete.py` | ~5 | TODO |
| F5 | `case_graph_clear.py` | ~6 | TODO |

---

## G. files/ tester classes

| # | File | Client calls | Status |
|---|------|-------------|--------|
| G1 | `case_file_list.py` | ~2 | TODO |
| G2 | `case_file_create.py` | ~2 | TODO |
| G3 | `case_file_upload.py` | ~2 | TODO |
| G4 | `case_file_download.py` | ~2 | TODO |
| G5 | `case_file_delete.py` | ~2 | TODO |
| G6 | `case_file_pump.py` | ~2 | TODO |
| G7 | `case_file_stream_upload.py` | ~2 | TODO |
| G8 | `case_file_stream_download.py` | ~2 | TODO |

---

## H. kgtypes/ tester classes

| # | File | Client calls | Status |
|---|------|-------------|--------|
| H1 | `case_kgtype_list.py` | ~3 | TODO |
| H2 | `case_kgtype_create.py` | ~4 | TODO |
| H3 | `case_kgtype_get.py` | ~3 | TODO |
| H4 | `case_kgtype_update.py` | ~4 | TODO |
| H5 | `case_kgtype_delete.py` | ~3 | TODO |

---

## I. kgqueries/ tester classes

| # | File | Client calls | Status |
|---|------|-------------|--------|
| I1 | `case_frame_queries.py` | ~9 | TODO |
| I2 | `case_relation_queries.py` | ~8 | TODO |

---

## J. Non-test utility files (no client calls, skip)

- `__init__.py` (all directories)
- `data/__init__.py`
- `client_test_data.py` — data creation helpers, no client calls
- `client_test_utils.py` — empty file
- `dump_postgresql_quads.py` — likely standalone DB tool

---

## Total: ~75 files to update

- 21 test runner scripts (section A)
- 23 multi_kgentity case files (section B)
- 5 entity_graph_lead case files (section C)
- 4 entity_graph_lead_dataset case files (section D)
- 11 kgentities case files (section E)
- 5 graphs case files (section F)
- 8 files case files (section G)
- 5 kgtypes case files (section H)
- 2 kgqueries case files (section I)

## Recommended Order

1. **B (multi_kgentity cases)** — used by `test_crud_stress.py` (already updated runner)
2. **A2** (`test_multiple_organizations_crud.py`) — the other main runner
3. **C, D** (entity_graph_lead cases + their runners A3, A4)
4. **E** (kgentities cases + runner A5)
5. **F** (graphs cases + runner A13)
6. **G** (files cases + runner A14)
7. **H** (kgtypes cases + runner A8)
8. **I** (kgqueries cases + runner A9)
9. **Remaining runners** (A6, A7, A10-A12, A15-A21)
10. **Verify** all files compile with `python -m py_compile`
