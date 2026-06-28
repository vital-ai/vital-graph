"""Quick test: verify _rows_to_sparql_bindings propagates __datatype correctly."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))


def test_bindings():
    from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl

    # Simulate what a BGP query returns for a datetime literal
    row_with_dt = {
        "v0": "http://example.com/entity/1",
        "v0__type": "U",
        "v0__uuid": None,
        "v0__lang": None,
        "v0__datatype": None,
        "v1": "http://vital.ai/ontology/vital-core#hasObjectModificationDateTime",
        "v1__type": "U",
        "v1__uuid": None,
        "v1__lang": None,
        "v1__datatype": None,
        "v2": "2026-04-29T22:58:37.886191+00:00",
        "v2__type": "L",
        "v2__uuid": None,
        "v2__lang": None,
        "v2__datatype": "http://www.w3.org/2001/XMLSchema#dateTime",
    }
    var_map = {"v0": "subject", "v1": "predicate", "v2": "object"}

    bindings = SparqlSQLSpaceImpl._rows_to_sparql_bindings([row_with_dt], var_map)
    obj = bindings[0]["object"]
    print("=== With __datatype populated ===")
    for k, v in obj.items():
        print(f"  {k}: {v!r}")
    assert "datatype" in obj, "FAIL: datatype key missing when __datatype is set!"

    # Now test with __datatype = None (the potentially broken case)
    row_no_dt = dict(row_with_dt)
    row_no_dt["v2__datatype"] = None
    bindings2 = SparqlSQLSpaceImpl._rows_to_sparql_bindings([row_no_dt], var_map)
    obj2 = bindings2[0]["object"]
    print("\n=== With __datatype = None ===")
    for k, v in obj2.items():
        print(f"  {k}: {v!r}")
    assert "datatype" not in obj2, "Expected no datatype key when __datatype is None"

    # Now test the full round-trip through _sparql_binding_to_rdflib
    from vitalgraph.kg_impl.kgentity_frame_create_impl import _sparql_binding_to_rdflib

    lit_with = _sparql_binding_to_rdflib(obj)
    lit_without = _sparql_binding_to_rdflib(obj2)
    print(f"\n=== RDFLib round-trip ===")
    print(f"  With datatype:    {lit_with!r}  datatype={getattr(lit_with, 'datatype', None)}")
    print(f"  Without datatype: {lit_without!r}  datatype={getattr(lit_without, 'datatype', None)}")

    # Now test UUID generation
    import uuid
    _VITALGRAPH_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

    def gen_uuid(text, ttype, lang=None, dt_id=None):
        parts = [text, ttype]
        if lang is not None:
            parts.append(f"lang:{lang}")
        if dt_id is not None:
            parts.append(f"datatype:{dt_id}")
        return uuid.uuid5(_VITALGRAPH_NS, "\x00".join(parts))

    # The original stored UUID (with datatype_id=7 as an example)
    stored_uuid = gen_uuid("2026-04-29T22:58:37.886191+00:00", "L", None, 7)

    # UUID from reconstructed Literal WITH datatype
    from rdflib import Literal, URIRef
    from rdflib.namespace import XSD
    recon_with = Literal("2026-04-29T22:58:37.886191+00:00", datatype=XSD.dateTime)
    # dt_map lookup would give datatype_id=7
    uuid_with = gen_uuid(str(recon_with), "L", None, 7)

    # UUID from reconstructed Literal WITHOUT datatype
    recon_without = Literal("2026-04-29T22:58:37.886191+00:00")
    # dt_map lookup: o.datatype is None, so o_dt = None
    uuid_without = gen_uuid(str(recon_without), "L", None, None)

    print(f"\n=== UUID comparison ===")
    print(f"  Stored UUID (dt_id=7):          {stored_uuid}")
    print(f"  Reconstructed WITH datatype:    {uuid_with}  match={stored_uuid == uuid_with}")
    print(f"  Reconstructed WITHOUT datatype: {uuid_without}  match={stored_uuid == uuid_without}")

    if stored_uuid != uuid_without:
        print("\n  >>> CONFIRMED: Missing datatype causes UUID mismatch <<<")
        print("  >>> DELETE would silently miss the stored quad <<<")

    print("\n=== CONCLUSION ===")
    if "datatype" in obj:
        print("  The SQL pipeline DOES produce __datatype when the column is populated.")
        print("  If deletes are failing, the SQL itself must be returning NULL for __datatype.")
        print("  This means the issue is at query execution time, not code generation time.")
    else:
        print("  BUG: The pipeline drops __datatype even when populated!")


if __name__ == "__main__":
    test_bindings()
