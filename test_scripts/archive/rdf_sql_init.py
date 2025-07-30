import logging
from rdflib import Graph, URIRef
from rdflib import Namespace, RDF, Literal
from rdflib.namespace import FOAF
from vitalgraph.store.store import VitalGraphSQLStore

PG_HOST     = "127.0.0.1"
PG_PORT     = 5432
PG_USER     = "postgres"
PG_PASSWORD = ""           # empty password
PG_DATABASE = "vitalgraphdb"

GRAPH_NAME = "test_graph1"


def main():
    # Enable INFO‐level logging so you can see VitalGraphSQLStore DDL/DML
    logging.basicConfig(level=logging.INFO)

    # Build the VitalGraphSQLStore connection URI.
    # If PG_PASSWORD is empty, omit the colon:
    DRIVER = "postgresql+psycopg"  # tells VitalGraphSQLStore to use psycopg3 (v3 driver)
    if PG_PASSWORD:
        db_uri = f"{DRIVER}://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}"
    else:
        db_uri = f"{DRIVER}://{PG_USER}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}"

    store = VitalGraphSQLStore()

    EX = Namespace("http://example.org/")

    g = Graph(store=store, identifier=URIRef(f"http://example.org/{GRAPH_NAME}"))

    g.open(db_uri, create=True)

    print(f"Initialized graph in PostgreSQL at {db_uri}")

    # Choose a small RDF dataset for testing (FOAF RDF/XML)
    dataset_url = "http://xmlns.com/foaf/spec/index.rdf"

    g.parse(dataset_url, format="xml")

    g.add((EX.alice, RDF.type, FOAF.Person))
    g.add((EX.alice, FOAF.name, Literal("Alice")))
    g.add((EX.bob, RDF.type, FOAF.Person))
    g.add((EX.bob, FOAF.name, Literal("Bob")))

    print(f"Loaded {len(g)} triples from {dataset_url}")

    g.close()

if __name__ == "__main__":
    main()