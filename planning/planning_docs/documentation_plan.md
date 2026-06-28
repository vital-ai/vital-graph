# Plan: VitalGraph Documentation

**Date:** 2026-06-28
**Status:** In Progress

---

## Goal

Create comprehensive documentation for VitalGraph in the `docs/` directory
covering all features, components, architecture, and usage instructions. The
documentation should serve both developers working on VitalGraph and users
consuming the API/CLI/UI.

---

## Principles

- **Living documentation** — Updated incrementally as features are built or changed
- **Audience-aware** — Separate developer docs from user/operator guides
- **Example-driven** — Include concrete examples for all API/CLI usage
- **Single source of truth** — `docs/` is the canonical location; planning docs inform but don't replace

---

## Planned Structure

```
docs/
├── OVERVIEW.md                  # Top-level system overview (✅ exists)
├── architecture/
│   ├── system-architecture.md   # Layered architecture, component interaction
│   ├── data-model.md            # RDF quad store, term tables, space isolation
│   └── sparql-engine.md         # SPARQL-to-SQL pipeline internals
├── guides/
│   ├── getting-started.md       # Installation, first run, basic usage
│   ├── configuration.md         # Config files, environment variables
│   ├── deployment.md            # Docker, ECS, Kubernetes
│   └── authentication.md        # JWT, API keys, roles
├── api/
│   ├── rest-api-reference.md    # Full endpoint reference
│   ├── sparql-reference.md      # SPARQL support, vg: functions
│   ├── client-python.md         # Python client usage
│   └── client-typescript.md     # TypeScript client usage
├── features/
│   ├── knowledge-graph.md       # Entities, frames, slots, types, relations
│   ├── documents.md             # KGDocuments, segmentation, RAG
│   ├── search.md                # Vector, FTS, hybrid, geo, fuzzy
│   ├── entity-registry.md       # Dedup, resolution, clustering
│   ├── import-export.md         # Bulk data operations
│   └── files.md                 # File management
├── cli/
│   ├── vitalgraphdb.md          # Server CLI
│   ├── vitalgraphadmin.md       # Admin CLI
│   ├── vitalgraphimport.md      # Import CLI
│   └── vitalgraphexport.md      # Export CLI
├── frontend/
│   └── admin-ui.md              # React frontend guide
└── operations/
    ├── monitoring.md            # Metrics, observability
    ├── maintenance.md           # Background jobs, vacuum, stats
    └── troubleshooting.md       # Common issues, debugging
```

---

## Approach

1. Start with `OVERVIEW.md` as the entry point (done)
2. Build docs incrementally — each time a feature is reviewed or worked on,
   write or update the corresponding doc
3. Prioritize user-facing docs (guides, API reference) over internals
4. Extract content from planning docs where relevant, converting plans into
   factual documentation of current state
5. Keep architecture docs accurate — update when implementation changes

---

## Priority Order

| Priority | Document | Reason |
|----------|----------|--------|
| 1 | `guides/getting-started.md` | First thing new users need |
| 2 | `api/rest-api-reference.md` | Core usage reference |
| 3 | `features/knowledge-graph.md` | Primary feature set |
| 4 | `api/sparql-reference.md` | Key differentiator |
| 5 | `features/search.md` | High-value feature |
| 6 | `guides/configuration.md` | Operational necessity |
| 7 | `cli/` | All CLI docs |
| 8 | `architecture/` | Developer audience |
| 9 | Remaining features | As worked on |

---

## Notes

- The existing `README.md` at the repo root provides a quick-start; `docs/`
  should expand on that without duplicating it
- API reference can potentially be auto-generated from FastAPI's OpenAPI schema
  and augmented with examples
- CLI docs can be bootstrapped from `--help` output and expanded with examples
