"""
Admin operations for the sparql_sql backend.

Provides init / purge / delete / info / list-spaces for the SPARQL-SQL
pure-PostgreSQL backend.  All DDL is owned by SparqlSQLSchema; this
module only orchestrates the operations.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from ..common.models import GraphData, SpaceData, UserData
from ..db_admin_inf import DbAdminInterface
from .sparql_sql_schema import SparqlSQLSchema

logger = logging.getLogger(__name__)

# DDL for deterministic UUID v5 function — mirrors Python's _generate_term_uuid()
# exactly, including \x00 separators. Requires pgcrypto extension.
_VITALGRAPH_ISO_TO_UTC_DDL = """
-- Parse a strict ISO-8601 literal to a UTC timestamp, IMMUTABLY.
--
-- The obvious `CAST(term_text AS TIMESTAMP)` cannot be used in a generated
-- column: it honours the DateStyle setting, so PostgreSQL rejects it with
-- "generation expression is not immutable". `to_timestamp` is STABLE for the
-- same reason. num_val exists only because text->numeric happens to be
-- immutable — that was luck, not a pattern that generalises (issues/053).
--
-- Assembling the value from components avoids the settings dependency
-- entirely: make_timestamp, make_interval, regexp_match and the text->int
-- casts are all immutable, so this function genuinely is too. Nothing is
-- mislabelled, which matters because an IMMUTABLE lie produces wrong answers
-- after a dump/restore rather than an error.
--
-- An explicit offset is applied to normalise to UTC, so
-- 2020-01-01T12:00:00+05:00 and 2020-01-01T07:00:00+00:00 compare equal — the
-- case lexicographic comparison on term_text gets silently backwards.
-- A literal with no offset is taken as UTC. That is a policy choice: the
-- alternative, ::timestamptz, reads it in the SESSION timezone and is
-- therefore not immutable and not reproducible.
--
-- Returns NULL for anything that is not a strict ISO date/dateTime, which is
-- what makes it safe to apply across a term table holding URIs and free text.
CREATE OR REPLACE FUNCTION vitalgraph_iso_to_utc(t text)
RETURNS timestamp
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $iso$
SELECT CASE WHEN m IS NULL THEN NULL ELSE
  make_timestamp(m[1]::int, m[2]::int, m[3]::int,
                 COALESCE(m[4], '0')::int, COALESCE(m[5], '0')::int,
                 COALESCE(m[6], '0')::double precision)
  - make_interval(
      hours => COALESCE(m[8], '0')::int * CASE WHEN m[7] = '-' THEN -1 ELSE 1 END,
      mins  => COALESCE(m[9], '0')::int * CASE WHEN m[7] = '-' THEN -1 ELSE 1 END)
END
FROM regexp_match(
  t,
  '^(\\d{4})-(\\d{2})-(\\d{2})(?:[T ](\\d{2}):(\\d{2}):(\\d{2}(?:\\.\\d+)?))?(?:([+-])(\\d{2}):(\\d{2})|Z)?$'
) AS m
$iso$;
"""


_VITALGRAPH_TERM_UUID_DDL = """
CREATE OR REPLACE FUNCTION vitalgraph_term_uuid(
    p_text text, p_type char(1),
    p_lang text DEFAULT NULL,
    p_datatype_id bigint DEFAULT NULL
) RETURNS uuid AS $$
DECLARE
    name_bytes bytea;
    ns_bytes bytea;
    hash bytea;
    raw bytea;
BEGIN
    name_bytes := convert_to(p_text, 'UTF8') || '\\x00'::bytea || convert_to(p_type, 'UTF8');
    IF p_lang IS NOT NULL THEN
        name_bytes := name_bytes || '\\x00'::bytea || convert_to('lang:' || p_lang, 'UTF8');
    END IF;
    IF p_datatype_id IS NOT NULL THEN
        name_bytes := name_bytes || '\\x00'::bytea || convert_to('datatype:' || p_datatype_id::text, 'UTF8');
    END IF;
    ns_bytes := '\\x6ba7b8109dad11d180b400c04fd430c8'::bytea;
    hash := digest(ns_bytes || name_bytes, 'sha1');
    raw := substring(hash from 1 for 16);
    raw := set_byte(raw, 6, (get_byte(raw, 6) & 15) | 80);
    raw := set_byte(raw, 8, (get_byte(raw, 8) & 63) | 128);
    RETURN encode(raw, 'hex')::uuid;
END;
$$ LANGUAGE plpgsql IMMUTABLE;
"""


# EVERY function the schema needs, in one place.
#
# There are two installers — `SparqlSQLAdmin.init_tables` (the app/admin path)
# and `scripts/perf_init_db.py` (the perf runner, which talks to a raw asyncpg
# connection rather than a db_impl). They drifted: perf_init_db installed
# `vitalgraph_term_uuid` and not `vitalgraph_iso_to_utc`, so a genuinely fresh
# perf database raised
#
#     asyncpg.exceptions.UndefinedFunctionError:
#       function vitalgraph_iso_to_utc(text) does not exist
#
# and every space-creating bench errored at setup. It went unnoticed because the
# test stack reused a data volume that already had the function, so only a truly
# clean database — which is what pinning the postgres minor forced — exposed it.
#
# Both installers now iterate this tuple. Add a function here and both paths get
# it; that is the point.
FUNCTION_DDL = (_VITALGRAPH_TERM_UUID_DDL, _VITALGRAPH_ISO_TO_UTC_DDL)


class SparqlSQLAdmin(DbAdminInterface):
    """Admin operations for the sparql_sql backend."""

    def __init__(self):
        self.schema = SparqlSQLSchema()

    # ---- check -----------------------------------------------------------

    async def check_admin_tables(self, db_impl) -> Dict[str, Any]:
        table_names = self.schema.ADMIN_TABLE_NAMES
        check_query = """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name IN ({})
        """.format(", ".join(f"'{n}'" for n in table_names))

        rows = await db_impl.execute_query(check_query)
        found = [r['table_name'] for r in rows] if rows else []
        return {
            'expected': len(table_names),
            'found': len(found),
            'tables': found,
        }

    # ---- init ------------------------------------------------------------

    async def init_tables(self, db_impl) -> bool:
        # Ensure extensions + functions (idempotent — always runs)
        await db_impl.execute_update("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        await db_impl.execute_update("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        await db_impl.execute_update("CREATE EXTENSION IF NOT EXISTS vector")
        await db_impl.execute_update("CREATE EXTENSION IF NOT EXISTS postgis")
        for _fn_ddl in FUNCTION_DDL:
            await db_impl.execute_update(_fn_ddl)

        status = await self.check_admin_tables(db_impl)

        if status['found'] == status['expected']:
            logger.info("All %d admin tables already exist", status['expected'])
            return True

        # Create tables
        for stmt in self.schema.create_admin_tables_sql():
            await db_impl.execute_update(stmt)

        # Create indexes
        for stmt in self.schema.create_admin_indexes_sql():
            await db_impl.execute_update(stmt)

        # Seed data
        for stmt in self.schema.get_admin_seed_sql():
            await db_impl.execute_update(stmt)

        logger.info("SPARQL-SQL admin tables initialized successfully")
        return True

    # ---- purge -----------------------------------------------------------

    async def purge_tables(self, db_impl) -> bool:
        # Drop all per-space tables first
        spaces = await self.list_spaces(db_impl)
        for sp in spaces:
            for stmt in self.schema.drop_space_tables_sql(sp.space_id):
                await db_impl.execute_update(stmt)
            logger.info("Dropped per-space tables for: %s", sp.space_id)

        # Truncate admin tables in reverse dependency order
        for stmt in self.schema.truncate_admin_tables_sql():
            await db_impl.execute_update(stmt)

        # Re-seed
        for stmt in self.schema.get_admin_seed_sql():
            await db_impl.execute_update(stmt)

        logger.info("SPARQL-SQL tables purged and re-seeded")
        return True

    # ---- delete ----------------------------------------------------------

    async def delete_tables(self, db_impl) -> bool:
        # Drop all per-space tables first
        spaces = await self.list_spaces(db_impl)
        for sp in spaces:
            for stmt in self.schema.drop_space_tables_sql(sp.space_id):
                await db_impl.execute_update(stmt)

        # Drop admin tables in reverse dependency order
        for stmt in self.schema.drop_admin_tables_sql():
            await db_impl.execute_update(stmt)

        logger.info("SPARQL-SQL tables deleted")
        return True

    # ---- info ------------------------------------------------------------

    async def get_info(self, db_impl, config=None) -> Dict[str, Any]:
        info: Dict[str, Any] = {
            'backend': 'SPARQL-SQL (Pure PostgreSQL)',
            'status': 'Connected',
        }

        # Config-derived info
        if config:
            sparql_sql_config = config.get_sparql_sql_config()
            info['sidecar_url'] = sparql_sql_config.get('sidecar', {}).get('url', 'N/A')
            pg_config = sparql_sql_config.get('database', {})
            info['pg_host'] = pg_config.get('host', 'N/A')
            info['pg_database'] = pg_config.get('database', 'N/A')

        # Admin table check
        status = await self.check_admin_tables(db_impl)
        info['admin_tables'] = status

        if status['found'] >= 5:
            info['init_state'] = 'initialized'

            # Space count and per-space table check
            spaces = await self.list_spaces(db_impl)
            info['space_count'] = len(spaces)
            info['spaces'] = []
            for sp in spaces:
                sid = sp.space_id
                term_tbl = f"{sid}_term"
                quad_tbl = f"{sid}_rdf_quad"
                tbl_check = await db_impl.execute_query(
                    "SELECT COUNT(*) as c FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name IN ($1, $2)",
                    [term_tbl, quad_tbl]
                )
                tbl_count = tbl_check[0]['c'] if tbl_check else 0
                info['spaces'].append({'space_id': sid, 'tables_ok': tbl_count == 2})

            # pg_trgm
            ext_result = await db_impl.execute_query(
                "SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
            info['pg_trgm'] = bool(ext_result)

            # User count
            user_result = await db_impl.execute_query(
                'SELECT COUNT(*) as count FROM "user"')
            info['user_count'] = user_result[0]['count'] if user_result else 0
        elif status['found'] > 0:
            info['init_state'] = 'partially_initialized'
        else:
            info['init_state'] = 'uninitialized'

        return info

    # ---- list spaces -----------------------------------------------------

    async def list_spaces(self, db_impl) -> List[SpaceData]:
        try:
            rows = await db_impl.execute_query(
                "SELECT space_id, space_name, space_description, tenant, update_time "
                "FROM space ORDER BY space_id")
            return [SpaceData.from_row(r) for r in rows] if rows else []
        except Exception:
            return []

    # ---- list graphs -----------------------------------------------------

    async def list_graphs(self, db_impl, space_id: str = None) -> List[GraphData]:
        try:
            if space_id:
                rows = await db_impl.execute_query(
                    "SELECT graph_id, space_id, graph_uri, graph_name, created_time "
                    "FROM graph WHERE space_id = $1 ORDER BY graph_id",
                    [space_id])
            else:
                rows = await db_impl.execute_query(
                    "SELECT graph_id, space_id, graph_uri, graph_name, created_time "
                    "FROM graph ORDER BY space_id, graph_id")
            return [GraphData.from_row(r) for r in rows] if rows else []
        except Exception:
            return []

    # ---- list users ------------------------------------------------------

    async def list_users(self, db_impl) -> List[UserData]:
        try:
            rows = await db_impl.execute_query(
                'SELECT user_id, username, password, email, tenant, update_time '
                'FROM "user" ORDER BY username')
            return [UserData.from_row(r) for r in rows] if rows else []
        except Exception:
            return []
