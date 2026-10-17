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

AN INVALID INDEX IS A MISSING INDEX (`issues/272`). A `CREATE INDEX
CONCURRENTLY` or `REINDEX CONCURRENTLY` that fails or is cancelled leaves the
index in the catalog with `indisvalid = false`: the planner never uses it, every
write still maintains it. Matched by NAME it looked present, so the check
reported nothing — and `CREATE INDEX IF NOT EXISTS` skips the name, so no
replay could repair it either. Production on 2026-10-17 had one (an empty test
space's `term_dt`), and the deploy's own cancelled `DROP INDEX CONCURRENTLY`
left another for the minutes before its re-run. So validity is part of
"present", and the repair drops an invalid index before recreating it.
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


async def _present(conn, space_id: str) -> Tuple[Set[str], Set[str], Set[str]]:
    """`(tables, valid index names, INVALID index names)` for the space."""
    tables = {r["tablename"] for r in await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
        "AND tablename LIKE $1", f"{space_id}\\_%")}
    valid, invalid = set(), set()
    for r in await conn.fetch(
            "SELECT ci.relname, i.indisvalid AND i.indisready AS ok "
            "FROM pg_index i "
            "JOIN pg_class ci ON ci.oid = i.indexrelid "
            "JOIN pg_class ct ON ct.oid = i.indrelid "
            "JOIN pg_namespace n ON n.oid = ct.relnamespace "
            "WHERE n.nspname = 'public' AND ct.relname = ANY($1::text[])",
            list(tables)):
        (valid if r["ok"] else invalid).add(r["relname"])
    return tables, valid, invalid


async def missing_space_indexes(
        conn, space_id: str,
        tables: Optional[Iterable[str]] = None) -> List[Tuple[str, str]]:
    """`[(index_name, table)]` the schema names, on tables that exist, that are absent.

    `tables` narrows the check (the bulk import only touches term and quad).
    An index for a table the space does not have is not "missing": spaces
    predating a table legitimately lack its indexes. An index that exists but
    is INVALID is missing (`issues/272`); `invalid_space_indexes` says which.
    """
    present_tables, valid, _invalid = await _present(conn, space_id)
    wanted = set(tables) & present_tables if tables is not None else present_tables
    return [(name, table) for name, table, _ in schema_indexes(space_id)
            if table in wanted and name not in valid]


async def invalid_space_indexes(conn, space_id: str) -> List[str]:
    """Names of the space's schema indexes that exist but are INVALID."""
    _tables, _valid, invalid = await _present(conn, space_id)
    return [name for name, _t, _s in schema_indexes(space_id) if name in invalid]


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
    _t, _v, invalid = await _present(conn, space_id)
    created = []
    for name, _table, stmt in schema_indexes(space_id):
        if name in names:
            if name in invalid:
                # `IF NOT EXISTS` would skip the name and leave it unusable.
                await conn.execute(f'DROP INDEX IF EXISTS "{name}"')
            await conn.execute(stmt)
            created.append(name)
    return created
