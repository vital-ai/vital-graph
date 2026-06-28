-- Diagnostic query to debug each CTE step individually
-- This will help identify where the logic breaks down

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
-- Test 1: Check if happy_entities CTE works
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
-- Test 2: Check edge_structure from materialized view
edge_structure AS MATERIALIZED (
    SELECT 
        mv.edge_uuid,
        mv.source_node_uuid as frame_uuid,
        mv.dest_node_uuid as slot_uuid
    FROM vitalgraph1__wordnet_frames__edge_relationships_mv mv
),
-- Test 3: Check slot_data with happy entities
slot_data AS MATERIALIZED (
    SELECT DISTINCT
        slot.subject_uuid as slot_uuid,
        type.object_uuid as slot_type,
        entity.object_uuid as entity_uuid
    FROM constants
    JOIN happy_entities he ON true
    JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged entity
        ON entity.object_uuid = he.entity_uuid
        AND entity.predicate_uuid = constants.has_entity_slot_value_uuid
        AND entity.context_uuid = constants.graph_uuid
    JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged slot
        ON slot.subject_uuid = entity.subject_uuid
        AND slot.context_uuid = constants.graph_uuid
    JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged type
        ON type.subject_uuid = slot.subject_uuid
        AND type.predicate_uuid = constants.has_slot_type_uuid
        AND type.context_uuid = constants.graph_uuid
        AND type.object_uuid IN (constants.has_source_entity_uuid, constants.has_destination_entity_uuid)
)

-- Diagnostic output - test each CTE individually
SELECT 'Step 1: Happy Entities Count' as test_step, COUNT(*) as count FROM happy_entities
UNION ALL
SELECT 'Step 2: Edge Structure Count' as test_step, COUNT(*) as count FROM edge_structure  
UNION ALL
SELECT 'Step 3: Slot Data Count' as test_step, COUNT(*) as count FROM slot_data
UNION ALL
SELECT 'Step 4: Join Test Count' as test_step, COUNT(*) as count 
FROM edge_structure es
JOIN slot_data sd ON sd.slot_uuid = es.slot_uuid;
