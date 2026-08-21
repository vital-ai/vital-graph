-- What the edge_type_uuid column is worth, with buffers recorded.
--
-- issues/060 claimed 31x. That was wall-clock on a 1 GB pool against a 22 GB
-- quad table, with no buffer count, so the issues/081 buffer-pool review could
-- not clear it. Warm on a 16 GB pool, both shapes fully resident (read=0) and
-- returning the same 3,877,000 rows, the advantage is 6.5x in time and 5.75x
-- in buffers. The three-hop chain below is the one the fixture actually holds:
-- Edge_hasEntityKGFrame -> Edge_hasKGFrame -> Edge_hasKGSlot.
--
-- Run twice; the first run warms. Cold, shape A took 74.8 s against 8.8 s warm,
-- which is the distortion the 31x was made of.
--
--   docker cp test_scripts/perf/edge_type_column_advantage.sql <pg>:/tmp/
--   docker exec <pg> psql -U postgres -d sparql_sql_graph -f /tmp/edge_type_column_advantage.sql

\set QUIET on
SELECT term_uuid AS ef FROM sp_lead_synth_100k_term
 WHERE term_text='http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame' \gset
SELECT term_uuid AS ff FROM sp_lead_synth_100k_term
 WHERE term_text='http://vital.ai/ontology/haley-ai-kg#Edge_hasKGFrame' \gset
SELECT term_uuid AS fs FROM sp_lead_synth_100k_term
 WHERE term_text='http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot' \gset
SELECT term_uuid AS vt FROM sp_lead_synth_100k_term
 WHERE term_text='http://vital.ai/ontology/vital-core#vitaltype' \gset

\echo '### A: typed via quad joins (pre-column)'
EXPLAIN (ANALYZE, BUFFERS, SUMMARY ON)
SELECT count(*) FROM sp_lead_synth_100k_edge e1
JOIN sp_lead_synth_100k_rdf_quad q1 ON q1.subject_uuid=e1.edge_uuid
  AND q1.predicate_uuid=:'vt' AND q1.object_uuid=:'ef'
JOIN sp_lead_synth_100k_edge e2 ON e2.source_node_uuid=e1.dest_node_uuid
JOIN sp_lead_synth_100k_rdf_quad q2 ON q2.subject_uuid=e2.edge_uuid
  AND q2.predicate_uuid=:'vt' AND q2.object_uuid=:'ff'
JOIN sp_lead_synth_100k_edge e3 ON e3.source_node_uuid=e2.dest_node_uuid
JOIN sp_lead_synth_100k_rdf_quad q3 ON q3.subject_uuid=e3.edge_uuid
  AND q3.predicate_uuid=:'vt' AND q3.object_uuid=:'fs';

\echo '### C: typed via edge_type_uuid (the column)'
EXPLAIN (ANALYZE, BUFFERS, SUMMARY ON)
SELECT count(*) FROM sp_lead_synth_100k_edge e1
JOIN sp_lead_synth_100k_edge e2 ON e2.source_node_uuid=e1.dest_node_uuid
JOIN sp_lead_synth_100k_edge e3 ON e3.source_node_uuid=e2.dest_node_uuid
WHERE e1.edge_type_uuid=:'ef' AND e2.edge_type_uuid=:'ff' AND e3.edge_type_uuid=:'fs';
