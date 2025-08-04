WITH constants AS (
    SELECT 
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged WHERE term_text = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type' LIMIT 1) AS rdf_type_uuid,
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged WHERE term_text = 'http://vital.ai/ontology/haley-ai-kg#KGEntity' LIMIT 1) AS kg_entity_uuid,
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged WHERE term_text = 'http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription' LIMIT 1) AS has_description_uuid,
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged WHERE term_text = 'http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue' LIMIT 1) AS has_entity_slot_value_uuid,
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged WHERE term_text = 'http://vital.ai/ontology/haley-ai-kg#hasKGSlotType' LIMIT 1) AS has_slot_type_uuid,
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged WHERE term_text = 'http://vital.ai/ontology/vital-core#hasEdgeSource' LIMIT 1) AS has_edge_source_uuid,
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged WHERE term_text = 'http://vital.ai/ontology/vital-core#hasEdgeDestination' LIMIT 1) AS has_edge_destination_uuid,
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged WHERE term_text = 'http://vital.ai/graph/kgwordnetframes' LIMIT 1) AS graph_uuid,
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged WHERE term_text = 'urn:hasSourceEntity' LIMIT 1) AS has_source_entity_uuid,
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged WHERE term_text = 'urn:hasDestinationEntity' LIMIT 1) AS has_destination_entity_uuid
),
happy_entities AS (
    SELECT q1.subject_uuid as entity_uuid
    FROM constants
    JOIN vitalgraph1__wordnet_frames__term_unlogged obj
        ON obj.term_text_fts @@ plainto_tsquery('english', 'happy')
        AND obj.term_type = 'L'
    JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged q1 
        ON q1.object_uuid = obj.term_uuid
        AND q1.predicate_uuid = constants.has_description_uuid
        AND q1.context_uuid = constants.graph_uuid
    JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged q2
        ON q2.subject_uuid = q1.subject_uuid
        AND q2.predicate_uuid = constants.rdf_type_uuid
        AND q2.object_uuid = constants.kg_entity_uuid
        AND q2.context_uuid = constants.graph_uuid
)
-- Source entity is happy
SELECT 
    fc1.entity_uuid as entity,
    fc1.frame_uuid as frame,
    fc1.slot_uuid as sourceSlot,
    fc2.slot_uuid as destinationSlot,
    fc1.entity_uuid as sourceSlotEntity,
    fc2.entity_uuid as destinationSlotEntity
FROM constants
-- Get source slots with happy entities
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged ev1
    ON ev1.predicate_uuid = constants.has_entity_slot_value_uuid
    AND ev1.context_uuid = constants.graph_uuid
    AND EXISTS (SELECT 1 FROM happy_entities WHERE entity_uuid = ev1.object_uuid)
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged st1
    ON st1.subject_uuid = ev1.subject_uuid
    AND st1.predicate_uuid = constants.has_slot_type_uuid
    AND st1.object_uuid = constants.has_source_entity_uuid
    AND st1.context_uuid = constants.graph_uuid
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged ed1
    ON ed1.object_uuid = ev1.subject_uuid
    AND ed1.predicate_uuid = constants.has_edge_destination_uuid
    AND ed1.context_uuid = constants.graph_uuid
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged es1
    ON es1.subject_uuid = ed1.subject_uuid
    AND es1.predicate_uuid = constants.has_edge_source_uuid
    AND es1.context_uuid = constants.graph_uuid
-- Get corresponding destination slot for same frame
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged ev2
    ON ev2.predicate_uuid = constants.has_entity_slot_value_uuid
    AND ev2.context_uuid = constants.graph_uuid
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged st2
    ON st2.subject_uuid = ev2.subject_uuid
    AND st2.predicate_uuid = constants.has_slot_type_uuid
    AND st2.object_uuid = constants.has_destination_entity_uuid
    AND st2.context_uuid = constants.graph_uuid
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged ed2
    ON ed2.object_uuid = ev2.subject_uuid
    AND ed2.predicate_uuid = constants.has_edge_destination_uuid
    AND ed2.context_uuid = constants.graph_uuid
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged es2
    ON es2.subject_uuid = ed2.subject_uuid
    AND es2.predicate_uuid = constants.has_edge_source_uuid
    AND es2.object_uuid = es1.object_uuid  -- Same frame
    AND es2.context_uuid = constants.graph_uuid
-- Create result aliases
CROSS JOIN LATERAL (
    SELECT 
        ev1.subject_uuid as slot_uuid,
        ev1.object_uuid as entity_uuid,
        es1.object_uuid as frame_uuid
) fc1
CROSS JOIN LATERAL (
    SELECT 
        ev2.subject_uuid as slot_uuid,
        ev2.object_uuid as entity_uuid
) fc2

UNION ALL

-- Destination entity is happy
SELECT 
    fc2.entity_uuid as entity,
    fc1.frame_uuid as frame,
    fc1.slot_uuid as sourceSlot,
    fc2.slot_uuid as destinationSlot,
    fc1.entity_uuid as sourceSlotEntity,
    fc2.entity_uuid as destinationSlotEntity
FROM constants
-- Get destination slots with happy entities
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged ev2
    ON ev2.predicate_uuid = constants.has_entity_slot_value_uuid
    AND ev2.context_uuid = constants.graph_uuid
    AND EXISTS (SELECT 1 FROM happy_entities WHERE entity_uuid = ev2.object_uuid)
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged st2
    ON st2.subject_uuid = ev2.subject_uuid
    AND st2.predicate_uuid = constants.has_slot_type_uuid
    AND st2.object_uuid = constants.has_destination_entity_uuid
    AND st2.context_uuid = constants.graph_uuid
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged ed2
    ON ed2.object_uuid = ev2.subject_uuid
    AND ed2.predicate_uuid = constants.has_edge_destination_uuid
    AND ed2.context_uuid = constants.graph_uuid
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged es2
    ON es2.subject_uuid = ed2.subject_uuid
    AND es2.predicate_uuid = constants.has_edge_source_uuid
    AND es2.context_uuid = constants.graph_uuid
-- Get corresponding source slot for same frame
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged ev1
    ON ev1.predicate_uuid = constants.has_entity_slot_value_uuid
    AND ev1.context_uuid = constants.graph_uuid
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged st1
    ON st1.subject_uuid = ev1.subject_uuid
    AND st1.predicate_uuid = constants.has_slot_type_uuid
    AND st1.object_uuid = constants.has_source_entity_uuid
    AND st1.context_uuid = constants.graph_uuid
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged ed1
    ON ed1.object_uuid = ev1.subject_uuid
    AND ed1.predicate_uuid = constants.has_edge_destination_uuid
    AND ed1.context_uuid = constants.graph_uuid
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged es1
    ON es1.subject_uuid = ed1.subject_uuid
    AND es1.predicate_uuid = constants.has_edge_source_uuid
    AND es1.object_uuid = es2.object_uuid  -- Same frame
    AND es1.context_uuid = constants.graph_uuid
-- Create result aliases
CROSS JOIN LATERAL (
    SELECT 
        ev1.subject_uuid as slot_uuid,
        ev1.object_uuid as entity_uuid,
        es1.object_uuid as frame_uuid
) fc1
CROSS JOIN LATERAL (
    SELECT 
        ev2.subject_uuid as slot_uuid,
        ev2.object_uuid as entity_uuid
) fc2

ORDER BY entity
LIMIT 500 OFFSET 0;
