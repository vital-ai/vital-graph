"""Check which spaces have xsd:dateTime literals and ObjectModificationDateTime."""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import asyncpg


async def main():
    h = os.environ.get("LOCAL_DB_HOST", "localhost")
    p = os.environ.get("LOCAL_DB_PORT", "5432")
    d = os.environ.get("LOCAL_DB_NAME", "sparql_sql_graph")
    u = os.environ.get("LOCAL_DB_USERNAME", "postgres")
    pw = os.environ.get("LOCAL_DB_PASSWORD", "")
    conn = await asyncpg.connect(f"postgresql://{u}:{pw}@{h}:{p}/{d}")

    # Find all spaces
    tabs = await conn.fetch(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name LIKE '%_rdf_quad' "
        "ORDER BY table_name"
    )
    spaces = [r["table_name"].replace("_rdf_quad", "") for r in tabs]

    for sp in spaces:
        try:
            # Check for dateTime typed literals (datatype_id=9 is xsd:dateTime)
            cnt = await conn.fetchval(
                f"SELECT COUNT(*) FROM {sp}_term WHERE datatype_id = 9"
            )
            if cnt and cnt > 0:
                # Check for ObjectModificationDateTime predicate
                omd = await conn.fetchval(
                    f"SELECT COUNT(*) FROM {sp}_rdf_quad q "
                    f"JOIN {sp}_term pt ON q.predicate_uuid = pt.term_uuid "
                    f"WHERE pt.term_text LIKE '%ObjectModificationDateTime'"
                )
                # Sample values
                sample = await conn.fetch(
                    f"SELECT term_text FROM {sp}_term WHERE datatype_id = 9 LIMIT 3"
                )
                vals = [r["term_text"][:50] for r in sample]
                print(f"{sp}: {cnt} dateTime terms, {omd} ObjectModDateTime quads")
                for v in vals:
                    print(f"  sample: {v}")
            else:
                print(f"{sp}: 0 dateTime terms")
        except Exception as e:
            print(f"{sp}: error {e}")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
