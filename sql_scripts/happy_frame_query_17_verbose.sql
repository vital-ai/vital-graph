-- Verbose version with detailed execution plan
BEGIN;

-- late filtering case

-- Enable all logging for this session
-- SET log_min_duration_statement = 0;
-- SET log_statement = 'all';
\timing on

-- Show the execution plan
-- EXPLAIN (ANALYZE, BUFFERS, TIMING, VERBOSE)
WITH
-- Entities matching "man" in description (for low-selectivity case)
man_entities AS (
    SELECT DISTINCT q1.subject_uuid as entity_uuid
    FROM vitalgraph1__wordnet_frames__rdf_quad_unlogged q1
    WHERE q1.predicate_uuid = '1e7843d3-ac11-5ba9-9d19-92274c1e48a6'::uuid  -- has_description_uuid
      AND q1.object_uuid IN (
          SELECT t.term_uuid 
          FROM vitalgraph1__wordnet_frames__term_unlogged t
          WHERE plainto_tsquery('man') @@ t.term_text_fts
      )
),
-- Traditional slot data - NO early filtering for low-selectivity cases
slot_data AS (
    SELECT 
        q1.subject_uuid as slot_uuid,
        q1.object_uuid as entity_uuid,
        CASE WHEN q2.object_uuid = '3dd13e9e-4f51-5a18-9654-7ec814d02ba7'::uuid THEN 'source'
             WHEN q2.object_uuid = 'd1daebbc-ca1e-5ff6-baad-bd88487575d9'::uuid THEN 'dest'
             ELSE NULL END as slot_type
    FROM vitalgraph1__wordnet_frames__rdf_quad_unlogged q1
    JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged q2 ON q2.subject_uuid = q1.subject_uuid
    -- NO JOIN with man_entities here - process all slots first!
    WHERE q1.predicate_uuid = '87a0a946-3150-5b4a-852f-84ce8e37e29f'::uuid  -- has_entity_slot_value_uuid
      AND q2.predicate_uuid = 'e263c804-e3b0-5bdf-968c-82e536f5effe'::uuid  -- has_slot_type_uuid
      AND q2.object_uuid IN ('3dd13e9e-4f51-5a18-9654-7ec814d02ba7'::uuid, 'd1daebbc-ca1e-5ff6-baad-bd88487575d9'::uuid)
),
edge_structure AS (
    SELECT 
        source_node_uuid as frame_uuid,
        dest_node_uuid as slot_uuid
    FROM vitalgraph1__wordnet_frames__edge_relationships_mv
),
-- Aggregation without entity matching flags (applied later)
frame_aggregated AS (
    SELECT 
        es.frame_uuid,
        (array_agg(sd.slot_uuid) FILTER (WHERE sd.slot_type = 'source'))[1] as source_slot_uuid,
        (array_agg(sd.entity_uuid) FILTER (WHERE sd.slot_type = 'source'))[1] as source_entity_uuid,
        (array_agg(sd.slot_uuid) FILTER (WHERE sd.slot_type = 'dest'))[1] as dest_slot_uuid,
        (array_agg(sd.entity_uuid) FILTER (WHERE sd.slot_type = 'dest'))[1] as dest_entity_uuid
    FROM edge_structure es
    JOIN slot_data sd ON sd.slot_uuid = es.slot_uuid
    GROUP BY es.frame_uuid
    HAVING (array_agg(sd.entity_uuid) FILTER (WHERE sd.slot_type = 'source'))[1] IS NOT NULL
       AND (array_agg(sd.entity_uuid) FILTER (WHERE sd.slot_type = 'dest'))[1] IS NOT NULL
)
-- UNION: Apply entity filter at the END (late filtering)
-- Solution 1: Bind ?entity to SOURCE entity when it matches "man"
SELECT 
    fa.source_entity_uuid as entity_uuid,
    fa.frame_uuid,
    fa.source_slot_uuid,
    fa.dest_slot_uuid,
    fa.source_entity_uuid,
    fa.dest_entity_uuid
FROM frame_aggregated fa
WHERE EXISTS (
    SELECT 1 FROM man_entities me 
    WHERE me.entity_uuid = fa.source_entity_uuid
)

UNION ALL

-- Solution 2: Bind ?entity to DESTINATION entity when it matches "man"
SELECT 
    fa.dest_entity_uuid as entity_uuid,
    fa.frame_uuid,
    fa.source_slot_uuid,
    fa.dest_slot_uuid,
    fa.source_entity_uuid,
    fa.dest_entity_uuid
FROM frame_aggregated fa
WHERE EXISTS (
    SELECT 1 FROM man_entities me 
    WHERE me.entity_uuid = fa.dest_entity_uuid
)

ORDER BY entity_uuid
LIMIT 500 OFFSET 0;

COMMIT;
