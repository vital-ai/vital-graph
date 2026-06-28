"""Check what schemas/tables exist in the database."""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import asyncpg


async def main():
    db_host = os.environ.get("LOCAL_DB_HOST", "localhost")
    db_port = os.environ.get("LOCAL_DB_PORT", "5432")
    db_name = os.environ.get("LOCAL_DB_NAME", "sparql_sql_graph")
    db_user = os.environ.get("LOCAL_DB_USERNAME", "postgres")
    db_pass = os.environ.get("LOCAL_DB_PASSWORD", "")
    url = f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
    print(f"Connecting to: {url[:60]}...")

    conn = await asyncpg.connect(url)

    # Find rdf_quad tables
    rows = await conn.fetch(
        "SELECT table_schema, table_name FROM information_schema.tables "
        "WHERE table_name = 'rdf_quad' LIMIT 10"
    )
    print(f"\nrdf_quad tables found: {len(rows)}")
    for r in rows:
        print(f"  {r['table_schema']}.{r['table_name']}")

    # Find datatype tables
    rows2 = await conn.fetch(
        "SELECT table_schema, table_name FROM information_schema.tables "
        "WHERE table_name LIKE '%datatype%' LIMIT 10"
    )
    print(f"\ndatatype tables found: {len(rows2)}")
    for r in rows2:
        print(f"  {r['table_schema']}.{r['table_name']}")

    # If we found a rdf_quad table, check for datetime literals
    if rows:
        schema = rows[0]["table_schema"]
        print(f"\nChecking {schema}.rdf_quad for rows...")
        count = await conn.fetchval(f"SELECT COUNT(*) FROM {schema}.rdf_quad")
        print(f"  Total quads: {count}")

        if rows2:
            dt_schema = rows2[0]["table_schema"]
            dt_rows = await conn.fetch(
                f"SELECT datatype_id, datatype_uri FROM {dt_schema}.datatype LIMIT 20"
            )
            print(f"\n  Datatype mappings ({dt_schema}):")
            for r in dt_rows:
                print(f"    {r['datatype_id']}: {r['datatype_uri']}")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
