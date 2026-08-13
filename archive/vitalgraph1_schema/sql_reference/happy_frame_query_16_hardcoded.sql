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
          WHERE plainto_tsquery('house') @@ t.term_text_fts
      )
),
-- Slot data with entity information
slot_data AS (
    SELECT DISTINCT
        q1.subject_uuid as slot_uuid,
        q1.object_uuid as entity_uuid,
        q2.object_uuid as slot_type
    FROM vitalgraph1__wordnet_frames__rdf_quad_unlogged q1
    JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged q2 ON q2.subject_uuid = q1.subject_uuid
    JOIN happy_entities he ON he.entity_uuid = q1.object_uuid
    WHERE q1.predicate_uuid = '87a0a946-3150-5b4a-852f-84ce8e37e29f'::uuid  -- has_entity_slot_value_uuid
      AND q2.predicate_uuid = 'e263c804-e3b0-5bdf-968c-82e536f5effe'::uuid  -- has_slot_type_uuid
      AND q2.object_uuid IN ('3dd13e9e-4f51-5a18-9654-7ec814d02ba7'::uuid,  -- has_source_entity_uuid
                             'd1daebbc-ca1e-5ff6-baad-bd88487575d9'::uuid)   -- has_destination_entity_uuid
),
-- Use materialized view for edge structure (replacing expensive CTE)
edge_structure AS (
    SELECT 
        source_node_uuid as frame_uuid,
        dest_node_uuid as slot_uuid
    FROM vitalgraph1__wordnet_frames__edge_relationships_mv
),
-- OPTIMIZED: Direct aggregation without JSON overhead
frame_aggregated AS (
    SELECT 
        es.frame_uuid,
        -- Use conditional aggregation with string conversion for UUIDs
        (MAX(CASE WHEN sd.slot_type = '3dd13e9e-4f51-5a18-9654-7ec814d02ba7'::uuid 
             THEN sd.slot_uuid::text END))::uuid as source_slot_uuid,
        (MAX(CASE WHEN sd.slot_type = 'd1daebbc-ca1e-5ff6-baad-bd88487575d9'::uuid 
             THEN sd.slot_uuid::text END))::uuid as dest_slot_uuid,
        (MAX(CASE WHEN sd.slot_type = '3dd13e9e-4f51-5a18-9654-7ec814d02ba7'::uuid 
             THEN sd.entity_uuid::text END))::uuid as source_entity_uuid,
        (MAX(CASE WHEN sd.slot_type = 'd1daebbc-ca1e-5ff6-baad-bd88487575d9'::uuid 
             THEN sd.entity_uuid::text END))::uuid as dest_entity_uuid,
        -- Count distinct slot types to ensure we have both source and dest
        COUNT(DISTINCT sd.slot_type) as slot_type_count
    FROM edge_structure es
    JOIN slot_data sd ON sd.slot_uuid = es.slot_uuid
    GROUP BY es.frame_uuid
    HAVING COUNT(DISTINCT sd.slot_type) = 2  -- Must have both source and dest
)
-- OPTIMIZED: Return UUIDs directly for cache-based resolution
SELECT 
    -- Return UUIDs that will be resolved via cache
    COALESCE(fa.source_entity_uuid, fa.dest_entity_uuid) as entity_uuid,
    fa.frame_uuid,
    fa.source_slot_uuid,
    fa.dest_slot_uuid,
    fa.source_entity_uuid,
    fa.dest_entity_uuid
FROM frame_aggregated fa
ORDER BY entity_uuid
LIMIT 500 OFFSET 0;

COMMIT;
