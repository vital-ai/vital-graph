"""Smoke test for SPARQL Compiler Sidecar running on localhost:7070"""
import json
import urllib.request

BASE = "http://localhost:7070"

def post_compile(sparql, phases=None):
    body = {"sparql": sparql}
    if phases:
        body["phases"] = phases
    body["trace"] = {"includeTiming": True, "includeWarnings": True, "includePretty": True}
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{BASE}/v1/sparql/compile",
                                data=data,
                                headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        raise Exception(f"HTTP {e.code}: {error_body[:300]}")

def test_health():
    with urllib.request.urlopen(f"{BASE}/health", timeout=5) as resp:
        data = json.loads(resp.read())
    print(f"✓ Health: {data}")
    assert data["status"] == "ok"

def test_select():
    r = post_compile("SELECT ?s ?o WHERE { ?s <http://example.org/p> ?o } LIMIT 10")
    assert r["ok"], f"Expected ok=true, got: {json.dumps(r, indent=2)[:500]}"
    pq = r["phases"]["parsedQuery"]
    assert pq["sparqlForm"] == "QUERY", f"sparqlForm={pq.get('sparqlForm')}"
    assert pq["queryType"] == "SELECT", f"queryType={pq.get('queryType')}"
    assert "s" in pq["projectVars"], f"projectVars={pq.get('projectVars')}"
    assert pq["limit"] == 10, f"limit={pq.get('limit')}"
    alg = r["phases"]["algebraCompiled"]
    top_type = alg["op"]["type"]
    assert top_type in ("OpProject", "OpSlice"), f"op type={top_type}"
    assert alg["pretty"] is not None
    print(f"✓ SELECT: vars={pq['projectVars']}, limit={pq['limit']}, op={top_type}")

def test_select_filter():
    r = post_compile('SELECT ?s WHERE { ?s <http://ex.org/name> ?n . FILTER(CONTAINS(?n, "John")) }')
    assert r["ok"]
    print(f"✓ SELECT+FILTER: op={r['phases']['algebraCompiled']['op']['type']}")

def test_select_optional():
    r = post_compile("SELECT ?s ?name ?age WHERE { ?s <http://ex.org/name> ?name . OPTIONAL { ?s <http://ex.org/age> ?age } }")
    assert r["ok"]
    pretty = r["phases"]["algebraCompiled"]["pretty"]
    assert "leftjoin" in pretty.lower() or "LeftJoin" in pretty
    print(f"✓ SELECT+OPTIONAL: has leftjoin in algebra")

def test_construct():
    r = post_compile("CONSTRUCT { ?s <http://ex.org/label> ?name } WHERE { ?s <http://ex.org/name> ?name }")
    assert r["ok"]
    assert r["phases"]["parsedQuery"]["queryType"] == "CONSTRUCT"
    print(f"✓ CONSTRUCT: template={len(r['phases']['parsedQuery'].get('constructTemplate', []))} triples")

def test_ask():
    r = post_compile("ASK { <http://ex.org/p1> a <http://ex.org/Person> }")
    assert r["ok"]
    assert r["phases"]["parsedQuery"]["queryType"] == "ASK"
    print(f"✓ ASK")

def test_describe():
    r = post_compile("DESCRIBE <http://ex.org/person1>")
    assert r["ok"]
    assert r["phases"]["parsedQuery"]["queryType"] == "DESCRIBE"
    print(f"✓ DESCRIBE")

def test_insert_data():
    r = post_compile('INSERT DATA { <http://ex.org/s1> <http://ex.org/p1> "hello" }')
    assert r["ok"]
    assert r["phases"]["parsedQuery"]["sparqlForm"] == "UPDATE"
    ops = r["phases"]["updateOperations"]
    assert ops[0]["type"] == "UpdateDataInsert"
    quads = ops[0]["quads"]
    assert quads[0]["subject"]["value"] == "http://ex.org/s1"
    print(f"✓ INSERT DATA: {len(quads)} quad(s)")

def test_delete_insert_where():
    r = post_compile("DELETE { ?s <http://ex.org/old> ?o } INSERT { ?s <http://ex.org/new> ?o } WHERE { ?s <http://ex.org/old> ?o }")
    assert r["ok"]
    ops = r["phases"]["updateOperations"]
    assert ops[0]["type"] == "UpdateModify"
    assert len(ops[0]["deleteQuads"]) > 0
    assert len(ops[0]["insertQuads"]) > 0
    assert ops[0]["wherePattern"] is not None
    print(f"✓ DELETE/INSERT WHERE: del={len(ops[0]['deleteQuads'])}, ins={len(ops[0]['insertQuads'])}")

def test_clear():
    r = post_compile("CLEAR GRAPH <http://ex.org/graph1>")
    assert r["ok"]
    ops = r["phases"]["updateOperations"]
    assert ops[0]["type"] == "UpdateClear"
    assert ops[0]["target"]["scope"] == "GRAPH"
    print(f"✓ CLEAR GRAPH")

def test_load():
    r = post_compile("LOAD <http://example.org/data.ttl> INTO GRAPH <http://ex.org/g1>")
    assert r["ok"]
    ops = r["phases"]["updateOperations"]
    assert ops[0]["type"] == "UpdateLoad"
    print(f"✓ LOAD: source={ops[0]['source']}")

def test_parse_error():
    r = post_compile("SELCT ?s WHERE { ?s ?p ?o }")
    assert not r["ok"]
    assert r["error"]["code"] == "PARSE_ERROR"
    print(f"✓ PARSE_ERROR: {r['error']['message'][:60]}...")

def test_timing():
    r = post_compile("SELECT ?s WHERE { ?s ?p ?o }")
    timing = r["meta"]["timingMs"]
    assert "parse" in timing
    print(f"✓ Timing: {timing}")

if __name__ == "__main__":
    tests = [
        test_health, test_select, test_select_filter, test_select_optional,
        test_construct, test_ask, test_describe,
        test_insert_data, test_delete_insert_where, test_clear, test_load,
        test_parse_error, test_timing,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"✗ {t.__name__}: {e}")
            failed += 1
    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)}")
