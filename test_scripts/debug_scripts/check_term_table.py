"""Check term table schema and duplicate rows."""
import asyncio, os, sys
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()
import asyncpg

SP = "space_multi_org_crud_test"

async def main():
    h = os.environ.get("LOCAL_DB_HOST", "localhost")
    p = os.environ.get("LOCAL_DB_PORT", "5432")
    d = os.environ.get("LOCAL_DB_NAME", "sparql_sql_graph")
    u = os.environ.get("LOCAL_DB_USERNAME", "postgres")
    pw = os.environ.get("LOCAL_DB_PASSWORD", "")
    conn = await asyncpg.connect(f"postgresql://{u}:{pw}@{h}:{p}/{d}")

    # 1. Schema
    cols = await conn.fetch(
        "SELECT column_name, data_type, is_nullable "
        "FROM information_schema.columns "
        f"WHERE table_name = '{SP}_term' "
        "ORDER BY ordinal_position"
    )
    print("=== Term table columns ===")
    for c in cols:
        print(f"  {c['column_name']:20s} {c['data_type']:15s} nullable={c['is_nullable']}")

    # 2. Indexes
    idx = await conn.fetch(
        f"SELECT indexname, indexdef FROM pg_indexes WHERE tablename = '{SP}_term'"
    )
    print(f"\n=== Indexes ===")
    for i in idx:
        print(f"  {i['indexname']}")
        print(f"    {i['indexdef']}")

    # 3. Duplicates: same text+type, different datatype_id or uuid
    dups = await conn.fetch(f"""
        SELECT term_text, term_type, COUNT(*) as cnt,
               array_agg(DISTINCT datatype_id ORDER BY datatype_id) as dt_ids,
               array_agg(DISTINCT term_uuid ORDER BY term_uuid) as uuids
        FROM {SP}_term
        WHERE term_type = 'L'
        GROUP BY term_text, term_type
        HAVING COUNT(*) > 1
        LIMIT 10
    """)
    print(f"\n=== Duplicate text+type rows ({len(dups)}) ===")
    for d in dups:
        print(f"  text={str(d['term_text'])[:50]}  cnt={d['cnt']}  dt_ids={d['dt_ids']}  uuids=[{len(d['uuids'])} distinct]")

    # 4. Sample dateTime term
    dt_row = await conn.fetchrow(
        f"SELECT term_uuid, term_text, term_type, datatype_id "
        f"FROM {SP}_term WHERE datatype_id = 9 LIMIT 1"
    )
    if dt_row:
        print(f"\n=== Sample dateTime term ===")
        print(f"  uuid={dt_row['term_uuid']}  text={dt_row['term_text']}  type={dt_row['term_type']}  dt_id={dt_row['datatype_id']}")

    # 5. Check if term_text+term_type is unique (constraint)
    constraints = await conn.fetch(f"""
        SELECT conname, contype, pg_get_constraintdef(oid) as def
        FROM pg_constraint
        WHERE conrelid = '{SP}_term'::regclass
    """)
    print(f"\n=== Constraints ===")
    for c in constraints:
        print(f"  {c['conname']} ({c['contype']}): {c['def']}")

    await conn.close()

asyncio.run(main())
