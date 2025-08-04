-- Extract constants for hardcoding in optimized queries
-- This eliminates the need for the constants CTE in production queries

SELECT 
    'rdf_type_uuid' as constant_name,
    t1.term_uuid as uuid_value,
    t1.term_text as uri_value
FROM vitalgraph1__wordnet_frames__term_unlogged t1
WHERE t1.term_text = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'

UNION ALL

SELECT 
    'kg_entity_uuid' as constant_name,
    t2.term_uuid as uuid_value,
    t2.term_text as uri_value
FROM vitalgraph1__wordnet_frames__term_unlogged t2
WHERE t2.term_text = 'http://vital.ai/ontology/haley-ai-kg#KGEntity'

UNION ALL

SELECT 
    'has_description_uuid' as constant_name,
    t3.term_uuid as uuid_value,
    t3.term_text as uri_value
FROM vitalgraph1__wordnet_frames__term_unlogged t3
WHERE t3.term_text = 'http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription'

UNION ALL

SELECT 
    'has_entity_slot_value_uuid' as constant_name,
    t4.term_uuid as uuid_value,
    t4.term_text as uri_value
FROM vitalgraph1__wordnet_frames__term_unlogged t4
WHERE t4.term_text = 'http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue'

UNION ALL

SELECT 
    'has_slot_type_uuid' as constant_name,
    t5.term_uuid as uuid_value,
    t5.term_text as uri_value
FROM vitalgraph1__wordnet_frames__term_unlogged t5
WHERE t5.term_text = 'http://vital.ai/ontology/haley-ai-kg#hasKGSlotType'

UNION ALL

SELECT 
    'has_edge_source_uuid' as constant_name,
    t6.term_uuid as uuid_value,
    t6.term_text as uri_value
FROM vitalgraph1__wordnet_frames__term_unlogged t6
WHERE t6.term_text = 'http://vital.ai/ontology/vital-core#hasEdgeSource'

UNION ALL

SELECT 
    'has_edge_destination_uuid' as constant_name,
    t7.term_uuid as uuid_value,
    t7.term_text as uri_value
FROM vitalgraph1__wordnet_frames__term_unlogged t7
WHERE t7.term_text = 'http://vital.ai/ontology/vital-core#hasEdgeDestination'

UNION ALL

SELECT 
    'graph_uuid' as constant_name,
    t8.term_uuid as uuid_value,
    t8.term_text as uri_value
FROM vitalgraph1__wordnet_frames__term_unlogged t8
WHERE t8.term_text = 'http://vital.ai/graph/kgwordnetframes'

UNION ALL

SELECT 
    'has_source_entity_uuid' as constant_name,
    t9.term_uuid as uuid_value,
    t9.term_text as uri_value
FROM vitalgraph1__wordnet_frames__term_unlogged t9
WHERE t9.term_text = 'urn:hasSourceEntity'

UNION ALL

SELECT 
    'has_destination_entity_uuid' as constant_name,
    t10.term_uuid as uuid_value,
    t10.term_text as uri_value
FROM vitalgraph1__wordnet_frames__term_unlogged t10
WHERE t10.term_text = 'urn:hasDestinationEntity'

ORDER BY constant_name;
