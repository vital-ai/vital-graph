-- Optimized frame query using materialized view ONLY for edge_structure
-- All other logic remains identical to working happy_frame_query_5.sql

BEGIN;
SET work_mem = '1GB';
SET enable_nestloop = off;
SET enable_mergejoin = off;
SET enable_hashjoin = on;
SET random_page_cost = 1.1;
SET seq_page_cost = 1.0;

WITH constants AS (
    SELECT
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged 
         WHERE term_text = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type' LIMIT 1) AS rdf_type_uuid,
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged 
         WHERE term_text = 'http://vital.ai/ontology/haley-ai-kg#KGEntity' LIMIT 1) AS kg_entity_uuid,
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged 
         WHERE term_text = 'http://vital.ai/ontology/vital-core#hasName' LIMIT 1) AS has_name_uuid,
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged 
         WHERE term_text = 'http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription' LIMIT 1) AS has_description_uuid,
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged 
         WHERE term_text = 'http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue' LIMIT 1) AS has_entity_slot_value_uuid,
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged 
         WHERE term_text = 'http://vital.ai/ontology/haley-ai-kg#hasKGSlotType' LIMIT 1) AS has_slot_type_uuid,
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged 
         WHERE term_text = 'http://vital.ai/ontology/vital-core#hasEdgeSource' LIMIT 1) AS has_edge_source_uuid,
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged 
         WHERE term_text = 'http://vital.ai/ontology/vital-core#hasEdgeDestination' LIMIT 1) AS has_edge_destination_uuid,
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged 
         WHERE term_text = 'http://vital.ai/graph/kgwordnetframes' LIMIT 1) AS graph_uuid,
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged 
         WHERE term_text = 'urn:hasSourceEntity' LIMIT 1) AS has_source_entity_uuid,
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged 
         WHERE term_text = 'urn:hasDestinationEntity' LIMIT 1) AS has_destination_entity_uuid
),
-- Find all happy entities efficiently
happy_entities AS MATERIALIZED (
    SELECT DISTINCT q1.subject_uuid as entity_uuid
    FROM constants
    JOIN vitalgraph1__wordnet_frames__term_unlogged obj
        ON obj.term_text_fts @@ plainto_tsquery('english', 'happy')
        AND obj.term_type = 'L'
    JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged q1 
        ON q1.object_uuid = obj.term_uuid
    WHERE q1.predicate_uuid = constants.has_description_uuid
        AND q1.context_uuid = constants.graph_uuid
        AND EXISTS (
            SELECT 1 FROM vitalgraph1__wordnet_frames__rdf_quad_unlogged q2
            WHERE q2.subject_uuid = q1.subject_uuid
            AND q2.predicate_uuid = constants.rdf_type_uuid
            AND q2.object_uuid = constants.kg_entity_uuid
            AND q2.context_uuid = constants.graph_uuid
        )
),
-- OPTIMIZED: Use materialized view instead of expensive edge_structure CTE
edge_structure AS MATERIALIZED (
    SELECT 
        edge_uuid,
        source_node_uuid as frame_uuid,
        dest_node_uuid as slot_uuid
    FROM vitalgraph1__wordnet_frames__edge_relationships_mv
),
-- Get slot types and entities with early happy entity filtering
slot_data AS MATERIALIZED (
    SELECT DISTINCT
        slot.subject_uuid as slot_uuid,
        type.object_uuid as slot_type,
        entity.object_uuid as entity_uuid
    FROM constants
    -- Start with happy entities to drastically reduce search space
    JOIN happy_entities he ON true  -- Cross join with small happy entities set
    -- Join entity table first, filtered by happy entities
    JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged entity
        ON entity.object_uuid = he.entity_uuid
        AND entity.predicate_uuid = constants.has_entity_slot_value_uuid
        AND entity.context_uuid = constants.graph_uuid
    -- Then join slot table
    JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged slot
        ON slot.subject_uuid = entity.subject_uuid
        AND slot.context_uuid = constants.graph_uuid
    -- Finally join slot type
    JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged type
        ON type.subject_uuid = slot.subject_uuid
        AND type.predicate_uuid = constants.has_slot_type_uuid
        AND type.context_uuid = constants.graph_uuid
        AND type.object_uuid IN (constants.has_source_entity_uuid, constants.has_destination_entity_uuid)
),
-- Combine edge structure with slot data
final_results AS (
    SELECT 
        es.frame_uuid,
        sd.entity_uuid,
        es.slot_uuid,
        sd.slot_type
    FROM edge_structure es
    JOIN slot_data sd ON sd.slot_uuid = es.slot_uuid
),
-- Aggregate results by frame and entity
aggregated_results AS (
    SELECT 
        fr.frame_uuid,
        fr.entity_uuid,
        COUNT(*) as entity_count,
        STRING_AGG(CASE WHEN fr.slot_type = constants.has_source_entity_uuid THEN fr.entity_uuid::text END, ', ') as source_entities,
        STRING_AGG(CASE WHEN fr.slot_type = constants.has_destination_entity_uuid THEN fr.entity_uuid::text END, ', ') as dest_entities
    FROM final_results fr, constants
    GROUP BY fr.frame_uuid, fr.entity_uuid
)
-- Final output with names
SELECT 
    frame_term.term_text as frame_uuid,
    frame_name.term_text as frame_name,
    ar.entity_count,
    ar.source_entities,
    ar.dest_entities,
    source_names.names as source_entity_names,
    dest_names.names as dest_entity_names
FROM aggregated_results ar
JOIN constants ON true
-- Get frame info
JOIN vitalgraph1__wordnet_frames__term_unlogged frame_term 
    ON frame_term.term_uuid = ar.frame_uuid
LEFT JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged frame_name_quad
    ON frame_name_quad.subject_uuid = ar.frame_uuid
    AND frame_name_quad.predicate_uuid = constants.has_name_uuid
    AND frame_name_quad.context_uuid = constants.graph_uuid
LEFT JOIN vitalgraph1__wordnet_frames__term_unlogged frame_name
    ON frame_name.term_uuid = frame_name_quad.object_uuid
-- Get source entity names
LEFT JOIN LATERAL (
    SELECT STRING_AGG(name_term.term_text, ', ') as names
    FROM unnest(string_to_array(ar.source_entities, ', ')) as source_uuid_text
    JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged name_quad
        ON name_quad.subject_uuid = source_uuid_text::uuid
        AND name_quad.predicate_uuid = constants.has_name_uuid
        AND name_quad.context_uuid = constants.graph_uuid
    JOIN vitalgraph1__wordnet_frames__term_unlogged name_term
        ON name_term.term_uuid = name_quad.object_uuid
    WHERE ar.source_entities IS NOT NULL
) source_names ON true
-- Get dest entity names  
LEFT JOIN LATERAL (
    SELECT STRING_AGG(name_term.term_text, ', ') as names
    FROM unnest(string_to_array(ar.dest_entities, ', ')) as dest_uuid_text
    JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged name_quad
        ON name_quad.subject_uuid = dest_uuid_text::uuid
        AND name_quad.predicate_uuid = constants.has_name_uuid
        AND name_quad.context_uuid = constants.graph_uuid
    JOIN vitalgraph1__wordnet_frames__term_unlogged name_term
        ON name_term.term_uuid = name_quad.object_uuid
    WHERE ar.dest_entities IS NOT NULL
) dest_names ON true
ORDER BY frame_term.term_text, ar.entity_count DESC
LIMIT 10 OFFSET 0;

COMMIT;
