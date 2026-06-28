"""Verify that the _VITALGRAPH_TERM_UUID_DDL embedded in sparql_sql_admin.py
works correctly when executed via asyncpg (the same driver the app uses)."""

import asyncio
import uuid
import sys

_VITALGRAPH_NS = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')


def _generate_term_uuid(term_text, term_type, lang=None, datatype_id=None):
    parts = [term_text, term_type]
    if lang is not None:
        parts.append(f"lang:{lang}")
    if datatype_id is not None:
        parts.append(f"datatype:{datatype_id}")
    return uuid.uuid5(_VITALGRAPH_NS, "\x00".join(parts))


async def main():
    import asyncpg

    # Import the DDL constant from the actual module
    sys.path.insert(0, '.')
    from vitalgraph.db.sparql_sql.sparql_sql_admin import _VITALGRAPH_TERM_UUID_DDL

    conn = await asyncpg.connect(
        host='localhost', port=5432,
        user='postgres', database='vitalgraphdb',
    )

    try:
        # Ensure pgcrypto + create/replace function via the embedded DDL
        await conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        await conn.execute(_VITALGRAPH_TERM_UUID_DDL)
        print("DDL executed successfully via asyncpg")

        # Test cases: (text, type, lang, datatype_id)
        tests = [
            ("hello", "U", None, None),
            ("hello", "L", None, None),
            ("2026-04-30T12:00:00+00:00", "L", None, 9),
            ("some text", "L", "en", None),
            ("label", "L", "fr", 5),
            ("0", "L", None, 3),
            ("true", "L", None, 7),
        ]

        ok = True
        for text, ttype, lang, dt_id in tests:
            py_uuid = str(_generate_term_uuid(text, ttype, lang, dt_id))
            sql_uuid = str(await conn.fetchval(
                "SELECT vitalgraph_term_uuid($1, $2, $3, $4)",
                text, ttype, lang, dt_id,
            ))
            match = "PASS" if py_uuid == sql_uuid else "FAIL"
            if py_uuid != sql_uuid:
                ok = False
            print(f"  {match}: ({text!r}, {ttype}, lang={lang}, dt={dt_id})")
            if py_uuid != sql_uuid:
                print(f"    Python: {py_uuid}")
                print(f"    SQL:    {sql_uuid}")

        print()
        print("ALL PASS" if ok else "SOME FAILED")
        return ok
    finally:
        await conn.close()


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
