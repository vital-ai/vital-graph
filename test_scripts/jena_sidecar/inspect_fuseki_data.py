"""
Query lead_test data directly from Fuseki to inspect datatype annotations.
Compares how Fuseki stores literals vs PostgreSQL (which strips datatypes).
"""

import json
import urllib.request

FUSEKI_URL = "http://localhost:3030"
DATASET = "vitalgraph_space_lead_test"


def query_fuseki(sparql):
    """Execute SPARQL query against local Fuseki, return raw JSON results."""
    url = f"{FUSEKI_URL}/{DATASET}/query"
    data = urllib.parse.urlencode({"query": sparql}).encode()
    req = urllib.request.Request(url, data=data,
                                headers={"Accept": "application/sparql-results+json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()[:300]}")
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None


import urllib.parse

def print_bindings(results, max_rows=20):
    """Print SPARQL result bindings showing full type info."""
    if not results or "results" not in results:
        print("  No results")
        return
    bindings = results["results"]["bindings"]
    print(f"  {len(bindings)} result(s)")
    for i, row in enumerate(bindings[:max_rows]):
        parts = []
        for var, val in row.items():
            vtype = val.get("type", "?")
            value = val.get("value", "")[:80]
            extra = ""
            if "datatype" in val:
                extra = f"  ^^<{val['datatype']}>"
            if "xml:lang" in val:
                extra = f"  @{val['xml:lang']}"
            parts.append(f"    {var} = [{vtype}] {value}{extra}")
        print(f"  Row {i+1}:")
        for p in parts:
            print(p)


def main():
    print("=" * 70)
    print("Fuseki Data Inspection — lead_test")
    print(f"Endpoint: {FUSEKI_URL}/{DATASET}/query")
    print("=" * 70)

    # 1. Count triples
    print("\n--- Total triples ---")
    r = query_fuseki("SELECT (COUNT(*) AS ?count) WHERE { ?s ?p ?o }")
    print_bindings(r)

    # 2. Count triples in named graph
    print("\n--- Triples in urn:lead_test graph ---")
    r = query_fuseki("SELECT (COUNT(*) AS ?count) WHERE { GRAPH <urn:lead_test> { ?s ?p ?o } }")
    print_bindings(r)

    # 3. Sample triples with full type info (look for datatypes)
    print("\n--- Sample triples (raw, 10 rows) ---")
    r = query_fuseki("""
        SELECT ?s ?p ?o WHERE { 
            GRAPH <urn:lead_test> { ?s ?p ?o }
        } LIMIT 10
    """)
    print_bindings(r)

    # 4. Integer slot values — check for xsd:integer datatype
    print("\n--- Integer slot values (hasIntegerSlotValue) ---")
    r = query_fuseki("""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        SELECT ?slot ?value WHERE {
            GRAPH <urn:lead_test> {
                ?slot haley:hasIntegerSlotValue ?value
            }
        } LIMIT 10
    """)
    print_bindings(r)

    # 5. DateTime slot values — check for xsd:dateTime datatype
    print("\n--- DateTime slot values (hasDateTimeSlotValue) ---")
    r = query_fuseki("""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        SELECT ?slot ?value WHERE {
            GRAPH <urn:lead_test> {
                ?slot haley:hasDateTimeSlotValue ?value
            }
        } LIMIT 10
    """)
    print_bindings(r)

    # 6. Boolean slot values
    print("\n--- Boolean slot values (hasBooleanSlotValue) ---")
    r = query_fuseki("""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        SELECT ?slot ?value WHERE {
            GRAPH <urn:lead_test> {
                ?slot haley:hasBooleanSlotValue ?value
            }
        } LIMIT 10
    """)
    print_bindings(r)

    # 7. Text slot values — check if plain literal or xsd:string
    print("\n--- Text slot values (hasTextSlotValue) ---")
    r = query_fuseki("""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        SELECT ?slot ?value WHERE {
            GRAPH <urn:lead_test> {
                ?slot haley:hasTextSlotValue ?value
            }
        } LIMIT 10
    """)
    print_bindings(r)

    # 8. Double/Currency slot values
    print("\n--- Double slot values (hasDoubleSlotValue) ---")
    r = query_fuseki("""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        SELECT ?slot ?value WHERE {
            GRAPH <urn:lead_test> {
                ?slot haley:hasDoubleSlotValue ?value
            }
        } LIMIT 5
    """)
    print_bindings(r)

    print("\n--- Currency slot values (hasCurrencySlotValue) ---")
    r = query_fuseki("""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        SELECT ?slot ?value WHERE {
            GRAPH <urn:lead_test> {
                ?slot haley:hasCurrencySlotValue ?value
            }
        } LIMIT 5
    """)
    print_bindings(r)

    # 9. Check distinct datatypes used
    print("\n--- All distinct datatypes in the graph ---")
    r = query_fuseki("""
        SELECT DISTINCT (DATATYPE(?o) AS ?dt) (COUNT(*) AS ?cnt) WHERE {
            GRAPH <urn:lead_test> {
                ?s ?p ?o .
                FILTER(isLiteral(?o))
            }
        } GROUP BY (DATATYPE(?o)) ORDER BY DESC(?cnt)
    """)
    print_bindings(r)

    print("\n" + "=" * 70)
    print("Inspection complete.")


if __name__ == "__main__":
    main()
