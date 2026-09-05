"""Both schema installers must create every function the schema needs.

There are two: `SparqlSQLAdmin.init_tables` (app/admin, talks to a db_impl) and
`scripts/perf_init_db.py` (perf runner, talks to a raw asyncpg connection). They
drifted — perf_init_db installed `vitalgraph_term_uuid` and not
`vitalgraph_iso_to_utc` — and a genuinely fresh perf database then failed every
space-creating bench at setup with

    asyncpg.exceptions.UndefinedFunctionError:
      function vitalgraph_iso_to_utc(text) does not exist

Nothing caught it for as long as the test stack reused a data volume that
already had the function. It surfaced only when pinning the postgres minor
version forced a genuinely clean database — i.e. the drift was invisible exactly
while the environment was dirty, which is the opposite of when you want to find
it.

Both now iterate `FUNCTION_DDL`. This asserts they still do, because the failure
mode is silent until a fresh database meets a bench that needs the function.
"""

from __future__ import annotations

import re
from pathlib import Path

from vitalgraph.db.sparql_sql.sparql_sql_admin import FUNCTION_DDL

ROOT = Path(__file__).resolve().parents[2]


def _function_names(ddls) -> set:
    out = set()
    for d in ddls:
        m = re.search(r"CREATE OR REPLACE FUNCTION (\w+)", d)
        if m:
            out.add(m.group(1))
    return out


def test_the_shared_tuple_holds_the_functions_the_schema_needs():
    names = _function_names(FUNCTION_DDL)
    assert "vitalgraph_term_uuid" in names
    assert "vitalgraph_iso_to_utc" in names, (
        "the function whose absence failed every space-creating perf bench")


def test_the_admin_installer_iterates_the_tuple():
    src = (ROOT / "vitalgraph" / "db" / "sparql_sql"
           / "sparql_sql_admin.py").read_text(encoding="utf-8")
    body = src[src.index("async def init_tables"):]
    body = body[:body.index("\n    async def ", 1) if "\n    async def " in body[1:]
                else len(body)]
    assert "FUNCTION_DDL" in body, (
        "init_tables must iterate FUNCTION_DDL, not name DDLs individually — "
        "naming them individually is how the two installers drifted")


def test_the_perf_installer_iterates_the_tuple():
    src = (ROOT / "scripts" / "perf_init_db.py").read_text(encoding="utf-8")
    assert "FUNCTION_DDL" in src, (
        "perf_init_db.py must iterate FUNCTION_DDL; it previously installed one "
        "function by name and missed the other")
    assert not re.search(r"execute\(\s*_VITALGRAPH_\w+_DDL\s*\)", src), (
        "installing a single named function DDL is the drift this test exists "
        "to prevent")
