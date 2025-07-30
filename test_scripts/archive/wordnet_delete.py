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

    try:
        g.open(db_uri)
        
        # Get the count of triples before deletion
        triple_count = len(g)
        print(f"Found {triple_count} triples in WordNet graph")
        
        # Remove all triples from the graph
        g.remove((None, None, None))
        
        print(f"Deleted all triples from WordNet graph")
        print(f"Graph '{GRAPH_NAME}' has been cleared")
        
        g.close()
        
    except Exception as e:
        print(f"Error deleting WordNet graph: {e}")
        print("Graph may not exist or may already be empty")


if __name__ == "__main__":
    main()
