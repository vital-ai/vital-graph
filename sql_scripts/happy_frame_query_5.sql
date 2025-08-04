BEGIN;

-- Set local settings (only for this transaction)
SET LOCAL max_parallel_workers_per_gather = 4;
SET LOCAL parallel_tuple_cost = 0.1;
SET LOCAL parallel_setup_cost = 100;
SET LOCAL min_parallel_table_scan_size = '8MB';
SET LOCAL min_parallel_index_scan_size = '512kB';

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
-- Get all edges and their frames/slots in parallel
edge_structure AS MATERIALIZED (
    SELECT 
        edge.subject_uuid as edge_uuid,
        source.object_uuid as frame_uuid,
        dest.object_uuid as slot_uuid
    FROM constants
    CROSS JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged edge
    JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged source 
        ON source.subject_uuid = edge.subject_uuid
        AND source.predicate_uuid = constants.has_edge_source_uuid
        AND source.context_uuid = constants.graph_uuid
    JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged dest 
        ON dest.subject_uuid = edge.subject_uuid
        AND dest.predicate_uuid = constants.has_edge_destination_uuid
        AND dest.context_uuid = constants.graph_uuid
    WHERE edge.context_uuid = constants.graph_uuid
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
    -- Finally join type table with selectivity
    JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged type
        ON type.subject_uuid = slot.subject_uuid
        AND type.predicate_uuid = constants.has_slot_type_uuid
        AND type.context_uuid = constants.graph_uuid
        AND type.object_uuid IN (constants.has_source_entity_uuid, constants.has_destination_entity_uuid)
),
-- Combine the parallel results (happy entities already filtered in slot_data)
final_results AS (
    SELECT DISTINCT
        es.frame_uuid,
        sd.entity_uuid,
        es.slot_uuid,
        CASE 
            WHEN sd.slot_type = constants.has_source_entity_uuid THEN 'source'
            WHEN sd.slot_type = constants.has_destination_entity_uuid THEN 'dest'
        END as slot_role,
        sd.slot_type
    FROM edge_structure es
    JOIN slot_data sd ON sd.slot_uuid = es.slot_uuid
    CROSS JOIN constants
),
-- Aggregate to get complete frames
frame_aggregated AS (
    SELECT 
        frame_uuid,
        jsonb_object_agg(slot_role || '_slot', slot_uuid) as slots,
        jsonb_object_agg(slot_role || '_entity', entity_uuid) as entities,
        COUNT(DISTINCT slot_role) as role_count
    FROM final_results
    WHERE slot_role IS NOT NULL
    GROUP BY frame_uuid
    HAVING COUNT(DISTINCT slot_role) = 2
)
-- Resolve UUIDs to URIs in the final output
SELECT 
    entity_term.term_text as entity,
    frame_term.term_text as frame,
    source_slot_term.term_text as sourceSlot,
    dest_slot_term.term_text as destinationSlot,
    source_entity_term.term_text as sourceSlotEntity,
    dest_entity_term.term_text as destinationSlotEntity
FROM frame_aggregated fa
-- Resolve entity URI (whichever one has "happy")
JOIN vitalgraph1__wordnet_frames__term_unlogged entity_term
    ON entity_term.term_uuid = COALESCE((fa.entities->>'source_entity')::uuid, (fa.entities->>'dest_entity')::uuid)
-- Resolve frame URI
JOIN vitalgraph1__wordnet_frames__term_unlogged frame_term
    ON frame_term.term_uuid = fa.frame_uuid
-- Resolve source slot URI
JOIN vitalgraph1__wordnet_frames__term_unlogged source_slot_term
    ON source_slot_term.term_uuid = (fa.slots->>'source_slot')::uuid
-- Resolve destination slot URI
JOIN vitalgraph1__wordnet_frames__term_unlogged dest_slot_term
    ON dest_slot_term.term_uuid = (fa.slots->>'dest_slot')::uuid
-- Resolve source entity URI
JOIN vitalgraph1__wordnet_frames__term_unlogged source_entity_term
    ON source_entity_term.term_uuid = (fa.entities->>'source_entity')::uuid
-- Resolve destination entity URI
JOIN vitalgraph1__wordnet_frames__term_unlogged dest_entity_term
    ON dest_entity_term.term_uuid = (fa.entities->>'dest_entity')::uuid
ORDER BY entity
LIMIT 10 OFFSET 0;

COMMIT;