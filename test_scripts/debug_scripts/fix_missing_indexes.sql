-- Fix missing indexes for SPARQL query performance
-- These indexes are critical for JOIN performance and COUNT query optimization
-- 
-- Usage: Set the space_id variable and run the script
-- Example: psql -d vitalgraphdb -v space_id=import_001 -f fix_missing_indexes.sql

-- Indexes on rdf_quad_primary table for JOIN columns
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vitalgraph2__:space_id __rdf_quad_primary_subject_uuid 
    ON vitalgraph2__:space_id __rdf_quad_primary (subject_uuid);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vitalgraph2__:space_id __rdf_quad_primary_predicate_uuid 
    ON vitalgraph2__:space_id __rdf_quad_primary (predicate_uuid);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vitalgraph2__:space_id __rdf_quad_primary_object_uuid 
    ON vitalgraph2__:space_id __rdf_quad_primary (object_uuid);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vitalgraph2__:space_id __rdf_quad_primary_context_uuid 
    ON vitalgraph2__:space_id __rdf_quad_primary (context_uuid);

-- Index on term_primary table for JOIN column
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vitalgraph2__:space_id __term_primary_term_uuid 
    ON vitalgraph2__:space_id __term_primary (term_uuid);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vitalgraph2__:space_id __term_primary_term_text 
    ON vitalgraph2__:space_id __term_primary (term_text);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vitalgraph2__:space_id __term_primary_term_type 
    ON vitalgraph2__:space_id __term_primary (term_type);

-- Composite index for optimized lookups
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vitalgraph2__:space_id __term_primary_text_type 
    ON vitalgraph2__:space_id __term_primary (term_text, term_type);

-- SPARQL-optimized composite index (subject, predicate, object, context)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vitalgraph2__:space_id __rdf_quad_primary_spoc 
    ON vitalgraph2__:space_id __rdf_quad_primary (subject_uuid, predicate_uuid, object_uuid, context_uuid);

-- Create indexes on the partitioned parent tables as well
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vitalgraph2__:space_id __rdf_quad_subject_uuid 
    ON vitalgraph2__:space_id __rdf_quad (subject_uuid);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vitalgraph2__:space_id __rdf_quad_predicate_uuid 
    ON vitalgraph2__:space_id __rdf_quad (predicate_uuid);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vitalgraph2__:space_id __rdf_quad_object_uuid 
    ON vitalgraph2__:space_id __rdf_quad (object_uuid);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vitalgraph2__:space_id __rdf_quad_context_uuid 
    ON vitalgraph2__:space_id __rdf_quad (context_uuid);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vitalgraph2__:space_id __rdf_quad_uuid 
    ON vitalgraph2__:space_id __rdf_quad (quad_uuid);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vitalgraph2__:space_id __rdf_quad_dataset 
    ON vitalgraph2__:space_id __rdf_quad (dataset);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vitalgraph2__:space_id __term_term_text 
    ON vitalgraph2__:space_id __term (term_text);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vitalgraph2__:space_id __term_term_type 
    ON vitalgraph2__:space_id __term (term_type);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vitalgraph2__:space_id __term_dataset 
    ON vitalgraph2__:space_id __term (dataset);

-- Composite index for term text and type lookups
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vitalgraph2__:space_id __term_text_type 
    ON vitalgraph2__:space_id __term (term_text, term_type);

-- Full-text search indexes using trigram extension (if pg_trgm is available)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vitalgraph2__:space_id __term_text_gin_trgm 
    ON vitalgraph2__:space_id __term USING gin (term_text gin_trgm_ops);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vitalgraph2__:space_id __term_text_gist_trgm 
    ON vitalgraph2__:space_id __term USING gist (term_text gist_trgm_ops);

-- Additional indexes for CSV import partition tables (if they exist)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vitalgraph2__:space_id __rdf_quad_csv_:space_id _subject_uuid 
    ON vitalgraph2__:space_id __rdf_quad_csv_:space_id (subject_uuid);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vitalgraph2__:space_id __rdf_quad_csv_:space_id _context_uuid 
    ON vitalgraph2__:space_id __rdf_quad_csv_:space_id (context_uuid);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vitalgraph2__:space_id __term_csv_:space_id _term_text 
    ON vitalgraph2__:space_id __term_csv_:space_id (term_text);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vitalgraph2__:space_id __term_csv_:space_id _term_type 
    ON vitalgraph2__:space_id __term_csv_:space_id (term_type);
