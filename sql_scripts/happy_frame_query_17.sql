-- Ultra-Optimized PostgreSQL Frame Query - Hardcoded Constants + No UUID-to-URI JOINs
-- Eliminates constants CTE overhead and all term table JOINs for maximum performance

BEGIN;

-- Enable timing for performance measurement
\timing on

-- Hardcoded constants (extracted from get_constants.sql)
-- These would come from cache in production
-- rdf_type_uuid: f947f06c-bd0c-5ae0-bcd6-6db005605b0a
-- kg_entity_uuid: 2d50120b-1fe8-5aed-bea8-cf3fa0acec45
-- has_description_uuid: 1e7843d3-ac11-5ba9-9d19-92274c1e48a6
-- has_entity_slot_value_uuid: 87a0a946-3150-5b4a-852f-84ce8e37e29f
-- has_slot_type_uuid: e263c804-e3b0-5bdf-968c-82e536f5effe
-- has_edge_source_uuid: c7ef9fd3-8e1a-5ad8-afe5-069a76b889e2
-- has_edge_destination_uuid: 57fdaf9c-79ba-5cbd-893e-d6eeb0b84eb9
-- graph_uuid: 647097a7-9e47-5fee-8c12-6b92df9347b7
-- has_source_entity_uuid: 3dd13e9e-4f51-5a18-9654-7ec814d02ba7
-- has_destination_entity_uuid: d1daebbc-ca1e-5ff6-baad-bd88487575d9

WITH
-- Happy entities with "happy" in description
happy_entities AS (
    SELECT DISTINCT q1.subject_uuid as entity_uuid
    FROM vitalgraph1__wordnet_frames__rdf_quad_unlogged q1
    WHERE q1.predicate_uuid = '1e7843d3-ac11-5ba9-9d19-92274c1e48a6'::uuid  -- has_description_uuid
      AND q1.object_uuid IN (
          SELECT t.term_uuid 
          FROM vitalgraph1__wordnet_frames__term_unlogged t
          WHERE plainto_tsquery('happy') @@ t.term_text_fts
      )
),
-- Optimized slot data - only include slots with matching "happy" entities (early filtering)
slot_data AS (
    SELECT 
        q1.subject_uuid as slot_uuid,
        q1.object_uuid as entity_uuid,
        CASE WHEN q2.object_uuid = '3dd13e9e-4f51-5a18-9654-7ec814d02ba7'::uuid THEN 'source'
             WHEN q2.object_uuid = 'd1daebbc-ca1e-5ff6-baad-bd88487575d9'::uuid THEN 'dest'
             ELSE NULL END as slot_type,
        -- All entities match by definition (due to INNER JOIN)
        1 as is_matching_entity
    FROM vitalgraph1__wordnet_frames__rdf_quad_unlogged q1
    JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged q2 ON q2.subject_uuid = q1.subject_uuid
    JOIN happy_entities he ON he.entity_uuid = q1.object_uuid  -- INNER JOIN = early filter!
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
-- Efficient aggregation like query 16
frame_aggregated AS (
    SELECT 
        es.frame_uuid,
        (array_agg(sd.slot_uuid) FILTER (WHERE sd.slot_type = 'source'))[1] as source_slot_uuid,
        (array_agg(sd.entity_uuid) FILTER (WHERE sd.slot_type = 'source'))[1] as source_entity_uuid,
        (array_agg(sd.slot_uuid) FILTER (WHERE sd.slot_type = 'dest'))[1] as dest_slot_uuid,
        (array_agg(sd.entity_uuid) FILTER (WHERE sd.slot_type = 'dest'))[1] as dest_entity_uuid,
        -- Simple flags for matching entities
        MAX(CASE WHEN sd.slot_type = 'source' AND sd.is_matching_entity = 1 THEN 1 ELSE 0 END) as source_matches_happy,
        MAX(CASE WHEN sd.slot_type = 'dest' AND sd.is_matching_entity = 1 THEN 1 ELSE 0 END) as dest_matches_happy
    FROM edge_structure es
    JOIN slot_data sd ON sd.slot_uuid = es.slot_uuid
    GROUP BY es.frame_uuid
    HAVING (array_agg(sd.entity_uuid) FILTER (WHERE sd.slot_type = 'source'))[1] IS NOT NULL
       AND (array_agg(sd.entity_uuid) FILTER (WHERE sd.slot_type = 'dest'))[1] IS NOT NULL
)
-- UNION: Mirror the SPARQL UNION structure exactly
-- Solution 1: Bind ?entity to SOURCE entity when it matches "happy"
SELECT 
    fa.source_entity_uuid as entity_uuid,
    fa.frame_uuid,
    fa.source_slot_uuid,
    fa.dest_slot_uuid,
    fa.source_entity_uuid,
    fa.dest_entity_uuid
FROM frame_aggregated fa
WHERE fa.source_matches_happy = 1

UNION ALL

-- Solution 2: Bind ?entity to DESTINATION entity when it matches "happy"
SELECT 
    fa.dest_entity_uuid as entity_uuid,
    fa.frame_uuid,
    fa.source_slot_uuid,
    fa.dest_slot_uuid,
    fa.source_entity_uuid,
    fa.dest_entity_uuid
FROM frame_aggregated fa
WHERE fa.dest_matches_happy = 1

ORDER BY entity_uuid
LIMIT 500 OFFSET 0;

COMMIT;
