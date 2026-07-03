"""API tests: Multi-Vector Semantic Search (end-to-end with real embeddings).

True multi-vector case: each KGEntity has TWO distinct vectors — one in a
"category" index (general professional type) and one in a "specialty" index
(specific activity/domain). The queries then search BOTH indexes simultaneously,
fusing scores with weights to find entities that match across both semantic
dimensions.

Workflow:
  1. Create real KGEntities in the graph
  2. Create two vector indexes (category + specialty), 384-dim vitalsigns provider
  3. Vectorize DIFFERENT text per index per entity, upsert distinct embeddings
  4. Run multi-vector search_text queries against both indexes
  5. Assert that semantically relevant entities rank higher
  6. Cleanup
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from ai_haley_kg_domain.model.KGEntity import KGEntity
from vital_ai_vitalsigns.embedding.embedding_model import EmbeddingModel

from vitalgraph.model.kgqueries_model import KGQueryCriteria
from vitalgraph.model.kgentities_model import (
    MultiVectorSearchCriteria,
    WeightedVectorInput,
)

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

# Two indexes representing ORTHOGONAL semantic dimensions
INDEX_PROFESSION = f"mv_sem_prof_{uuid.uuid4().hex[:6]}"  # what is their job?
INDEX_FOOD = f"mv_sem_food_{uuid.uuid4().hex[:6]}"        # what food do they like?
DIMENSIONS = 384  # paraphrase-MiniLM

NS = "urn:test:mvsem:"

# Source texts for vectorization — completely DIFFERENT semantic dimensions.
# INDEX_PROFESSION: "what is this person's job?"
# INDEX_FOOD: "what is this person's favorite food?"
# These are orthogonal axes — knowing someone is a plumber tells you nothing
# about whether they like sushi or pizza.
ENTITY_TEXTS = {
    "alice": {
        "profession": "software engineer programmer developer coding algorithms",
        "food": "sushi sashimi Japanese cuisine raw fish miso soup ramen",
    },
    "bob": {
        "profession": "software engineer programmer developer coding algorithms",
        "food": "pizza pepperoni mozzarella Italian marinara garlic bread",
    },
    "carol": {
        "profession": "professional chef cook culinary arts restaurant kitchen",
        "food": "sushi sashimi Japanese cuisine raw fish miso soup ramen",
    },
    "dave": {
        "profession": "professional chef cook culinary arts restaurant kitchen",
        "food": "pizza pepperoni mozzarella Italian marinara garlic bread",
    },
}


def _make_entity(uri: str, name: str) -> KGEntity:
    e = KGEntity()
    e.URI = uri
    e.name = name
    return e


def _embed(text: str) -> list[float]:
    """Vectorize text using the same local ONNX model the server uses."""
    import numpy as np
    model = EmbeddingModel()
    result = model.vectorize(text)
    if isinstance(result, np.ndarray):
        return result.tolist()  # type: ignore[return-value]
    return [float(x) for x in result]  # type: ignore[arg-type]


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def semantic_env(vg_client, test_space, test_graph):
    """Create 4 entities, each with TWO distinct vectors (profession + food).

    Matrix:
      - Alice: engineer + sushi
      - Bob:   engineer + pizza
      - Carol: chef     + sushi
      - Dave:  chef     + pizza
    """
    uris = {
        "alice": f"{NS}alice_{uuid.uuid4().hex[:6]}",
        "bob": f"{NS}bob_{uuid.uuid4().hex[:6]}",
        "carol": f"{NS}carol_{uuid.uuid4().hex[:6]}",
        "dave": f"{NS}dave_{uuid.uuid4().hex[:6]}",
    }

    # Create real KGEntities
    entities = [
        _make_entity(uris["alice"], "Alice - Software Engineer who loves sushi"),
        _make_entity(uris["bob"], "Bob - Software Engineer who loves pizza"),
        _make_entity(uris["carol"], "Carol - Professional Chef who loves sushi"),
        _make_entity(uris["dave"], "Dave - Professional Chef who loves pizza"),
    ]
    await vg_client.kgentities.create_kgentities(
        space_id=test_space, graph_id=test_graph, objects=entities
    )

    # Create two vector indexes (orthogonal dimensions)
    await vg_client.vector_indexes.create_index(
        space_id=test_space,
        index_name=INDEX_PROFESSION,
        dimensions=DIMENSIONS,
        distance_metric="cosine",
        provider="vitalsigns",
        description="Profession/job description embeddings",
    )
    await vg_client.vector_indexes.create_index(
        space_id=test_space,
        index_name=INDEX_FOOD,
        dimensions=DIMENSIONS,
        distance_metric="cosine",
        provider="vitalsigns",
        description="Favorite food embeddings",
    )

    # Vectorize and upsert PROFESSION vectors (from profession text)
    prof_vectors = []
    for key, uri in uris.items():
        embedding = _embed(ENTITY_TEXTS[key]["profession"])
        prof_vectors.append({
            "subject_uri": uri,
            "graph_uri": test_graph,
            "embedding": embedding,
        })
    await vg_client.vector_indexes.upsert_vectors(
        space_id=test_space,
        index_name=INDEX_PROFESSION,
        vectors=prof_vectors,
    )

    # Vectorize and upsert FOOD vectors (from food text)
    food_vectors = []
    for key, uri in uris.items():
        embedding = _embed(ENTITY_TEXTS[key]["food"])
        food_vectors.append({
            "subject_uri": uri,
            "graph_uri": test_graph,
            "embedding": embedding,
        })
    await vg_client.vector_indexes.upsert_vectors(
        space_id=test_space,
        index_name=INDEX_FOOD,
        vectors=food_vectors,
    )

    yield {
        "space_id": test_space,
        "graph_id": test_graph,
        "index_profession": INDEX_PROFESSION,
        "index_food": INDEX_FOOD,
        "uris": uris,
    }

    # Cleanup
    for uri in uris.values():
        try:
            await vg_client.kgentities.delete_kgentity(test_space, test_graph, uri)
        except Exception:
            pass
    for idx in [INDEX_PROFESSION, INDEX_FOOD]:
        try:
            await vg_client.vector_indexes.delete_index(test_space, idx)
        except Exception:
            pass


class TestSemanticMultiVectorRanking:
    """Validate multi-vector ranking across orthogonal semantic dimensions.

    Entity matrix:
      - Alice: engineer + sushi
      - Bob:   engineer + pizza
      - Carol: chef     + sushi
      - Dave:  chef     + pizza

    Each entity has a DIFFERENT vector in each index.
    Multi-vector queries combine profession + food to find the best match.
    """

    async def test_engineer_who_likes_sushi(self, vg_client, semantic_env):
        """Query 'software engineer' + 'sushi' — Alice matches both dimensions."""
        criteria = KGQueryCriteria(
            query_type="entity",
            multi_vector_criteria=MultiVectorSearchCriteria(
                vectors=[
                    WeightedVectorInput(
                        search_text="software engineer programmer developer",
                        index_name=semantic_env["index_profession"],
                        weight=0.5,
                    ),
                    WeightedVectorInput(
                        search_text="sushi sashimi Japanese food raw fish",
                        index_name=semantic_env["index_food"],
                        weight=0.5,
                    ),
                ],
                top_k=4,
            ),
        )
        resp = await vg_client.kgqueries.query_connections(
            space_id=semantic_env["space_id"],
            graph_id=semantic_env["graph_id"],
            criteria=criteria,
            page_size=10,
        )
        uris = resp.entity_uris or []
        assert len(uris) >= 2, f"Expected at least 2 results, got {len(uris)}"
        # Alice is the ONLY entity matching BOTH dimensions perfectly
        assert uris[0] == semantic_env["uris"]["alice"], (
            f"Alice should rank first (engineer+sushi), got: {uris}"
        )
        # Dave (chef+pizza) should rank last — wrong on both dimensions
        dave_idx = uris.index(semantic_env["uris"]["dave"]) if semantic_env["uris"]["dave"] in uris else 99
        assert dave_idx == len(uris) - 1, (
            f"Dave should rank last (wrong profession + wrong food), got idx={dave_idx}: {uris}"
        )

    async def test_chef_who_likes_pizza(self, vg_client, semantic_env):
        """Query 'chef cook' + 'pizza Italian' — Dave matches both dimensions."""
        criteria = KGQueryCriteria(
            query_type="entity",
            multi_vector_criteria=MultiVectorSearchCriteria(
                vectors=[
                    WeightedVectorInput(
                        search_text="professional chef cook culinary kitchen",
                        index_name=semantic_env["index_profession"],
                        weight=0.5,
                    ),
                    WeightedVectorInput(
                        search_text="pizza pepperoni mozzarella Italian food",
                        index_name=semantic_env["index_food"],
                        weight=0.5,
                    ),
                ],
                top_k=4,
            ),
        )
        resp = await vg_client.kgqueries.query_connections(
            space_id=semantic_env["space_id"],
            graph_id=semantic_env["graph_id"],
            criteria=criteria,
            page_size=10,
        )
        uris = resp.entity_uris or []
        assert len(uris) >= 2, f"Expected at least 2 results, got {len(uris)}"
        # Dave is the ONLY entity matching BOTH dimensions perfectly
        assert uris[0] == semantic_env["uris"]["dave"], (
            f"Dave should rank first (chef+pizza), got: {uris}"
        )
        # Alice (engineer+sushi) should rank last — wrong on both
        alice_idx = uris.index(semantic_env["uris"]["alice"]) if semantic_env["uris"]["alice"] in uris else 99
        assert alice_idx == len(uris) - 1, (
            f"Alice should rank last (wrong profession + wrong food), got idx={alice_idx}: {uris}"
        )

    async def test_weight_on_profession_disambiguates_same_food(self, vg_client, semantic_env):
        """Both Alice and Carol like sushi. Heavy profession weight picks the engineer.

        Query: 'engineer' (profession) + 'sushi' (food), weight 0.9 on profession.
        Alice (engineer+sushi) should beat Carol (chef+sushi).
        """
        criteria = KGQueryCriteria(
            query_type="entity",
            multi_vector_criteria=MultiVectorSearchCriteria(
                vectors=[
                    WeightedVectorInput(
                        search_text="software engineer programmer developer",
                        index_name=semantic_env["index_profession"],
                        weight=0.9,
                    ),
                    WeightedVectorInput(
                        search_text="sushi sashimi Japanese food",
                        index_name=semantic_env["index_food"],
                        weight=0.1,
                    ),
                ],
                top_k=4,
            ),
        )
        resp = await vg_client.kgqueries.query_connections(
            space_id=semantic_env["space_id"],
            graph_id=semantic_env["graph_id"],
            criteria=criteria,
            page_size=10,
        )
        uris = resp.entity_uris or []
        assert len(uris) >= 2, f"Expected at least 2 results, got {len(uris)}"
        # Both Alice and Bob are engineers; Alice also likes sushi
        # With 0.9 profession weight, engineers (Alice, Bob) should dominate
        assert uris[0] in [semantic_env["uris"]["alice"], semantic_env["uris"]["bob"]], (
            f"An engineer should rank first with heavy profession weight, got: {uris}"
        )

    async def test_weight_on_food_disambiguates_same_profession(self, vg_client, semantic_env):
        """Both Alice and Bob are engineers. Heavy food weight picks the sushi lover.

        Query: 'engineer' (profession) + 'sushi' (food), weight 0.9 on food.
        Alice (engineer+sushi) and Carol (chef+sushi) should beat Bob (engineer+pizza).
        """
        criteria = KGQueryCriteria(
            query_type="entity",
            multi_vector_criteria=MultiVectorSearchCriteria(
                vectors=[
                    WeightedVectorInput(
                        search_text="software engineer programmer developer",
                        index_name=semantic_env["index_profession"],
                        weight=0.1,
                    ),
                    WeightedVectorInput(
                        search_text="sushi sashimi Japanese food raw fish",
                        index_name=semantic_env["index_food"],
                        weight=0.9,
                    ),
                ],
                top_k=4,
            ),
        )
        resp = await vg_client.kgqueries.query_connections(
            space_id=semantic_env["space_id"],
            graph_id=semantic_env["graph_id"],
            criteria=criteria,
            page_size=10,
        )
        uris = resp.entity_uris or []
        assert len(uris) >= 2, f"Expected at least 2 results, got {len(uris)}"
        # With 0.9 food weight, sushi lovers (Alice, Carol) should dominate
        assert uris[0] in [semantic_env["uris"]["alice"], semantic_env["uris"]["carol"]], (
            f"A sushi lover should rank first with heavy food weight, got: {uris}"
        )
        # Pizza lovers should be in the bottom half
        bob_idx = uris.index(semantic_env["uris"]["bob"]) if semantic_env["uris"]["bob"] in uris else 99
        dave_idx = uris.index(semantic_env["uris"]["dave"]) if semantic_env["uris"]["dave"] in uris else 99
        assert bob_idx >= 2, f"Bob (pizza) should rank low with sushi-heavy query, got idx={bob_idx}: {uris}"
        assert dave_idx >= 2, f"Dave (pizza) should rank low with sushi-heavy query, got idx={dave_idx}: {uris}"
