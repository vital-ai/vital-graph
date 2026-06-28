# Snowflake Incremental Wide Table: Streams + Tasks + Dynamic SQL

## Overview

Transform normalized RDF quad storage (term + quad tables) into denormalized wide tables on Snowflake, with incremental column addition via `ALTER TABLE ADD COLUMN` as new predicates appear.

This uses a regular table (not a Dynamic Table), so full DDL is supported.

## Source Tables

```sql
-- Term lookup
sp_sql_lead_dataset_term:
  term_uuid
  term_text

-- Quad storage
sp_sql_lead_dataset_rdf_quad:
  context_uuid
  subject_uuid
  predicate_uuid
  object_uuid
```

## Target Tables

```sql
-- Wide table starts with just the primary key
CREATE TABLE sp_sql_lead_dataset_graph_1 (
  id STRING PRIMARY KEY
);

-- Column registry
CREATE TABLE column_mapping (
  graph_id STRING,
  predicate_uri STRING,
  col_name STRING,
  display_name STRING,
  data_type STRING DEFAULT 'STRING',
  assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  PRIMARY KEY (graph_id, predicate_uri)
);

-- CDC stream
CREATE STREAM quad_changes
  ON TABLE sp_sql_lead_dataset_rdf_quad
  SHOW_INITIAL_ROWS = TRUE;
```

## Stored Procedure

```sql
CREATE OR REPLACE PROCEDURE refresh_graph_table(graph_id STRING)
RETURNS STRING
LANGUAGE SQL
AS
$$
DECLARE
  merge_sql STRING;
  update_set STRING;
  insert_cols STRING;
  insert_vals STRING;
  pivot_cols STRING;
  new_pred STRING;
  next_col STRING;
  col_count INT;
  new_count INT DEFAULT 0;
  c CURSOR FOR
    -- Find predicates in the stream with no column assignment yet
    SELECT DISTINCT p.term_text AS predicate_uri
    FROM quad_changes q
    JOIN sp_sql_lead_dataset_term c ON q.context_uuid = c.term_uuid
    JOIN sp_sql_lead_dataset_term p ON q.predicate_uuid = p.term_uuid
    WHERE c.term_text = :graph_id
      AND q.METADATA$ACTION = 'INSERT'
      AND p.term_text NOT IN (
        SELECT predicate_uri FROM column_mapping WHERE graph_id = :graph_id
      );
BEGIN
  -- ============================================================
  -- PHASE 1: Add columns for NEW predicates
  -- ============================================================
  FOR rec IN c DO
    -- Determine next column name
    SELECT COUNT(*) INTO :col_count
    FROM column_mapping WHERE graph_id = :graph_id;

    LET next_col := 'c' || LPAD((:col_count + 1)::STRING, 4, '0');

    -- Add the physical column to the table
    EXECUTE IMMEDIATE
      'ALTER TABLE sp_sql_lead_dataset_' || :graph_id ||
      ' ADD COLUMN ' || :next_col || ' STRING';

    -- Register in mapping
    INSERT INTO column_mapping (graph_id, predicate_uri, col_name, display_name)
    VALUES (:graph_id, rec.predicate_uri, :next_col, rec.predicate_uri);

    new_count := :new_count + 1;
  END FOR;

  -- ============================================================
  -- PHASE 2: Build pivot expressions (only assigned columns)
  -- ============================================================
  SELECT LISTAGG(
    'MAX(CASE WHEN p.term_text = ''' || predicate_uri ||
    ''' THEN o.term_text END) AS ' || col_name,
    ', '
  ) INTO :pivot_cols
  FROM column_mapping
  WHERE graph_id = :graph_id
  ORDER BY col_name;

  -- ============================================================
  -- PHASE 3: Build MERGE clauses
  -- ============================================================
  SELECT LISTAGG(
    'tgt.' || col_name || ' = COALESCE(src.' || col_name || ', tgt.' || col_name || ')',
    ', '
  ) INTO :update_set
  FROM column_mapping WHERE graph_id = :graph_id;

  SELECT LISTAGG(col_name, ', ')
  INTO :insert_cols
  FROM column_mapping WHERE graph_id = :graph_id;

  SELECT LISTAGG('src.' || col_name, ', ')
  INTO :insert_vals
  FROM column_mapping WHERE graph_id = :graph_id;

  -- ============================================================
  -- PHASE 4: Assemble and execute MERGE
  -- ============================================================
  merge_sql := '
    MERGE INTO sp_sql_lead_dataset_' || :graph_id || ' tgt
    USING (
      WITH changes AS (
        SELECT q.*,
               q.METADATA$ACTION AS action,
               q.METADATA$ISUPDATE AS is_update
        FROM quad_changes q
        JOIN sp_sql_lead_dataset_term ctx ON q.context_uuid = ctx.term_uuid
        WHERE ctx.term_text = ''' || :graph_id || '''
      ),
      deleted_subjects AS (
        SELECT DISTINCT s.term_text AS id
        FROM changes ch
        JOIN sp_sql_lead_dataset_term s ON ch.subject_uuid = s.term_uuid
        WHERE ch.action = ''DELETE'' AND ch.is_update = FALSE
        EXCEPT
        SELECT DISTINCT s.term_text
        FROM changes ch
        JOIN sp_sql_lead_dataset_term s ON ch.subject_uuid = s.term_uuid
        WHERE ch.action = ''INSERT''
      ),
      pivoted AS (
        SELECT s.term_text AS id, ' || :pivot_cols || '
        FROM changes ch
        JOIN sp_sql_lead_dataset_term s ON ch.subject_uuid = s.term_uuid
        JOIN sp_sql_lead_dataset_term p ON ch.predicate_uuid = p.term_uuid
        JOIN sp_sql_lead_dataset_term o ON ch.object_uuid = o.term_uuid
        WHERE ch.action = ''INSERT''
        GROUP BY s.term_text
      )
      SELECT * FROM pivoted
    ) src
    ON tgt.id = src.id
    WHEN MATCHED AND src.id IN (SELECT id FROM deleted_subjects) THEN DELETE
    WHEN MATCHED THEN UPDATE SET ' || :update_set || '
    WHEN NOT MATCHED THEN INSERT (id, ' || :insert_cols || ')
      VALUES (src.id, ' || :insert_vals || ')
  ';

  EXECUTE IMMEDIATE :merge_sql;

  RETURN 'Refreshed ' || :graph_id ||
    ': ' || :new_count || ' new columns added, ' ||
    (SELECT COUNT(*) FROM column_mapping WHERE graph_id = :graph_id) ||
    ' total columns';
END;
$$;
```

## Task

```sql
CREATE TASK refresh_graph_1
  WAREHOUSE = my_wh
  SCHEDULE = '1 MINUTE'
  WHEN SYSTEM$STREAM_HAS_DATA('quad_changes')
AS
  CALL refresh_graph_table('graph_1');

ALTER TASK refresh_graph_1 RESUME;
```

## Behavior on Each Run

| Event | Phase 1 (schema) | Phase 2-4 (data) |
|---|---|---|
| Existing predicates, new quads | No-op (cursor returns 0 rows) | MERGE upserts/deletes rows |
| New predicate appears | `ALTER TABLE ADD COLUMN` + mapping insert | MERGE includes the new column |
| Subject deleted | No-op | MERGE deletes the row |
| No changes | Task doesn't fire | — |

## Timeline Example

```
t=0  Table has: id
     Mapping: (empty)

t=1  Quads arrive: hasName, hasType, hasDollarAmount
     → Phase 1: ALTER ADD c0001, c0002, c0003
     → Phase 4: MERGE inserts rows with 3 columns populated

t=2  Quads arrive: hasColor (new predicate) + more hasName data
     → Phase 1: ALTER ADD c0004
     → Phase 4: MERGE updates existing rows, inserts new ones
       (c0001-c0003 updated normally, c0004 populated for first time)

t=3  Quads arrive: only existing predicates
     → Phase 1: no-op
     → Phase 4: MERGE only
```

## Edge Cases

### Partial Updates

If only one predicate changes for a subject, the pivot's `MAX(CASE WHEN ...)` returns NULL for unchanged columns. The MERGE UPDATE would overwrite good data with NULL.

Fix: use `COALESCE` in the UPDATE SET (already included in the procedure above):

```sql
-- Instead of:  tgt.c0001 = src.c0001
-- Generate:    tgt.c0001 = COALESCE(src.c0001, tgt.c0001)

SELECT LISTAGG(
  'tgt.' || col_name || ' = COALESCE(src.' || col_name || ', tgt.' || col_name || ')',
  ', '
) INTO :update_set
FROM column_mapping WHERE graph_id = :graph_id;
```

This ensures unchanged columns retain their existing values.

### Multi-Graph

If the quad table serves multiple graphs, create one Task per graph, or a parent Task that iterates:

```sql
CREATE TASK refresh_all_graphs ...
AS
BEGIN
  FOR rec IN (SELECT DISTINCT graph_id FROM column_mapping) DO
    CALL refresh_graph_table(rec.graph_id);
  END FOR;
END;
```

## Alternatives Considered

| Approach | Schema changes | Incremental cost | Complexity |
|---|---|---|---|
| **Dynamic Table (fixed columns)** | Requires `CREATE OR REPLACE` (full rebuild) | Low after rebuild | Low |
| **Dynamic Table (VARIANT + View)** | View recreation only (instant, no rebuild) | Always incremental | Medium |
| **Pre-allocated 1,000 columns** | Mapping update only | 1,000 CASE exprs per refresh | Medium |
| **Incremental ADD COLUMN (this plan)** | `ALTER TABLE` (instant, metadata-only) | Only active columns in MERGE | Medium |
| **Streams + Tasks + manual MERGE** | `ALTER TABLE` works natively | You manage it | High |

### Why Incremental ADD COLUMN

- No phantom columns or arbitrary ceiling
- `ALTER TABLE ADD COLUMN` is metadata-only in Snowflake (instant, no data rewrite)
- MERGE SQL only touches assigned columns (no wasted compute)
- Snowflake limit: ~2,000 columns per table (sufficient for most predicate sets)
