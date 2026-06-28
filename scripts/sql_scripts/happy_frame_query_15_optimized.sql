-- Optimized PostgreSQL Frame Query - Eliminates JSON aggregation and UUID-to-URI JOINs
-- Focus: Optimize Final Join Processing bottleneck (~230ms reduction target)

BEGIN;

-- Enable timing for performance measurement
\timing on

-- Constants for ontology URIs (will be cached in production)
WITH constants AS (
    SELECT 
        t1.term_uuid as rdf_type_uuid,
        t2.term_uuid as kg_entity_uuid,
        t3.term_uuid as has_description_uuid,
        t4.term_uuid as has_entity_slot_value_uuid,
        t5.term_uuid as has_slot_type_uuid,
        t6.term_uuid as has_edge_source_uuid,
        t7.term_uuid as has_edge_destination_uuid,
        t8.term_uuid as graph_uuid,
        t9.term_uuid as has_source_entity_uuid,
        t10.term_uuid as has_destination_entity_uuid
    FROM 
        vitalgraph1__wordnet_frames__term_unlogged t1,
        vitalgraph1__wordnet_frames__term_unlogged t2,
        vitalgraph1__wordnet_frames__term_unlogged t3,
        vitalgraph1__wordnet_frames__term_unlogged t4,
        vitalgraph1__wordnet_frames__term_unlogged t5,
        vitalgraph1__wordnet_frames__term_unlogged t6,
        vitalgraph1__wordnet_frames__term_unlogged t7,
        vitalgraph1__wordnet_frames__term_unlogged t8,
        vitalgraph1__wordnet_frames__term_unlogged t9,
        vitalgraph1__wordnet_frames__term_unlogged t10
    WHERE t1.term_text = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
      AND t2.term_text = 'http://vital.ai/ontology/haley-ai-kg#KGEntity'
      AND t3.term_text = 'http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription'
      AND t4.term_text = 'http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue'
      AND t5.term_text = 'http://vital.ai/ontology/haley-ai-kg#hasKGSlotType'
      AND t6.term_text = 'http://vital.ai/ontology/vital-core#hasEdgeSource'
      AND t7.term_text = 'http://vital.ai/ontology/vital-core#hasEdgeDestination'
      AND t8.term_text = 'http://vital.ai/graph/kgwordnetframes'
      AND t9.term_text = 'urn:hasSourceEntity'
      AND t10.term_text = 'urn:hasDestinationEntity'
),
-- Happy entities with "happy" in description
happy_entities AS (
    SELECT DISTINCT q1.subject_uuid as entity_uuid
    FROM vitalgraph1__wordnet_frames__rdf_quad_unlogged q1
    CROSS JOIN constants
    WHERE q1.predicate_uuid = constants.has_description_uuid
      AND q1.object_uuid IN (
          SELECT t.term_uuid 
          FROM vitalgraph1__wordnet_frames__term_unlogged t
          WHERE plainto_tsquery('happy') @@ t.term_text_fts
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
    CROSS JOIN constants
    WHERE q1.predicate_uuid = constants.has_entity_slot_value_uuid
      AND q2.predicate_uuid = constants.has_slot_type_uuid
      AND q2.object_uuid IN (constants.has_source_entity_uuid, constants.has_destination_entity_uuid)
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
        (MAX(CASE WHEN sd.slot_type = constants.has_source_entity_uuid THEN sd.slot_uuid::text END))::uuid as source_slot_uuid,
        (MAX(CASE WHEN sd.slot_type = constants.has_destination_entity_uuid THEN sd.slot_uuid::text END))::uuid as dest_slot_uuid,
        (MAX(CASE WHEN sd.slot_type = constants.has_source_entity_uuid THEN sd.entity_uuid::text END))::uuid as source_entity_uuid,
        (MAX(CASE WHEN sd.slot_type = constants.has_destination_entity_uuid THEN sd.entity_uuid::text END))::uuid as dest_entity_uuid,
        -- Count distinct slot types to ensure we have both source and dest
        COUNT(DISTINCT sd.slot_type) as slot_type_count
    FROM edge_structure es
    JOIN slot_data sd ON sd.slot_uuid = es.slot_uuid
    CROSS JOIN constants
    GROUP BY es.frame_uuid, constants.has_source_entity_uuid, constants.has_destination_entity_uuid
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
