"""Test: verify emit_update.py fix generates deterministic UUIDs with datatype_id.

Directly unit-tests the core helpers (_term_upsert, _term_uuid_subquery,
_insert_data_sql, _delete_data_sql) without needing the Jena sidecar.
"""
import sys, uuid
sys.path.insert(0, '.')

from vitalgraph.db.sparql_sql.emit_update import (
    _generate_term_uuid,
    _term_upsert,
    _term_uuid_subquery,
    _insert_data_sql,
    _delete_data_sql,
    _node_datatype_uri,
)
from vitalgraph.db.jena_sparql.jena_types import (
    URINode, LiteralNode, QuadPattern,
)

_VITALGRAPH_NS = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')
XSD_DT = "http://www.w3.org/2001/XMLSchema#dateTime"
DT_ID = 9  # typical dateTime datatype_id
TERM_TABLE = "space_test_term"

passed = 0
failed = 0

def check(label, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  ✅ {label}")
        passed += 1
    else:
        print(f"  ❌ {label}  {detail}")
        failed += 1


print("=== Test 1: _generate_term_uuid includes datatype_id ===")
uuid_no_dt = _generate_term_uuid("2099-01-01T00:00:00+00:00", "L")
uuid_with_dt = _generate_term_uuid("2099-01-01T00:00:00+00:00", "L", datatype_id=DT_ID)
check("UUIDs differ when datatype_id added", uuid_no_dt != uuid_with_dt,
      f"both={uuid_no_dt}")
check("UUID is deterministic (same inputs -> same output)",
      uuid_with_dt == _generate_term_uuid("2099-01-01T00:00:00+00:00", "L", datatype_id=DT_ID))
check("Matches sparql_sql_space_impl formula",
      uuid_with_dt == uuid.uuid5(
          _VITALGRAPH_NS,
          "\x00".join(["2099-01-01T00:00:00+00:00", "L", f"datatype:{DT_ID}"])))


print("\n=== Test 2: _term_upsert uses deterministic UUID and datatype_id ===")
sql = _term_upsert(TERM_TABLE, "2099-01-01T00:00:00+00:00", "L", datatype_id=DT_ID)
check("No gen_random_uuid()", "gen_random_uuid" not in sql, sql[:80])
check("Contains deterministic UUID", str(uuid_with_dt) in sql)
check("Contains datatype_id column value", f", {DT_ID} " in sql or f", {DT_ID}\n" in sql,
      sql[:120])
check("WHERE uses term_uuid (not term_text)", "WHERE term_uuid =" in sql, sql)


print("\n=== Test 3: _term_uuid_subquery for typed literal ===")
expr = _term_uuid_subquery(TERM_TABLE, "2099-01-01T00:00:00+00:00", "L", datatype_id=DT_ID)
check("Returns inline UUID (no subquery)", "SELECT" not in expr, expr)
check("Contains correct UUID", str(uuid_with_dt) in expr)
check("Has ::uuid cast", "::uuid" in expr)


print("\n=== Test 4: _term_uuid_subquery for URI (no datatype) ===")
uri_expr = _term_uuid_subquery(TERM_TABLE, "http://example.org/foo", "U")
uri_uuid = _generate_term_uuid("http://example.org/foo", "U")
check("Returns inline UUID for URI", str(uri_uuid) in uri_expr)


print("\n=== Test 5: _term_uuid_subquery for plain literal (no datatype) ===")
plain_expr = _term_uuid_subquery(TERM_TABLE, "hello world", "L")
check("Falls back to text+type subquery", "SELECT term_uuid" in plain_expr)


print("\n=== Test 6: _insert_data_sql uses deterministic UUIDs ===")
dt_map = {XSD_DT: DT_ID}
quads = [QuadPattern(
    graph=URINode("urn:graph:test"),
    subject=URINode("urn:entity:001"),
    predicate=URINode("http://vital.ai/ontology/vital#hasObjectModificationDateTime"),
    object=LiteralNode("2099-01-01T00:00:00+00:00", datatype=XSD_DT),
)]
insert_sql = _insert_data_sql(quads, "space_test", dt_map=dt_map)
check("No gen_random_uuid() in INSERT DATA", "gen_random_uuid" not in insert_sql)
check("Contains typed literal UUID", str(uuid_with_dt) in insert_sql)
check("Contains datatype_id in term upsert", f", {DT_ID} " in insert_sql)
check("Has WHERE NOT EXISTS for quad dedup", "WHERE NOT EXISTS" in insert_sql)


print("\n=== Test 7: _delete_data_sql uses deterministic UUID for object ===")
delete_sql = _delete_data_sql(quads, "space_test", dt_map=dt_map)
check("Contains typed literal UUID in DELETE", str(uuid_with_dt) in delete_sql)


print("\n=== Test 8: _node_datatype_uri extracts datatype ===")
lit = LiteralNode("x", datatype=XSD_DT)
check("Returns datatype URI", _node_datatype_uri(lit) == XSD_DT)
check("Returns None for URI node", _node_datatype_uri(URINode("x")) is None)
check("Returns None for plain literal", _node_datatype_uri(LiteralNode("x")) is None)


print(f"\n{'='*50}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
else:
    print("All tests passed!")
