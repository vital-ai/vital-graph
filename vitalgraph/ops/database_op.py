"""
Database maintenance operations for VitalGraph.

Provides DatabaseOp subclasses for PostgreSQL maintenance tasks:
- AnalyzeOp: Update planner statistics (ANALYZE)
- VacuumOp: Reclaim dead tuple storage (VACUUM)
- StatsRebuildOp: Rebuild rdf_pred_stats / rdf_stats tables

These operations must be executed outside a transaction block (autocommit mode).
Applies to all PostgreSQL-backed backends (fuseki_postgresql, sparql_sql).
"""

import logging
from typing import Optional, List, Dict, Any

from .graph_op import GraphOp, OperationResult, OperationStatus

logger = logging.getLogger(__name__)


class DatabaseOp(GraphOp):
    """
    Base class for PostgreSQL database maintenance operations.

    Each op targets a specific space's tables. The target tables vary
    by backend (fuseki_postgresql vs sparql_sql) and are resolved at
    runtime from the active backend's schema.

    Important: ANALYZE and VACUUM must run outside a transaction block.
    With asyncpg, use a raw connection with autocommit (not inside a
    transaction context).
    """

    def __init__(self, space_id: str, conn=None, operation_id: Optional[str] = None):
        """Initialize database maintenance operation.

        Args:
            space_id: Target space whose tables will be maintained.
            conn: Database connection (must support autocommit for ANALYZE/VACUUM).
            operation_id: Optional unique identifier for this operation.
        """
        super().__init__(operation_id)
        self.space_id = space_id
        self.conn = conn
        self._tables_maintained: List[str] = []

    def _get_target_tables(self, backend_type: str = 'sparql_sql') -> List[str]:
        """Get tables to maintain for the target space.

        Table names depend on backend:
        - fuseki_postgresql: {space_id}_term, {space_id}_rdf_quad
        - sparql_sql: {space_id}_term, {space_id}_rdf_quad, {space_id}_datatype,
                      {space_id}_rdf_pred_stats, {space_id}_rdf_stats

        Args:
            backend_type: The active backend type.

        Returns:
            List of table names to operate on.
        """
        sid = self.space_id
        if backend_type == 'fuseki_postgresql':
            return [f"{sid}_term", f"{sid}_rdf_quad"]
        else:
            return [
                f"{sid}_term",
                f"{sid}_rdf_quad",
                f"{sid}_datatype",
                f"{sid}_rdf_pred_stats",
                f"{sid}_rdf_stats",
            ]


class AnalyzeOp(DatabaseOp):
    """Run PostgreSQL ANALYZE on one space's tables to update planner statistics.

    ANALYZE reads a sample of the table (not full scan) and updates
    pg_statistic so the query planner can choose optimal plans.
    Non-blocking — does not lock the table.
    """

    def get_operation_name(self) -> str:
        return f"ANALYZE: {self.space_id}"

    async def execute(self) -> OperationResult:
        tables = self._get_target_tables()
        analyzed = 0
        for table in tables:
            try:
                self.update_progress(f"Analyzing {table}...")
                await self.conn.execute(f"ANALYZE {table}")
                self._tables_maintained.append(table)
                analyzed += 1
            except Exception as e:
                logger.error(f"ANALYZE failed on {table}: {e}")
                return OperationResult(
                    status=OperationStatus.ERROR,
                    message=f"ANALYZE failed on {table}: {e}",
                    details={'tables_analyzed': analyzed, 'failed_table': table},
                )
        return OperationResult(
            status=OperationStatus.SUCCESS,
            message=f"Analyzed {analyzed} tables for space {self.space_id}",
            details={'tables_analyzed': analyzed, 'tables': self._tables_maintained},
        )


class VacuumOp(DatabaseOp):
    """Run PostgreSQL VACUUM on one space's tables to reclaim dead tuple storage.

    Plain VACUUM only (never VACUUM FULL). Non-blocking — runs concurrently
    with reads and writes.
    """

    def get_operation_name(self) -> str:
        return f"VACUUM: {self.space_id}"

    async def execute(self) -> OperationResult:
        tables = self._get_target_tables()
        vacuumed = 0
        for table in tables:
            try:
                self.update_progress(f"Vacuuming {table}...")
                await self.conn.execute(f"VACUUM {table}")
                self._tables_maintained.append(table)
                vacuumed += 1
            except Exception as e:
                logger.error(f"VACUUM failed on {table}: {e}")
                return OperationResult(
                    status=OperationStatus.ERROR,
                    message=f"VACUUM failed on {table}: {e}",
                    details={'tables_vacuumed': vacuumed, 'failed_table': table},
                )
        return OperationResult(
            status=OperationStatus.SUCCESS,
            message=f"Vacuumed {vacuumed} tables for space {self.space_id}",
            details={'tables_vacuumed': vacuumed, 'tables': self._tables_maintained},
        )


class StatsRebuildOp(DatabaseOp):
    """Rebuild rdf_pred_stats and rdf_stats tables for the query optimizer.

    These auxiliary tables are used by the sparql_sql generator for join
    reordering. This op truncates and repopulates them from rdf_quad.
    """

    def get_operation_name(self) -> str:
        return f"Stats Rebuild: {self.space_id}"

    async def execute(self) -> OperationResult:
        sid = self.space_id
        pred_stats = f"{sid}_rdf_pred_stats"
        rdf_stats = f"{sid}_rdf_stats"
        quad_table = f"{sid}_rdf_quad"

        try:
            self.update_progress("Rebuilding predicate stats...")
            await self.conn.execute(f"TRUNCATE {pred_stats}")
            await self.conn.execute(f"""
                INSERT INTO {pred_stats} (predicate_uuid, row_count)
                SELECT predicate_uuid, COUNT(*)
                FROM {quad_table}
                GROUP BY predicate_uuid
            """)

            self.update_progress("Rebuilding predicate-object stats...")
            await self.conn.execute(f"TRUNCATE {rdf_stats}")
            await self.conn.execute(f"""
                INSERT INTO {rdf_stats} (predicate_uuid, object_uuid, row_count)
                SELECT predicate_uuid, object_uuid, COUNT(*)
                FROM {quad_table}
                GROUP BY predicate_uuid, object_uuid
                HAVING COUNT(*) <= 200000
            """)

            return OperationResult(
                status=OperationStatus.SUCCESS,
                message=f"Stats rebuilt for space {sid}",
                details={'pred_stats_table': pred_stats, 'rdf_stats_table': rdf_stats},
            )
        except Exception as e:
            logger.error(f"Stats rebuild failed for {sid}: {e}")
            return OperationResult(
                status=OperationStatus.ERROR,
                message=f"Stats rebuild failed: {e}",
            )
