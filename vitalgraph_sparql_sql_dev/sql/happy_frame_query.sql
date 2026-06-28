-- Happy Frame Query — Updated for wordnet_exp tables
-- Uses trigram index (gin_trgm_ops) for text search instead of plainto_tsquery.
-- Uses edge_mv and frame_entity_mv materialized views.
-- All UUIDs resolved from wordnet_exp_term.
--
-- Predicate UUIDs (wordnet_exp):
-- hasKGraphDescription:  1e7843d3-ac11-5ba9-9d19-92274c1e48a6
-- hasEntitySlotValue:    87a0a946-3150-5b4a-852f-84ce8e37e29f
-- hasKGSlotType:         e263c804-e3b0-5bdf-968c-82e536f5effe
-- hasSourceEntity:       3dd13e9e-4f51-5a18-9654-7ec814d02ba7
-- hasDestinationEntity:  d1daebbc-ca1e-5ff6-baad-bd88487575d9
-- rdf:type:              f947f06c-bd0c-5ae0-bcd6-6db005605b0a
-- KGEntity:              2d50120b-1fe8-5aed-bea8-cf3fa0acec45
-- KGFrame:               3bf26ec8-6088-52ef-87d5-c350ce1ed447
-- hasName:               05b1c2f1-4489-5a62-8608-59178273cf5c
-- hasEdgeSource:         c7ef9fd3-8e1a-5ad8-afe5-069a76b889e2
-- hasEdgeDestination:    57fdaf9c-79ba-5cbd-893e-d6eeb0b84eb9

BEGIN;

\timing on

WITH
-- Step 1: Find entities whose description contains "happy" (trigram ILIKE)
happy_entities AS (
    SELECT DISTINCT q1.subject_uuid AS entity_uuid
    FROM wordnet_exp_rdf_quad q1
    WHERE q1.predicate_uuid = '1e7843d3-ac11-5ba9-9d19-92274c1e48a6'::uuid  -- hasKGraphDescription
      AND q1.object_uuid IN (
          SELECT t.term_uuid
          FROM wordnet_exp_term t
          WHERE t.term_text ILIKE '%happy%'
      )
),
-- Step 2: Slot data — join slots to happy entities (early filter)
-- Each slot has a type (source/dest) and points to an entity via hasEntitySlotValue
slot_data AS (
    SELECT
        q1.subject_uuid AS slot_uuid,
        q1.object_uuid  AS entity_uuid,
        CASE
            WHEN q2.object_uuid = '3dd13e9e-4f51-5a18-9654-7ec814d02ba7'::uuid THEN 'source'
            WHEN q2.object_uuid = 'd1daebbc-ca1e-5ff6-baad-bd88487575d9'::uuid THEN 'dest'
        END AS slot_type,
        1 AS is_matching_entity
    FROM wordnet_exp_rdf_quad q1
    JOIN wordnet_exp_rdf_quad q2
        ON q2.subject_uuid = q1.subject_uuid
    JOIN happy_entities he
        ON he.entity_uuid = q1.object_uuid
    WHERE q1.predicate_uuid = '87a0a946-3150-5b4a-852f-84ce8e37e29f'::uuid  -- hasEntitySlotValue
      AND q2.predicate_uuid = 'e263c804-e3b0-5bdf-968c-82e536f5effe'::uuid  -- hasKGSlotType
      AND q2.object_uuid IN (
          '3dd13e9e-4f51-5a18-9654-7ec814d02ba7'::uuid,  -- hasSourceEntity
          'd1daebbc-ca1e-5ff6-baad-bd88487575d9'::uuid   -- hasDestinationEntity
      )
),
-- Step 3: Edge structure from the edge MV (frame → slot)
edge_structure AS (
    SELECT
        source_node_uuid AS frame_uuid,
        dest_node_uuid   AS slot_uuid
    FROM wordnet_exp_edge_mv
),
-- Step 4: Aggregate slots per frame using conditional aggregation
-- Pivots source/dest slots+entities into columns per frame
frame_aggregated AS (
    SELECT
        es.frame_uuid,
        (array_agg(sd.slot_uuid)    FILTER (WHERE sd.slot_type = 'source'))[1] AS source_slot_uuid,
        (array_agg(sd.entity_uuid)  FILTER (WHERE sd.slot_type = 'source'))[1] AS source_entity_uuid,
        (array_agg(sd.slot_uuid)    FILTER (WHERE sd.slot_type = 'dest'))[1]   AS dest_slot_uuid,
        (array_agg(sd.entity_uuid)  FILTER (WHERE sd.slot_type = 'dest'))[1]   AS dest_entity_uuid,
        MAX(CASE WHEN sd.slot_type = 'source' AND sd.is_matching_entity = 1 THEN 1 ELSE 0 END) AS source_matches_happy,
        MAX(CASE WHEN sd.slot_type = 'dest'   AND sd.is_matching_entity = 1 THEN 1 ELSE 0 END) AS dest_matches_happy
    FROM edge_structure es
    JOIN slot_data sd ON sd.slot_uuid = es.slot_uuid
    GROUP BY es.frame_uuid
    HAVING (array_agg(sd.entity_uuid) FILTER (WHERE sd.slot_type = 'source'))[1] IS NOT NULL
       AND (array_agg(sd.entity_uuid) FILTER (WHERE sd.slot_type = 'dest'))[1]   IS NOT NULL
)
-- Solution 1: Bind entity to SOURCE when it matches "happy"
SELECT
    fa.source_entity_uuid AS entity_uuid,
    fa.frame_uuid,
    fa.source_slot_uuid,
    fa.dest_slot_uuid,
    fa.source_entity_uuid,
    fa.dest_entity_uuid
FROM frame_aggregated fa
WHERE fa.source_matches_happy = 1

UNION ALL

-- Solution 2: Bind entity to DESTINATION when it matches "happy"
SELECT
    fa.dest_entity_uuid AS entity_uuid,
    fa.frame_uuid,
    fa.source_slot_uuid,
    fa.dest_slot_uuid,
    fa.source_entity_uuid,
    fa.dest_entity_uuid
FROM frame_aggregated fa
WHERE fa.dest_matches_happy = 1

ORDER BY entity_uuid
LIMIT 500 OFFSET 0;

COMMIT;
