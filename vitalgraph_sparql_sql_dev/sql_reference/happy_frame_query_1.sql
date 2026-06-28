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
happy_entities AS MATERIALIZED (
    SELECT DISTINCT q1.subject_uuid as entity_uuid
    FROM constants
    JOIN vitalgraph1__wordnet_frames__term_unlogged obj
        ON obj.term_text_fts @@ plainto_tsquery('english', 'hope')
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
),
frame_components AS MATERIALIZED (
    SELECT 
        -- Entity to slot mapping
        ev.subject_uuid as slot_uuid,
        ev.object_uuid as entity_uuid,
        -- Slot type
        st.object_uuid as slot_type_uuid,
        -- Edge info (fixed: using subject_uuid as edge_uuid)
        ed.subject_uuid as edge_uuid,
        -- Frame
        es.object_uuid as frame_uuid
    FROM happy_entities he
    CROSS JOIN constants
    -- Get slots containing happy entities
    JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged ev
        ON ev.object_uuid = he.entity_uuid
        AND ev.predicate_uuid = constants.has_entity_slot_value_uuid
        AND ev.context_uuid = constants.graph_uuid
    -- Get slot types
    JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged st
        ON st.subject_uuid = ev.subject_uuid
        AND st.predicate_uuid = constants.has_slot_type_uuid
        AND st.context_uuid = constants.graph_uuid
        AND st.object_uuid IN (constants.has_source_entity_uuid, constants.has_destination_entity_uuid)
    -- Get edges pointing to slots
    JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged ed
        ON ed.object_uuid = ev.subject_uuid
        AND ed.predicate_uuid = constants.has_edge_destination_uuid
        AND ed.context_uuid = constants.graph_uuid
    -- Get frames from edges (fixed: using ed.subject_uuid)
    JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged es
        ON es.subject_uuid = ed.subject_uuid
        AND es.predicate_uuid = constants.has_edge_source_uuid
        AND es.context_uuid = constants.graph_uuid
),
-- Now aggregate with simplified logic
frame_data AS (
    SELECT 
        frame_uuid,
        jsonb_object_agg(
            CASE 
                WHEN slot_type_uuid = constants.has_source_entity_uuid THEN 'source_slot'
                WHEN slot_type_uuid = constants.has_destination_entity_uuid THEN 'dest_slot'
            END,
            slot_uuid
        ) as slots,
        jsonb_object_agg(
            CASE 
                WHEN slot_type_uuid = constants.has_source_entity_uuid THEN 'source_entity'
                WHEN slot_type_uuid = constants.has_destination_entity_uuid THEN 'dest_entity'
            END,
            entity_uuid
        ) as entities
    FROM frame_components, constants
    GROUP BY frame_uuid
    HAVING COUNT(DISTINCT 
        CASE 
            WHEN slot_type_uuid IN (constants.has_source_entity_uuid, constants.has_destination_entity_uuid) 
            THEN slot_type_uuid 
        END
    ) = 2
)
SELECT 
    COALESCE((entities->>'source_entity')::uuid, (entities->>'dest_entity')::uuid) as entity,
    frame_uuid as frame,
    (slots->>'source_slot')::uuid as sourceSlot,
    (slots->>'dest_slot')::uuid as destinationSlot,
    (entities->>'source_entity')::uuid as sourceSlotEntity,
    (entities->>'dest_entity')::uuid as destinationSlotEntity
FROM frame_data
ORDER BY entity
LIMIT 500 OFFSET 0;
