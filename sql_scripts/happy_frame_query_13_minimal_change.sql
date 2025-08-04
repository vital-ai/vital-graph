-- Minimal optimization: ONLY replace edge_structure CTE with materialized view
-- All other logic remains identical to happy_frame_query_5.sql

BEGIN;
SET LOCAL work_mem = '1GB';


WITH constants AS (
    SELECT
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged 
         WHERE term_text = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type' LIMIT 1) AS rdf_type_uuid,
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged 
         WHERE term_text = 'http://vital.ai/ontology/haley-ai-kg#KGEntity' LIMIT 1) AS kg_entity_uuid,
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
)
-- KEEP ORIGINAL OUTPUT FORMAT: entity, frame, sourceslot, destinationslot, sourceslotentity, destinationslotentity
SELECT DISTINCT
    entity_term.term_text as entity,
    frame_term.term_text as frame,
    source_slot_term.term_text as sourceslot,
    dest_slot_term.term_text as destinationslot,
    source_entity_term.term_text as sourceslotentity,
    dest_entity_term.term_text as destinationslotentity
FROM final_results fr1
JOIN final_results fr2 ON fr1.frame_uuid = fr2.frame_uuid AND fr1.entity_uuid = fr2.entity_uuid
JOIN constants ON true
-- Get entity term
JOIN vitalgraph1__wordnet_frames__term_unlogged entity_term 
    ON entity_term.term_uuid = fr1.entity_uuid
-- Get frame term
JOIN vitalgraph1__wordnet_frames__term_unlogged frame_term 
    ON frame_term.term_uuid = fr1.frame_uuid
-- Get source slot (fr1 is source, fr2 is destination)
JOIN vitalgraph1__wordnet_frames__term_unlogged source_slot_term 
    ON source_slot_term.term_uuid = fr1.slot_uuid
-- Get destination slot
JOIN vitalgraph1__wordnet_frames__term_unlogged dest_slot_term 
    ON dest_slot_term.term_uuid = fr2.slot_uuid
-- Get source entity
JOIN vitalgraph1__wordnet_frames__term_unlogged source_entity_term 
    ON source_entity_term.term_uuid = fr1.entity_uuid
-- Get destination entity  
JOIN vitalgraph1__wordnet_frames__term_unlogged dest_entity_term 
    ON dest_entity_term.term_uuid = fr2.entity_uuid
WHERE fr1.slot_type = constants.has_source_entity_uuid
  AND fr2.slot_type = constants.has_destination_entity_uuid
ORDER BY entity_term.term_text
LIMIT 10 OFFSET 0;

COMMIT;
