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
        status = await self.check_admin_tables(db_impl)

        if status['found'] == status['expected']:
            logger.info("All %d admin tables already exist", status['expected'])
            return True

        # Ensure pg_trgm extension (needed for per-space trigram indexes)
        await db_impl.execute_update("CREATE EXTENSION IF NOT EXISTS pg_trgm")

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
