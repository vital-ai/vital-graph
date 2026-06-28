-- Add unique constraint on (space_id, graph_uri) to the graph table.
-- This supports ON CONFLICT (space_id, graph_uri) DO NOTHING
-- used by the auto-registration of graphs on data insert.
--
-- Safe to run multiple times (IF NOT EXISTS).

CREATE UNIQUE INDEX IF NOT EXISTS uq_graph_space_uri
    ON graph (space_id, graph_uri);
