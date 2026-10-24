\echo Use "CREATE EXTENSION vg_planner" to load this file. \quit

CREATE FUNCTION vg_planner_info() RETURNS text
AS 'MODULE_PATHNAME', 'vg_planner_info'
LANGUAGE C STRICT STABLE PARALLEL SAFE;

