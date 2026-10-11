"""What indexes a space SHOULD have, which it lacks, and putting them back.

`issues/156`. The bulk import drops a space's secondary indexes before COPY and
recreated them from a list held only in the importing process's memory. A kill,
a crash, a lost connection — or a plain CANCEL, which returned early without
recreating anything — left the space with primary keys only: every query still
correct, every query a scan, nothing reporting it. Measured on a 50.3M-quad
space in that state: one exact term lookup 2,110 ms, an entity query timing out.

The schema is the definition (`SparqlSQLSchema.create_space_indexes_sql`), so the
expected set can be derived for any space at any time, by any process. Every
statement is `CREATE INDEX IF NOT EXISTS`, so replaying them is idempotent.
"""

import logging
import re
from typing import Iterable, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?"
    r"(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>\w+)\s+ON\s+(?P<table>\S+?)[\s(]",
    re.IGNORECASE)


def schema_indexes(space_id: str) -> List[Tuple[str, str, str]]:
    """`[(index_name, table, statement)]` for every CREATE INDEX the schema emits."""
    from .sparql_sql_schema import SparqlSQLSchema
    out = []
    for stmt in SparqlSQLSchema().create_space_indexes_sql(space_id):
        m = _NAME_RE.search(stmt)
        if m:
            out.append((m.group("name"), m.group("table"), stmt))
    return out


async def _present(conn, space_id: str) -> Tuple[Set[str], Set[str]]:
    tables = {r["tablename"] for r in await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
        "AND tablename LIKE $1", f"{space_id}\\_%")}
    have = {r["indexname"] for r in await conn.fetch(
        "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' "
        "AND tablename = ANY($1::text[])", list(tables))}
    return tables, have


async def missing_space_indexes(
        conn, space_id: str,
        tables: Optional[Iterable[str]] = None) -> List[Tuple[str, str]]:
    """`[(index_name, table)]` the schema names, on tables that exist, that are absent.

    `tables` narrows the check (the bulk import only touches term and quad).
    An index for a table the space does not have is not "missing": spaces
    predating a table legitimately lack its indexes.
    """
    present_tables, have = await _present(conn, space_id)
    wanted = set(tables) & present_tables if tables is not None else present_tables
    return [(name, table) for name, table, _ in schema_indexes(space_id)
            if table in wanted and name not in have]


async def restore_space_indexes(
        conn, space_id: str,
        tables: Optional[Iterable[str]] = None) -> List[str]:
    """Create every schema index missing on `tables` (default: all present).

    Returns the names created. Raises on the first failure: a restore that
    silently half-works is the defect this module exists to remove.
    """
    missing = await missing_space_indexes(conn, space_id, tables)
    if not missing:
        return []
    names = {n for n, _ in missing}
    created = []
    for name, _table, stmt in schema_indexes(space_id):
        if name in names:
            await conn.execute(stmt)
            created.append(name)
    return created
