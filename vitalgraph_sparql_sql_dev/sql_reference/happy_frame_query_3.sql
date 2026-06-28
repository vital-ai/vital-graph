WITH constants AS (
    SELECT
        (SELECT term_uuid 
         FROM vitalgraph1__wordnet_frames__term_unlogged 
         WHERE term_text = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type' 
         LIMIT 1
        ) AS rdf_type_uuid,
        (SELECT term_uuid 
         FROM vitalgraph1__wordnet_frames__term_unlogged 
         WHERE term_text = 'http://vital.ai/ontology/haley-ai-kg#KGEntity' 
         LIMIT 1
        ) AS kg_entity_uuid,
        (SELECT term_uuid 
         FROM vitalgraph1__wordnet_frames__term_unlogged 
         WHERE term_text = 'http://vital.ai/ontology/haley-ai-kg#KGFrame' 
         LIMIT 1
        ) AS kg_frame_uuid,
        (SELECT term_uuid 
         FROM vitalgraph1__wordnet_frames__term_unlogged 
         WHERE term_text = 'http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription' 
         LIMIT 1
        ) AS has_description_uuid,
        (SELECT term_uuid 
         FROM vitalgraph1__wordnet_frames__term_unlogged 
         WHERE term_text = 'http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue' 
         LIMIT 1
        ) AS has_entity_slot_value_uuid,
        (SELECT term_uuid 
         FROM vitalgraph1__wordnet_frames__term_unlogged 
         WHERE term_text = 'http://vital.ai/ontology/haley-ai-kg#hasKGSlotType' 
         LIMIT 1
        ) AS has_slot_type_uuid,
        (SELECT term_uuid 
         FROM vitalgraph1__wordnet_frames__term_unlogged 
         WHERE term_text = 'http://vital.ai/ontology/haley-ai-kg#KGEntitySlot' 
         LIMIT 1
        ) AS kg_entity_slot_uuid,
        (SELECT term_uuid 
         FROM vitalgraph1__wordnet_frames__term_unlogged 
         WHERE term_text = 'http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot' 
         LIMIT 1
        ) AS edge_has_kg_slot_uuid,
        (SELECT term_uuid 
         FROM vitalgraph1__wordnet_frames__term_unlogged 
         WHERE term_text = 'http://vital.ai/ontology/vital-core#hasEdgeSource' 
         LIMIT 1
        ) AS has_edge_source_uuid,
        (SELECT term_uuid 
         FROM vitalgraph1__wordnet_frames__term_unlogged 
         WHERE term_text = 'http://vital.ai/ontology/vital-core#hasEdgeDestination' 
         LIMIT 1
        ) AS has_edge_destination_uuid,
        (SELECT term_uuid 
         FROM vitalgraph1__wordnet_frames__term_unlogged 
         WHERE term_text = 'http://vital.ai/graph/kgwordnetframes' 
         LIMIT 1
        ) AS graph_uuid,
        (SELECT term_uuid 
         FROM vitalgraph1__wordnet_frames__term_unlogged 
         WHERE term_text = 'urn:hasSourceEntity' 
         LIMIT 1
        ) AS has_source_entity_uuid,
        (SELECT term_uuid 
         FROM vitalgraph1__wordnet_frames__term_unlogged 
         WHERE term_text = 'urn:hasDestinationEntity' 
         LIMIT 1
        ) AS has_destination_entity_uuid
),
happy_entities AS (
    SELECT DISTINCT q1.subject_uuid as entity_uuid
    FROM constants
    CROSS JOIN LATERAL (
        -- Force use of GIN trigram index if available
        SELECT term_uuid, term_text
        FROM vitalgraph1__wordnet_frames__term_unlogged
        WHERE term_text ILIKE '%happy%'
        -- Or use trigram similarity if configured:
        -- WHERE term_text % 'happy'
        LIMIT 1000  -- Prevent runaway results
    ) obj
    JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged q1 
        ON q1.object_uuid = obj.term_uuid
        AND q1.predicate_uuid = constants.has_description_uuid
        AND q1.context_uuid = constants.graph_uuid
    WHERE EXISTS (
        SELECT 1 
        FROM vitalgraph1__wordnet_frames__rdf_quad_unlogged q2
        WHERE q2.subject_uuid = q1.subject_uuid
        AND q2.predicate_uuid = constants.rdf_type_uuid
        AND q2.object_uuid = constants.kg_entity_uuid
        AND q2.context_uuid = constants.graph_uuid
    )
),
-- Pre-aggregate happy entities for faster lookup
happy_entity_lookup AS (
    SELECT entity_uuid 
    FROM happy_entities
),
-- Find frames more efficiently
relevant_frames AS (
    SELECT DISTINCT frame.subject_uuid as frame_uuid
    FROM constants
    JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged frame
        ON frame.predicate_uuid = constants.rdf_type_uuid
        AND frame.object_uuid = constants.kg_frame_uuid
        AND frame.context_uuid = constants.graph_uuid
    -- Check if frame has any connection to happy entities
    WHERE EXISTS (
        SELECT 1
        FROM vitalgraph1__wordnet_frames__rdf_quad_unlogged edge
        JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged slot
            ON slot.subject_uuid = edge.subject_uuid
            AND slot.predicate_uuid = constants.has_edge_destination_uuid
            AND slot.context_uuid = constants.graph_uuid
        JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged entity_link
            ON entity_link.subject_uuid = slot.object_uuid
            AND entity_link.predicate_uuid = constants.has_entity_slot_value_uuid
            AND entity_link.context_uuid = constants.graph_uuid
        JOIN happy_entity_lookup he
            ON he.entity_uuid = entity_link.object_uuid
        WHERE edge.predicate_uuid = constants.has_edge_source_uuid
        AND edge.object_uuid = frame.subject_uuid
        AND edge.context_uuid = constants.graph_uuid
    )
),
-- Now get the full frame data only for relevant frames
frame_data AS (
    SELECT 
        rf.frame_uuid,
        source_data.slot_uuid as source_slot_uuid,
        source_data.entity_uuid as source_entity_uuid,
        dest_data.slot_uuid as dest_slot_uuid,
        dest_data.entity_uuid as dest_entity_uuid
    FROM relevant_frames rf
    CROSS JOIN constants
    -- Get source slot data
    JOIN LATERAL (
        SELECT 
            slot.object_uuid as slot_uuid,
            entity.object_uuid as entity_uuid
        FROM vitalgraph1__wordnet_frames__rdf_quad_unlogged edge
        JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged slot
            ON slot.subject_uuid = edge.subject_uuid
            AND slot.predicate_uuid = constants.has_edge_destination_uuid
            AND slot.context_uuid = constants.graph_uuid
        JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged slot_type
            ON slot_type.subject_uuid = slot.object_uuid
            AND slot_type.predicate_uuid = constants.has_slot_type_uuid
            AND slot_type.object_uuid = constants.has_source_entity_uuid
            AND slot_type.context_uuid = constants.graph_uuid
        JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged entity
            ON entity.subject_uuid = slot.object_uuid
            AND entity.predicate_uuid = constants.has_entity_slot_value_uuid
            AND entity.context_uuid = constants.graph_uuid
        WHERE edge.predicate_uuid = constants.has_edge_source_uuid
        AND edge.object_uuid = rf.frame_uuid
        AND edge.context_uuid = constants.graph_uuid
        LIMIT 1
    ) source_data ON true
    -- Get destination slot data
    JOIN LATERAL (
        SELECT 
            slot.object_uuid as slot_uuid,
            entity.object_uuid as entity_uuid
        FROM vitalgraph1__wordnet_frames__rdf_quad_unlogged edge
        JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged slot
            ON slot.subject_uuid = edge.subject_uuid
            AND slot.predicate_uuid = constants.has_edge_destination_uuid
            AND slot.context_uuid = constants.graph_uuid
        JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged slot_type
            ON slot_type.subject_uuid = slot.object_uuid
            AND slot_type.predicate_uuid = constants.has_slot_type_uuid
            AND slot_type.object_uuid = constants.has_destination_entity_uuid
            AND slot_type.context_uuid = constants.graph_uuid
        JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged entity
            ON entity.subject_uuid = slot.object_uuid
            AND entity.predicate_uuid = constants.has_entity_slot_value_uuid
            AND entity.context_uuid = constants.graph_uuid
        WHERE edge.predicate_uuid = constants.has_edge_source_uuid
        AND edge.object_uuid = rf.frame_uuid
        AND edge.context_uuid = constants.graph_uuid
        LIMIT 1
    ) dest_data ON true
    WHERE EXISTS (
        SELECT 1 FROM happy_entity_lookup he
        WHERE he.entity_uuid IN (source_data.entity_uuid, dest_data.entity_uuid)
    )
)
SELECT DISTINCT
    COALESCE(he.entity_uuid, fd.source_entity_uuid, fd.dest_entity_uuid) as entity,
    fd.frame_uuid as frame,
    fd.source_slot_uuid as sourceSlot,
    fd.dest_slot_uuid as destinationSlot,
    fd.source_entity_uuid as sourceSlotEntity,
    fd.dest_entity_uuid as destinationSlotEntity
FROM frame_data fd
LEFT JOIN happy_entities he 
    ON he.entity_uuid IN (fd.source_entity_uuid, fd.dest_entity_uuid)
ORDER BY entity
LIMIT 10 OFFSET 0;
