import logging
from rdflib import Graph, URIRef
from vitalgraph.store.store import VitalGraphSQLStore

PG_HOST     = "127.0.0.1"
PG_PORT     = 5432
PG_USER     = "postgres"
PG_PASSWORD = ""           # empty password
PG_DATABASE = "vitalgraphdb"

GRAPH_NAME = "wordnet"


def main():
    # Enable INFO-level logging so you can see VitalGraphSQLStore DDL/DML
    logging.basicConfig(level=logging.INFO)

    # Build the VitalGraphSQLStore connection URI.
    # If PG_PASSWORD is empty, omit the colon:
    DRIVER = "postgresql+psycopg"  # tells VitalGraphSQLStore to use psycopg3 (v3 driver)
    if PG_PASSWORD:
        db_uri = f"{DRIVER}://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}"
    else:
        db_uri = f"{DRIVER}://{PG_USER}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}"

    store = VitalGraphSQLStore()

    graph_uri = f"http://vital.ai/graph/{GRAPH_NAME}"

    g = Graph(store=store, identifier=graph_uri)

    g.open(db_uri, create=True)

    print(f"Initialized WordNet graph in PostgreSQL at {db_uri}")
    print(f"Graph identifier: {graph_uri}")
    print(f"Graph is ready for data loading.")

    g.close()


if __name__ == "__main__":
    main()
