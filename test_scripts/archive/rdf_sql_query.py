from rdflib import Graph, URIRef
from sqlalchemy.engine import URL
from vitalgraph.store.store import VitalGraphSQLStore

PG_HOST     = "127.0.0.1"
PG_PORT     = 5432
PG_USER     = "postgres"
PG_PASSWORD = ""
PG_DATABASE = "vitalgraphdb"

# The same graph name you used when creating the tables
GRAPH_NAME = "test_graph1"

def main():
    # Build a fully-qualified VitalGraphSQLStore URL object for psycopg3
    db_url = URL.create(
        drivername="postgresql+psycopg",
        username=PG_USER,
        password=PG_PASSWORD or None,
        host=PG_HOST,
        port=PG_PORT,
        database=PG_DATABASE,
    )

    store = VitalGraphSQLStore()

    graph_iri = URIRef(f"http://example.org/{GRAPH_NAME}")

    g = Graph(store=store, identifier=graph_iri)

    g.open(db_url)
    print(f"Connected to graph “{GRAPH_NAME}” in PostgreSQL at {db_url}")

    sparql = """
      SELECT ?s ?p ?o
    WHERE {
      ?s ?p ?o .
    }
    """

    print("Querying for all triples…")
    for row in g.query(sparql):
        print(f"{row.s}  {row.p}  {row.o}")

    sparql = """
    PREFIX foaf: <http://xmlns.com/foaf/0.1/>
    SELECT DISTINCT ?person WHERE {
      ?person a foaf:Person .
    }
    """

    print("Querying for all foaf:Person subjects…")
    for row in g.query(sparql):
        print(row.person)

    g.close()

if __name__ == "__main__":
    main()