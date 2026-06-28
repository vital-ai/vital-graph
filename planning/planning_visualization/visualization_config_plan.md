# Graph Visualization Config — Database-Stored Mapping Plan

## 1. Overview

The graph visualization requires per-type configuration to control how KG types
are rendered: frame arity (binary collapse vs hub), node colors/shapes/icons,
edge styling, and label/tooltip selection. This configuration is **stored in the
database** as per-space PostgreSQL tables — separate from the ontology that
defines what types *are*.

This plan covers:
1. **Database schema** — separate tables per config category (no JSONB)
2. **Manager classes** — CRUD on each table
3. **REST endpoints** — per-table CRUD + combined read-only viz-config endpoint
4. **Frontend integration** — single JSON map consumed by the graph renderer

---

## 2. Design Principles

- **Not ontology properties** — visualization config is operational metadata,
  not part of the type system. Different spaces can style the same types
  differently.
- **Follows the vector mapping pattern** — per-space config tables with typed
  columns, CRUD via REST endpoints, managed through UI screens.
- **Separate tables per category** — each category has properly typed columns;
  no JSONB. New tables added incrementally as features are implemented.
- **Combined read endpoint** — the visualization fetches all config in one call
  (`viz-config`); CRUD endpoints are used by the admin UI.

---

## 3. Relationship to Other Mapping Infrastructure

| Table | Purpose | Consumers |
|-------|---------|-----------|
| `{space}_vector_mapping` | Property → vector index mapping | Vector populator, search |
| `{space}_vector_mapping_property` | Child properties per vector mapping | Vector populator |
| `{space}_geo_config` | Geo configuration | Geo populator |
| **`{space}_kgtype_frame_arity`** | **Frame arity classification** | **Graph visualization** |
| **`{space}_kgtype_node_style`** | **Node colors, shapes, icons** | **Graph visualization** |
| **`{space}_kgtype_edge_style`** | **Edge colors, widths, patterns** | **Graph visualization** |
| **`{space}_kgtype_label_config`** | **Label/tooltip property selection** | **Graph visualization** |
| **`{space}_kgtype_label_tooltip`** | **Tooltip property list (child)** | **Graph visualization** |

---

## 4. Database Schema

### 4.1 `{space_id}_kgtype_frame_arity`

```sql
CREATE TABLE IF NOT EXISTS {space_id}_kgtype_frame_arity (
    mapping_id          SERIAL PRIMARY KEY,
    type_uri            VARCHAR(500) NOT NULL UNIQUE, -- KGFrameType URI
    arity               VARCHAR(20) NOT NULL,         -- 'binary', 'n_ary', 'unary'
    source_slot_uri     VARCHAR(500),                 -- slot prototype URI for source (binary)
    dest_slot_uri       VARCHAR(500),                 -- slot prototype URI for destination (binary)
    edge_label          VARCHAR(255),                 -- display label when collapsed to edge
    auto_computed       BOOLEAN DEFAULT FALSE,        -- TRUE if derived from prototypes
    created_time        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_time        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Arity values:**

| Value | Slot Count | Visualization |
|-------|------------|---------------|
| `binary` | 2 entity slots | Collapsed to single edge between entities |
| `n_ary` | 3+ entity/doc slots | Hub node with spokes to entities |
| `unary` | 0–1 entity slots | Badge on entity or hidden |

**Binary frame directionality:** `source_slot_uri` / `dest_slot_uri` store
which KGSlotProtoType is source vs destination, auto-populated from
`Edge_hasKGSlotProtoType.kGSlotRoleSequence` (seq 1 = source, seq 2 = dest).

### 4.2 `{space_id}_kgtype_node_style`

```sql
CREATE TABLE IF NOT EXISTS {space_id}_kgtype_node_style (
    style_id            SERIAL PRIMARY KEY,
    type_uri            VARCHAR(500) NOT NULL UNIQUE, -- KGEntityType / KGFrameType URI
    color               VARCHAR(20),                  -- hex color (e.g. '#4F46E5')
    border_color        VARCHAR(20),                  -- hex border color
    shape               VARCHAR(30),                  -- 'circle', 'rectangle', 'diamond', 'hexagon'
    icon                VARCHAR(50),                  -- icon name (e.g. 'book', 'user', 'building')
    size                VARCHAR(20),                  -- 'small', 'medium', 'large'
    created_time        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_time        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 4.3 `{space_id}_kgtype_edge_style`

```sql
CREATE TABLE IF NOT EXISTS {space_id}_kgtype_edge_style (
    style_id            SERIAL PRIMARY KEY,
    type_uri            VARCHAR(500) NOT NULL UNIQUE, -- KGRelationType / binary KGFrameType URI
    color               VARCHAR(20),                  -- hex color
    stroke_width        INTEGER DEFAULT 2,            -- pixels
    dash_pattern        VARCHAR(20) DEFAULT 'solid',  -- 'solid', 'dashed', 'dotted'
    arrow_style         VARCHAR(20) DEFAULT 'triangle', -- 'triangle', 'circle', 'none'
    created_time        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_time        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 4.4 `{space_id}_kgtype_label_config`

```sql
CREATE TABLE IF NOT EXISTS {space_id}_kgtype_label_config (
    config_id           SERIAL PRIMARY KEY,
    type_uri            VARCHAR(500) NOT NULL UNIQUE, -- any KG type URI
    label_property      VARCHAR(500),                 -- property URI to use as node label
    subtitle_property   VARCHAR(500),                 -- property URI for subtitle line
    created_time        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_time        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 4.5 `{space_id}_kgtype_label_tooltip`

```sql
CREATE TABLE IF NOT EXISTS {space_id}_kgtype_label_tooltip (
    tooltip_id          SERIAL PRIMARY KEY,
    config_id           INTEGER NOT NULL,             -- FK to label_config
    property_uri        VARCHAR(500) NOT NULL,        -- property to show in tooltip
    ordinal             INTEGER DEFAULT 0,            -- display order
    FOREIGN KEY (config_id) REFERENCES {space_id}_kgtype_label_config(config_id) ON DELETE CASCADE
);
```

### 4.6 Future Tables

| Table | Applies To | Columns | Purpose |
|-------|-----------|---------|---------|
| `{space}_kgtype_grouping` | KGEntityType | `cluster_by`, `cluster_color`, `sort_priority` | How to cluster/group entities |
| `{space}_kgtype_visibility` | Any KG type | `default_visible`, `expandable`, `max_depth` | Default expand/collapse |

### 4.7 Table Creation

Added to `sparql_sql_schema.py` space creation alongside vector/geo tables:

```python
# 10. KG type visualization mapping tables
stmts.append(f'''
    CREATE TABLE IF NOT EXISTS {t['kgtype_frame_arity']} (
        mapping_id      SERIAL PRIMARY KEY,
        type_uri        VARCHAR(500) NOT NULL UNIQUE,
        arity           VARCHAR(20) NOT NULL,
        source_slot_uri VARCHAR(500),
        dest_slot_uri   VARCHAR(500),
        edge_label      VARCHAR(255),
        auto_computed   BOOLEAN DEFAULT FALSE,
        created_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')

stmts.append(f'''
    CREATE TABLE IF NOT EXISTS {t['kgtype_node_style']} (
        style_id        SERIAL PRIMARY KEY,
        type_uri        VARCHAR(500) NOT NULL UNIQUE,
        color           VARCHAR(20),
        border_color    VARCHAR(20),
        shape           VARCHAR(30),
        icon            VARCHAR(50),
        size            VARCHAR(20),
        created_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')

stmts.append(f'''
    CREATE TABLE IF NOT EXISTS {t['kgtype_edge_style']} (
        style_id        SERIAL PRIMARY KEY,
        type_uri        VARCHAR(500) NOT NULL UNIQUE,
        color           VARCHAR(20),
        stroke_width    INTEGER DEFAULT 2,
        dash_pattern    VARCHAR(20) DEFAULT 'solid',
        arrow_style     VARCHAR(20) DEFAULT 'triangle',
        created_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')
```

---

## 5. Manager Classes

Following the `MappingManager` pattern from `vitalgraph/vectorization/mapping_manager.py`,
each table gets its own manager class:

```python
class FrameArityManager:
    """CRUD on {space_id}_kgtype_frame_arity table."""

    def __init__(self, conn, space_id: str):
        self.conn = conn
        self._table = f"{space_id}_kgtype_frame_arity"

    async def get_arity_map(self) -> Dict[str, FrameArityDTO]:
        """Bulk fetch all frame arity rows → {type_uri: dto}."""
        rows = await self.conn.fetch(f"SELECT * FROM {self._table}")
        return {r["type_uri"]: self._row_to_dto(r) for r in rows}

    async def set_frame_arity(
        self, type_uri: str, arity: str, *,
        source_slot_uri: Optional[str] = None,
        dest_slot_uri: Optional[str] = None,
        edge_label: Optional[str] = None,
        auto_computed: bool = False,
    ) -> FrameArityDTO:
        """Upsert arity classification for a frame type."""
        sql = f"""
            INSERT INTO {self._table}
                (type_uri, arity, source_slot_uri, dest_slot_uri,
                 edge_label, auto_computed)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (type_uri) DO UPDATE SET
                arity = EXCLUDED.arity,
                source_slot_uri = EXCLUDED.source_slot_uri,
                dest_slot_uri = EXCLUDED.dest_slot_uri,
                edge_label = EXCLUDED.edge_label,
                auto_computed = EXCLUDED.auto_computed,
                updated_time = CURRENT_TIMESTAMP
            RETURNING *
        """
        row = await self.conn.fetchrow(
            sql, type_uri, arity, source_slot_uri, dest_slot_uri,
            edge_label, auto_computed,
        )
        return self._row_to_dto(row)

    async def delete(self, type_uri: str) -> bool:
        result = await self.conn.execute(
            f"DELETE FROM {self._table} WHERE type_uri = $1", type_uri,
        )
        return result == "DELETE 1"


class NodeStyleManager:
    """CRUD on {space_id}_kgtype_node_style table."""

    def __init__(self, conn, space_id: str):
        self.conn = conn
        self._table = f"{space_id}_kgtype_node_style"

    async def get_all(self) -> Dict[str, NodeStyleDTO]:
        rows = await self.conn.fetch(f"SELECT * FROM {self._table}")
        return {r["type_uri"]: self._row_to_dto(r) for r in rows}

    async def upsert(self, type_uri: str, *, color: Optional[str] = None,
                     border_color: Optional[str] = None, shape: Optional[str] = None,
                     icon: Optional[str] = None, size: Optional[str] = None) -> NodeStyleDTO:
        sql = f"""
            INSERT INTO {self._table} (type_uri, color, border_color, shape, icon, size)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (type_uri) DO UPDATE SET
                color = EXCLUDED.color, border_color = EXCLUDED.border_color,
                shape = EXCLUDED.shape, icon = EXCLUDED.icon, size = EXCLUDED.size,
                updated_time = CURRENT_TIMESTAMP
            RETURNING *
        """
        row = await self.conn.fetchrow(sql, type_uri, color, border_color, shape, icon, size)
        return self._row_to_dto(row)

    async def delete(self, type_uri: str) -> bool:
        result = await self.conn.execute(
            f"DELETE FROM {self._table} WHERE type_uri = $1", type_uri,
        )
        return result == "DELETE 1"
```

Similar managers for `EdgeStyleManager` and `LabelConfigManager`.

---

## 6. REST Endpoints

### 6.1 Combined Visualization Config (read-only)

`GET /api/kgtype-mappings/viz-config?space_id=...`

Returns a single JSON map merging all config tables:

```json
{
  "frame_arity": {
    "http://vital.ai/ontology/wordnet#WordnetHyponymFrame": {
      "arity": "binary",
      "source_slot_uri": "urn:wordnet:sourceSlot",
      "dest_slot_uri": "urn:wordnet:destSlot",
      "edge_label": "Hyponym"
    },
    "http://example.org/EmploymentFrame": {
      "arity": "n_ary",
      "edge_label": null
    }
  },
  "node_style": {
    "http://vital.ai/ontology/wordnet#WordSense": {
      "color": "#4F46E5",
      "border_color": "#3730A3",
      "shape": "circle",
      "icon": "book",
      "size": "medium"
    }
  },
  "edge_style": {
    "http://vital.ai/ontology/wordnet#Edge_WordnetHyponym": {
      "color": "#10B981",
      "stroke_width": 2,
      "dash_pattern": "solid",
      "arrow_style": "triangle"
    }
  },
  "label_config": {
    "http://vital.ai/ontology/wordnet#WordSense": {
      "label_property": "http://vital.ai/ontology/vital-core#hasName",
      "subtitle_property": null,
      "tooltip_properties": [
        "http://vital.ai/ontology/haley-ai-kg#hasKGDescription"
      ]
    }
  }
}
```

Sections are omitted if the table is empty or not yet created.

### 6.2 Per-Table CRUD Endpoints

**Frame Arity:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /api/kgtype-mappings/frame-arity?space_id=...` | GET | Bulk fetch all frame arity rows |
| `PUT /api/kgtype-mappings/frame-arity?space_id=...` | PUT | Upsert arity for a frame type |
| `DELETE /api/kgtype-mappings/frame-arity?space_id=...&type_uri=...` | DELETE | Remove arity row |
| `POST /api/kgtype-mappings/auto-compute?space_id=...` | POST | Re-compute all arity from prototypes |

**Node Style:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /api/kgtype-mappings/node-style?space_id=...` | GET | Bulk fetch all node styles |
| `PUT /api/kgtype-mappings/node-style?space_id=...` | PUT | Upsert node style for a type |
| `DELETE /api/kgtype-mappings/node-style?space_id=...&type_uri=...` | DELETE | Remove node style |

**Edge Style:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /api/kgtype-mappings/edge-style?space_id=...` | GET | Bulk fetch all edge styles |
| `PUT /api/kgtype-mappings/edge-style?space_id=...` | PUT | Upsert edge style for a type |
| `DELETE /api/kgtype-mappings/edge-style?space_id=...&type_uri=...` | DELETE | Remove edge style |

### 6.3 Server-Side Implementation

The `viz-config` endpoint queries each table in parallel and merges:

```sql
-- Frame arity
SELECT type_uri, arity, source_slot_uri, dest_slot_uri, edge_label
FROM {space_id}_kgtype_frame_arity

-- Node styles
SELECT type_uri, color, border_color, shape, icon, size
FROM {space_id}_kgtype_node_style

-- Edge styles
SELECT type_uri, color, stroke_width, dash_pattern, arrow_style
FROM {space_id}_kgtype_edge_style

-- Label config (with tooltip join)
SELECT lc.type_uri, lc.label_property, lc.subtitle_property,
       lt.property_uri AS tooltip_property, lt.ordinal
FROM {space_id}_kgtype_label_config lc
LEFT JOIN {space_id}_kgtype_label_tooltip lt ON lt.config_id = lc.config_id
ORDER BY lc.type_uri, lt.ordinal
```

No SPARQL involved — direct table reads, sub-millisecond each.

### 6.4 Auto-Compute Arity from Prototypes

`POST /api/kgtype-mappings/auto-compute?space_id=...`

This endpoint derives frame arity from the KG prototype model (see
`prototype_kg_types_plan.md` for the prototype data model). When triggered:

1. Queries all `KGFrameProtoType` instances and their `Edge_hasKGSlotProtoType` edges
2. Classifies each slot as entity-referencing vs data-value using VitalSigns ontology
3. Upserts rows into `{space}_kgtype_frame_arity` with `auto_computed = TRUE`
4. Does NOT overwrite rows where `auto_computed = FALSE` (manual overrides preserved)

**Classification logic:**

```python
def compute_frame_arity(slot_prototypes: list) -> str:
    entity_slot_count = sum(
        1 for sp in slot_prototypes
        if is_entity_referencing_slot(sp)
    )
    if entity_slot_count == 2:
        return "binary"
    elif entity_slot_count >= 3:
        return "n_ary"
    else:
        return "unary"

def is_entity_referencing_slot(slot_proto) -> bool:
    """Check if slot prototype references entities/documents."""
    slot_type = slot_proto.kGSlotType  # URI to KGSlotType
    from vital_ai_vitalsigns.vitalsigns import VitalSigns
    vs = VitalSigns()
    ont = vs.get_ontology_manager()
    entity_slot_uris = ont.get_subclass_uri_list(
        "http://vital.ai/ontology/haley-ai-kg#KGEntitySlot"
    )
    uri_slot_uris = ont.get_subclass_uri_list(
        "http://vital.ai/ontology/haley-ai-kg#KGURISlot"
    )
    return slot_type in entity_slot_uris or slot_type in uri_slot_uris
```

**Arity values:**

| Value | Slot Count | Visualization |
|-------|------------|---------------|
| `binary` | 2 entity slots | Collapsed to single edge between entities |
| `n_ary` | 3+ entity/doc slots | Hub node with spokes to entities |
| `unary` | 0–1 entity slots | Badge on entity or hidden |

**Binary frame directionality:** Auto-compute also populates `source_slot_uri`
and `dest_slot_uri` from `Edge_hasKGSlotProtoType.kGSlotRoleSequence`
(seq 1 = source, seq 2 = dest). These can be manually overridden.

**SPARQL fallback:** If auto-compute has not been run, arity can be computed
on-the-fly:

```sparql
SELECT ?frameTypeUri (COUNT(?slotProto) AS ?entitySlotCount)
WHERE {
  ?frameProto a <http://vital.ai/ontology/haley-ai-kg#KGFrameProtoType> .
  ?frameProto <http://vital.ai/ontology/haley-ai-kg#hasKGFrameType> ?frameTypeUri .
  ?slotEdge a <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlotProtoType> .
  ?slotEdge <http://vital.ai/ontology/vital-core#hasEdgeSource> ?frameProto .
  ?slotEdge <http://vital.ai/ontology/vital-core#hasEdgeDestination> ?slotProto .
  ?slotProto <http://vital.ai/ontology/haley-ai-kg#hasKGSlotType> ?slotTypeUri .
  FILTER(?slotTypeUri IN (
    <http://vital.ai/ontology/haley-ai-kg#KGEntitySlot>,
    <http://vital.ai/ontology/haley-ai-kg#KGURISlot>
  ))
}
GROUP BY ?frameTypeUri
```

Then classify: count=2 → binary, count≥3 → n_ary, else → unary.

---

## 7. Graph Visualization Integration

### 7.1 Frontend Usage

1. **On visualization load**: `GET /api/kgtype-mappings/viz-config?space_id=...`
   → cache the entire response as `vizConfig`
2. **During expansion**: Look up `vizConfig.frame_arity[frameTypeUri]`
   - **binary** → collapse frame + 2 slots into a single directed edge
     (source/dest from row, label from `edge_label`)
   - **n_ary** → render frame as hub node with spokes
   - **unary** → badge/annotation on entity
   - **not found** → fallback to slot counting at query time
3. **During rendering**: Look up `vizConfig.node_style[typeUri]` and
   `vizConfig.edge_style[typeUri]` for colors, shapes, icons, stroke widths

---

## 8. Implementation Phases

### Phase 1 — Frame Arity Table + viz-config Endpoint
- Add `{space}_kgtype_frame_arity` table to `sparql_sql_schema.py`
- Add migration script for existing spaces (same pattern as `migrate_vector_geo_schema.py`)
- Implement `FrameArityManager`
- Implement `GET /api/kgtype-mappings/viz-config` (returns `frame_arity` section only)
- Implement `PUT`/`DELETE` for frame-arity CRUD
- Wire graph visualization to fetch viz-config on load and use for binary collapse
- Manually set mappings work immediately (no prototype data required)

### Phase 2 — Style Tables + Style Editor UI
- Add `{space}_kgtype_node_style` and `{space}_kgtype_edge_style` tables
- Implement `NodeStyleManager` and `EdgeStyleManager`
- Extend `viz-config` endpoint to include `node_style` and `edge_style` sections
- Build style editor UI (color pickers, shape selectors, icon selection)
- Graph visualization applies styles from viz-config during rendering

### Phase 3 — Label/Tooltip Config + Future Tables
- Add `{space}_kgtype_label_config` and `{space}_kgtype_label_tooltip` tables
- Build label/tooltip configuration UI
- Add additional tables as needed (grouping, visibility)

---

## 9. Related Documents

- `planning_visualization/graph_visualization_plan.md` — visualization philosophy, frame collapse, expansion behavior
- `planning_visualization/prototype_kg_types_plan.md` — prototype data model, prototype editor UI
- `vitalgraph/vectorization/mapping_manager.py` — existing MappingManager pattern
- `vitalgraph/db/sparql_sql/sparql_sql_schema.py` — table creation location
