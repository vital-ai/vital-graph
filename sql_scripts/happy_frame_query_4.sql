-- SPARQL to SQL Translation: Text Search for "happy" entities
-- Based on happy_frame_query.sparql - focusing on the text search aspect only
-- This query finds KGEntity instances that contain "happy" in their hasKGraphDescription

WITH constants AS (
    SELECT
        -- RDF type predicate
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged 
         WHERE term_text = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type' LIMIT 1) AS rdf_type_uuid,
        
        -- KGEntity class
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged 
         WHERE term_text = 'http://vital.ai/ontology/haley-ai-kg#KGEntity' LIMIT 1) AS kg_entity_uuid,
        
        -- hasKGraphDescription predicate
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged 
         WHERE term_text = 'http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription' LIMIT 1) AS has_description_uuid,
        
        -- Graph context
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged 
         WHERE term_text = 'http://vital.ai/graph/kgwordnetframes' LIMIT 1) AS graph_uuid
),

-- Find entities with "happy" in their description
happy_entities AS (
    SELECT DISTINCT 
        q1.subject_uuid as entity_uuid,
        obj.term_text as description_text
    FROM constants
    -- Find literal terms containing "happy" using full-text search
    JOIN vitalgraph1__wordnet_frames__term_unlogged obj
        ON obj.term_text_fts @@ plainto_tsquery('english', 'happy')
        AND obj.term_type = 'L'  -- Literal type
    -- Find quads where these literals are objects of hasKGraphDescription
    JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged q1 
        ON q1.object_uuid = obj.term_uuid
        AND q1.predicate_uuid = constants.has_description_uuid
        AND q1.context_uuid = constants.graph_uuid
    -- Verify the subject is a KGEntity
    JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged q2
        ON q2.subject_uuid = q1.subject_uuid
        AND q2.predicate_uuid = constants.rdf_type_uuid
        AND q2.object_uuid = constants.kg_entity_uuid
        AND q2.context_uuid = constants.graph_uuid
)

-- Return the results with entity URIs and descriptions
SELECT 
    entity_term.term_text as entity_uri,
    he.description_text
FROM happy_entities he
JOIN vitalgraph1__wordnet_frames__term_unlogged entity_term
    ON entity_term.term_uuid = he.entity_uuid
ORDER BY entity_term.term_text
LIMIT 100;

-- Notes on required indexes:
-- 1. Full-text search index on term_text_fts (should exist)
-- 2. Index on term_type for efficient literal filtering
-- 3. Composite indexes on rdf_quad for efficient joins:
--    - (object_uuid, predicate_uuid, context_uuid) 
--    - (subject_uuid, predicate_uuid, object_uuid, context_uuid)
-- 4. Index on term_text for URI lookups in constants CTE
