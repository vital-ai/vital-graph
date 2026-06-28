-- Optimized frame query using the edge relationships materialized view
-- This leverages the pre-computed edge traversals for maximum performance

SET work_mem = '1GB';

WITH constants AS (
    SELECT 
        t1.term_uuid as rdf_type_uuid,
        t2.term_uuid as kg_entity_uuid,
        t3.term_uuid as has_name_uuid,
        t4.term_uuid as has_description_uuid,
        t5.term_uuid as has_entity_slot_value_uuid,
        t6.term_uuid as has_slot_type_uuid,
        t7.term_uuid as has_source_entity_uuid,
        t8.term_uuid as has_destination_entity_uuid,
        t9.term_uuid as graph_uuid
    FROM vitalgraph1__wordnet_frames__term_unlogged t1,
         vitalgraph1__wordnet_frames__term_unlogged t2,
         vitalgraph1__wordnet_frames__term_unlogged t3,
         vitalgraph1__wordnet_frames__term_unlogged t4,
         vitalgraph1__wordnet_frames__term_unlogged t5,
         vitalgraph1__wordnet_frames__term_unlogged t6,
         vitalgraph1__wordnet_frames__term_unlogged t7,
         vitalgraph1__wordnet_frames__term_unlogged t8,
         vitalgraph1__wordnet_frames__term_unlogged t9
    WHERE t1.term_text = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
      AND t2.term_text = 'http://vital.ai/ontology/vital-core#KGEntity'
      AND t3.term_text = 'http://vital.ai/ontology/vital-core#hasName'
      AND t4.term_text = 'http://vital.ai/ontology/vital-core#hasDescription'
      AND t5.term_text = 'http://vital.ai/ontology/vital-core#hasEntitySlotValue'
      AND t6.term_text = 'http://vital.ai/ontology/vital-core#hasSlotType'
      AND t7.term_text = 'http://vital.ai/ontology/vital-core#hasSourceEntity'
      AND t8.term_text = 'http://vital.ai/ontology/vital-core#hasDestinationEntity'
      AND t9.term_text = 'http://vital.ai/graph/kgwordnetframes'
),
-- Find entities with "happy" in their description
happy_entities AS MATERIALIZED (
    SELECT DISTINCT q1.subject_uuid as entity_uuid
    FROM constants
    JOIN vitalgraph1__wordnet_frames__term_unlogged obj 
        ON obj.term_type = 'L'
        AND obj.term_text_fts @@ plainto_tsquery('english', 'happy')
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
-- OPTIMIZED: Use materialized view for frame → slot relationships
frame_slot_connections AS MATERIALIZED (
    SELECT DISTINCT
        mv.source_node_uuid as frame_uuid,
        mv.dest_node_uuid as slot_uuid,
        mv.edge_uuid
    FROM vitalgraph1__wordnet_frames__edge_relationships_mv mv
),
-- Get slot data with early filtering by happy entities
slot_data AS MATERIALIZED (
    SELECT DISTINCT
        slot.subject_uuid as slot_uuid,
        type.object_uuid as slot_type,
        entity.object_uuid as entity_uuid
    FROM constants
    -- Start with happy entities to reduce search space
    JOIN happy_entities he ON true
    -- Join entity table first, filtered by happy entities
    JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged entity
        ON entity.object_uuid = he.entity_uuid
        AND entity.predicate_uuid = constants.has_entity_slot_value_uuid
        AND entity.context_uuid = constants.graph_uuid
    -- Join slot table (entity.subject_uuid is the slot)
    JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged slot
        ON slot.subject_uuid = entity.subject_uuid
        AND slot.context_uuid = constants.graph_uuid
    -- Join type table to get slot type
    JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged type
        ON type.subject_uuid = slot.subject_uuid
        AND type.predicate_uuid = constants.has_slot_type_uuid
        AND type.context_uuid = constants.graph_uuid
        AND type.object_uuid IN (constants.has_source_entity_uuid, constants.has_destination_entity_uuid)
),
-- Combine frame-slot connections with slot data using the materialized view
final_results AS (
    SELECT DISTINCT
        fsc.frame_uuid,
        sd.entity_uuid,
        fsc.slot_uuid,
        CASE 
            WHEN sd.slot_type = constants.has_source_entity_uuid THEN 'source'
            WHEN sd.slot_type = constants.has_destination_entity_uuid THEN 'dest'
            ELSE 'unknown'
        END as slot_role
    FROM constants
    CROSS JOIN frame_slot_connections fsc
    JOIN slot_data sd ON sd.slot_uuid = fsc.slot_uuid
),
-- Aggregate frame data
frame_aggregated AS (
    SELECT 
        frame_uuid,
        COUNT(DISTINCT entity_uuid) as entity_count,
        COUNT(DISTINCT CASE WHEN slot_role = 'source' THEN entity_uuid END) as source_entities,
        COUNT(DISTINCT CASE WHEN slot_role = 'dest' THEN entity_uuid END) as dest_entities,
        ARRAY_AGG(DISTINCT entity_uuid) as all_entities,
        ARRAY_AGG(DISTINCT CASE WHEN slot_role = 'source' THEN entity_uuid END) 
            FILTER (WHERE slot_role = 'source') as source_entity_list,
        ARRAY_AGG(DISTINCT CASE WHEN slot_role = 'dest' THEN entity_uuid END) 
            FILTER (WHERE slot_role = 'dest') as dest_entity_list
    FROM final_results
    GROUP BY frame_uuid
    HAVING COUNT(DISTINCT entity_uuid) > 0
)
-- Final output with entity names
SELECT 
    fa.frame_uuid,
    frame_term.term_text as frame_name,
    fa.entity_count,
    fa.source_entities,
    fa.dest_entities,
    -- Get names for source entities
    ARRAY(
        SELECT DISTINCT name_term.term_text
        FROM unnest(fa.source_entity_list) as source_uuid
        JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged name_quad 
            ON name_quad.subject_uuid = source_uuid
        JOIN vitalgraph1__wordnet_frames__term_unlogged name_term 
            ON name_term.term_uuid = name_quad.object_uuid
        JOIN constants ON name_quad.predicate_uuid = constants.has_name_uuid
        WHERE name_quad.context_uuid = constants.graph_uuid
        ORDER BY name_term.term_text
    ) as source_entity_names,
    -- Get names for destination entities  
    ARRAY(
        SELECT DISTINCT name_term.term_text
        FROM unnest(fa.dest_entity_list) as dest_uuid
        JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged name_quad 
            ON name_quad.subject_uuid = dest_uuid
        JOIN vitalgraph1__wordnet_frames__term_unlogged name_term 
            ON name_term.term_uuid = name_quad.object_uuid
        JOIN constants ON name_quad.predicate_uuid = constants.has_name_uuid
        WHERE name_quad.context_uuid = constants.graph_uuid
        ORDER BY name_term.term_text
    ) as dest_entity_names
FROM frame_aggregated fa
JOIN vitalgraph1__wordnet_frames__term_unlogged frame_term 
    ON frame_term.term_uuid = fa.frame_uuid
ORDER BY fa.entity_count DESC, frame_term.term_text
LIMIT 20;
