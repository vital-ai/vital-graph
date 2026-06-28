# Entity Graph Repair Utility

Diagnose and repair orphaned KG entity graphs. An entity graph becomes
orphaned when its top-level KGEntity node is deleted but its child objects
(frames, slots, edges, documents) remain.

## Usage

Run from the project root:

```bash
# Scan for orphan graphs in a space
python -m apps.entity_graph_repair.repair_orphan_graphs scan --space my_space

# Inspect a specific entity graph (shows all graph members, edges, frames)
python -m apps.entity_graph_repair.repair_orphan_graphs inspect \
    --space my_space --entity-uri urn:my_entity

# Delete an orphan graph (dry run — shows what would be deleted)
python -m apps.entity_graph_repair.repair_orphan_graphs delete \
    --space my_space --entity-uri urn:my_entity

# Delete for real
python -m apps.entity_graph_repair.repair_orphan_graphs delete \
    --space my_space --entity-uri urn:my_entity --no-dry-run

# Delete ALL orphan graphs in a space (dry run)
python -m apps.entity_graph_repair.repair_orphan_graphs delete-all-orphans \
    --space my_space

# Delete ALL orphan graphs for real
python -m apps.entity_graph_repair.repair_orphan_graphs delete-all-orphans \
    --space my_space --no-dry-run
```

## Options

- `--graph-id` — Named graph URI (auto-detects if not specified)
- `--batch-size N` — URIs per batch delete call (default: 50)
- `--no-dry-run` — Execute deletions (default is dry run)

## How It Works

A KGEntity has an associated entity graph — objects sharing the same
`hasKGGraphURI` value. The `scan` command finds `hasKGGraphURI` values
where no corresponding entity node exists. The `delete` command removes
all objects in the orphaned graph via the VitalGraph REST API.

## Requirements

Requires a running VitalGraph server and valid client configuration
(via environment variables or config file).
