"""Load-test data — space/graph/entity pool for the load driver.

Template committed with an empty ENTITY_DATA; `setup.py` overwrites this file
locally with the URIs it created (run setup before the load test).
"""

LOAD_TEST_SPACE_ID = "kg_load_test"
LOAD_TEST_GRAPH_ID = "urn:kg_load_test_graph"

# Populated by setup.py — each entry: {"uri": "...", "name": "..."}
ENTITY_DATA = []


def get_entity_uris():
    return [e["uri"] for e in ENTITY_DATA]


def get_entity_names():
    return [e["name"] for e in ENTITY_DATA]
