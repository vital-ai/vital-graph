"""Test: simulate touch_entity_modification_time and check term creation."""
import asyncio, os, sys, uuid
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()
import asyncpg
from datetime import datetime, timezone

SP = "space_multi_org_crud_test"
_VITALGRAPH_NS = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')
MODIFICATION_TIME_URI = "http://vital.ai/ontology/vital#hasObjectModificationDateTime"
XSD_DT = "http://www.w3.org/2001/XMLSchema#dateTime"


def _term_uuid_v5(text, term_type='U', lang=None, datatype_id=None):
    parts = [text, term_type]
    if lang is not None:
        parts.append(f"lang:{lang}")
    if datatype_id is not None:
        parts.append(f"datatype:{datatype_id}")
    return uuid.uuid5(_VITALGRAPH_NS, "\x00".join(parts))


async def main():
    h = os.environ.get("LOCAL_DB_HOST", "localhost")
    p = os.environ.get("LOCAL_DB_PORT", "5432")
    d = os.environ.get("LOCAL_DB_NAME", "sparql_sql_graph")
    u = os.environ.get("LOCAL_DB_USERNAME", "postgres")
    pw = os.environ.get("LOCAL_DB_PASSWORD", "")
    conn = await asyncpg.connect(f"postgresql://{u}:{pw}@{h}:{p}/{d}")

    # Find an existing ObjectModificationDateTime term
    row = await conn.fetchrow(f"""
        SELECT t.term_uuid, t.term_text, t.datatype_id
        FROM {SP}_rdf_quad q
        JOIN {SP}_term pt ON q.predicate_uuid = pt.term_uuid
        JOIN {SP}_term t ON q.object_uuid = t.term_uuid
        WHERE pt.term_text = '{MODIFICATION_TIME_URI}'
        LIMIT 1
    """)
    if not row:
        print("No ObjectModificationDateTime found!")
        await conn.close()
        return

    stored_uuid = row['term_uuid']
    stored_text = row['term_text']
    stored_dt_id = row['datatype_id']

    print(f"=== Existing stored term ===")
    print(f"  text: {stored_text}")
    print(f"  stored UUID:     {stored_uuid}")
    print(f"  stored dt_id:    {stored_dt_id}")

    # Compute what deterministic UUID v5 would give
    det_uuid_with_dt = _term_uuid_v5(stored_text, 'L', datatype_id=stored_dt_id)
    det_uuid_no_dt = _term_uuid_v5(stored_text, 'L', datatype_id=None)
    print(f"  deterministic UUID (dt_id={stored_dt_id}): {det_uuid_with_dt}")
    print(f"  deterministic UUID (dt_id=None):  {det_uuid_no_dt}")
    print(f"  stored matches det(dt_id={stored_dt_id})?: {stored_uuid == det_uuid_with_dt}")
    print(f"  stored matches det(no dt)?:  {stored_uuid == det_uuid_no_dt}")

    # Now check: if _term_upsert creates a NEW dateTime literal with gen_random_uuid(),
    # what UUID would the quad get vs what a deterministic lookup would expect?
    new_dt_text = "2099-01-01T00:00:00+00:00"
    
    # Simulate what _term_upsert does
    print(f"\n=== Simulating _term_upsert for new value: {new_dt_text} ===")
    
    # Check: does this term already exist?
    existing = await conn.fetchrow(f"""
        SELECT term_uuid, datatype_id 
        FROM {SP}_term 
        WHERE term_text = '{new_dt_text}' AND term_type = 'L'
    """)
    if existing:
        print(f"  Term already exists: uuid={existing['term_uuid']} dt_id={existing['datatype_id']}")
    else:
        print(f"  Term does NOT exist yet")
        # _term_upsert would create it with gen_random_uuid() and NO datatype_id
        # What UUID would it get?
        print(f"  _term_upsert would create: gen_random_uuid(), datatype_id=NULL")
        det = _term_uuid_v5(new_dt_text, 'L', datatype_id=9)
        print(f"  Deterministic UUID (dt_id=9): {det}")
        print(f"  These will NEVER match → quad lookup by deterministic UUID fails")

    # Check: is the STORED uuid deterministic or random?
    # Look at ALL datetime terms and check if they match deterministic pattern
    dt_terms = await conn.fetch(f"""
        SELECT term_uuid, term_text, datatype_id
        FROM {SP}_term
        WHERE datatype_id = 9
        LIMIT 20
    """)
    print(f"\n=== All dateTime terms: deterministic vs stored UUID ===")
    match_count = 0
    mismatch_count = 0
    for t in dt_terms:
        det = _term_uuid_v5(t['term_text'], 'L', datatype_id=t['datatype_id'])
        matches = (t['term_uuid'] == det)
        if matches:
            match_count += 1
        else:
            mismatch_count += 1
            print(f"  MISMATCH: text={t['term_text'][:40]}  stored={t['term_uuid']}  expected={det}")
    print(f"  {match_count} match, {mismatch_count} mismatch")

    await conn.close()

asyncio.run(main())
