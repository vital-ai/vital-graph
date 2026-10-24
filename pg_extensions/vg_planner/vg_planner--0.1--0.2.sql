\echo Use "ALTER EXTENSION vg_planner UPDATE" to load this file. \quit

-- The last advised statement's per-item result in this backend:
-- applied / NOT APPLIED for every rows, join and order item. NULL before any.
CREATE FUNCTION vg_planner_last_report() RETURNS text
AS 'MODULE_PATHNAME', 'vg_planner_last_report'
LANGUAGE C VOLATILE PARALLEL RESTRICTED;
