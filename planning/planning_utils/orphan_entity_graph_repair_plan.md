# Plan: Orphan Entity Graph Repair Utility

**Date:** 2026-06-28
**Status:** ✅ Implemented
**Location:** `apps/entity_graph_repair/`

---

## Problem

When a top-level KGEntity node is deleted without properly deleting its entity graph, the remaining graph objects (frames, slots, edges, documents) become orphaned. These orphans:

- Waste storage and pollute search indexes
- Have no parent entity to navigate to from the UI
- May cause confusing results in SPARQL queries and entity listings
- Cannot be discovered through normal entity browsing

### KG Entity Graph Structure

A KGEntity has an associated **entity graph** — a cluster of objects sharing the same `hasKGGraphURI` value (the entity's URI). A typical entity graph contains:

```
KGEntity (top-level node)
 ├── Edge_hasEntityKGFrame → KGFrame(s)
 │    ├── KGSlot(s) (text, integer, boolean, URI, etc.)
 │    └── Edge_hasKGDocument → KGDocument(s)
 ├── Edge_hasEntityKGFrame → additional frames
 └── Other edges (source or destination)
```

All objects in the graph have `hasKGGraphURI = <entity_uri>`.
Frames additionally have `hasFrameGraphURI` grouping their slots.

### Scenarios

1. **Entity deleted, graph left behind** — most common case. The KGEntity node was removed (e.g., via direct triple deletion or a bug in the delete path) but its frames, slots, edges, and documents remain.
2. **Partial deletion** — some graph members were deleted but others remain (e.g., edges deleted but slots left behind).
3. **Bulk operation failure** — a batch delete of entities failed partway through, leaving some entity graphs incomplete.

---

## Proposed Utility

A general-purpose CLI tool in `apps/entity_graph_repair/` that can **diagnose** and **repair** orphaned entity graphs.

### Commands

#### 1. `scan` — Find orphan graphs

Discover entity graphs where the top-level KGEntity node is missing.

```bash
python -m apps.entity_graph_repair.repair_orphan_graphs scan \
    --space <space_id> \
    [--graph <graph_uri>]    # optional: limit to specific named graph
```

Logic:
- Query for all distinct `hasKGGraphURI` values in the space
- For each, check if a subject with that URI exists with `rdf:type` that is a KGEntity subclass
- Report those where the entity node is missing, along with the count of orphaned objects

Output:
```
Scanning space: my_space
  urn:entity:001 — ORPHAN — 14 objects (3 frames, 8 slots, 2 edges, 1 doc)
  urn:entity:002 — OK
  urn:entity:003 — ORPHAN — 6 objects (1 frame, 4 slots, 1 edge)
Found 2 orphan entity graphs (20 total orphaned objects)
```

#### 2. `inspect` — Show details of an orphan graph

```bash
python -m apps.entity_graph_repair.repair_orphan_graphs inspect \
    --space <space_id> \
    --entity-uri <entity_uri>
```

Logic (derived from `query_entity_graph_leftovers.py`):
1. Objects with `hasKGGraphURI = <entity_uri>` (graph members)
2. Direct triples with the entity URI as subject (the entity itself, if any remain)
3. Edges referencing the entity as source or destination
4. Frame URIs and their `hasFrameGraphURI` children (slots)

#### 3. `delete` — Remove an orphaned entity graph

```bash
python -m apps.entity_graph_repair.repair_orphan_graphs delete \
    --space <space_id> \
    --entity-uri <entity_uri> \
    [--dry-run]               # default: dry run
    [--force]                 # skip confirmation
    [--batch-size 50]
```

Logic (derived from `delete_kggraph_uri_subjects.py`):
1. Discover all subjects with `hasKGGraphURI = <entity_uri>`
2. Also discover edges referencing the entity as source or destination
3. Delete all discovered objects in batches via the objects endpoint
4. Verify no orphans remain

#### 4. `delete-all-orphans` — Batch cleanup

```bash
python -m apps.entity_graph_repair.repair_orphan_graphs delete-all-orphans \
    --space <space_id> \
    [--dry-run]
```

Runs `scan` then `delete` for each orphan found.

---

## Design Decisions

- **Uses VitalGraphClient** — operates via the REST API, not direct SQL, so it's safe to run against any environment
- **Dry-run by default** — destructive operations require explicit `--force` or `--no-dry-run`
- **Batch deletion** — uses batched object deletion to avoid timeouts on large graphs
- **Verification step** — after deletion, re-queries to confirm cleanup
- **Parameterized** — no hardcoded space IDs or URIs (unlike the original scripts)
- **argparse CLI** — with subcommands (`scan`, `inspect`, `delete`, `delete-all-orphans`)

---

## File Structure

```
apps/entity_graph_repair/
├── __init__.py
├── repair_orphan_graphs.py      # CLI entry point with argparse subcommands
├── orphan_scanner.py             # scan + inspect logic
├── orphan_deleter.py             # delete + verify logic
└── README.md                     # usage documentation
```

---

## Prior Art (archived scripts)

These scripts addressed the same problem but with hardcoded URIs and single-use design:

- `archive/scripts/check_residual_triples.py` — checked for triples matching specific campaign kGGraphURIs
- `archive/scripts/query_kggraph_uri_subjects.py` — listed subjects under specific kGGraphURIs
- `archive/scripts/delete_kggraph_uri_subjects.py` — batch-deleted objects by kGGraphURI (with dry-run support)
- `test_scripts/query_entity_graph_leftovers.py` — comprehensive orphan inspection (5 query types: graph members, direct triples, frame edges, frame graph children, related edges)

The `query_entity_graph_leftovers.py` script has the most complete inspection logic and should be the primary reference for the `inspect` command.

---

## Implementation Notes

- The `scan` command needs an efficient way to find orphan graphs. A single SPARQL query can check for kGGraphURI values that don't have a corresponding entity node:
  ```sparql
  PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
  PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

  SELECT DISTINCT ?graphURI (COUNT(?s) AS ?objectCount) WHERE {
    ?s haley:hasKGGraphURI ?graphURI .
    FILTER NOT EXISTS {
      ?graphURI rdf:type ?type .
    }
  }
  GROUP BY ?graphURI
  ```
- Consider adding a `--entity-type` filter to scope the scan (e.g., only check KGNewsEntity graphs)
- The deletion should handle edge cases: objects that reference the orphaned entity from *other* entity graphs should not be deleted
