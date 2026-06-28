"""Tests for KGQueryCriteriaBuilder vector/geo criteria integration.

Verifies that VectorCriteria, GeoCriteria, and MultiVectorCriteria generate
correct SPARQL with vg: function BINDs, FILTERs, ORDER BY overrides, and
LIMIT overrides.
"""

import pytest

from vitalgraph.sparql.kg_query_builder import (
    KGQueryCriteriaBuilder,
    EntityQueryCriteria,
    FrameQueryCriteria,
    VectorCriteria,
    GeoCriteria,
    MultiVectorCriteria,
    MultiVectorCriteriaInput,
)


@pytest.fixture
def builder():
    return KGQueryCriteriaBuilder()


# ---------------------------------------------------------------------------
# VectorCriteria tests
# ---------------------------------------------------------------------------

class TestVectorCriteria:
    def test_vector_similarity_generates_bind(self, builder):
        vc = VectorCriteria(search_text="machine learning", index_name="my_idx", top_k=5)
        criteria = EntityQueryCriteria(vector_criteria=vc)
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 10, 0)

        assert 'vg:vectorSimilarity(?entity, "machine learning", "my_idx")' in sparql
        assert "?vg_score" in sparql

    def test_vector_similarity_order_by_desc(self, builder):
        vc = VectorCriteria(search_text="test", top_k=10)
        criteria = EntityQueryCriteria(vector_criteria=vc)
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 20, 0)

        assert "ORDER BY DESC(?vg_score)" in sparql

    def test_vector_similarity_overrides_limit(self, builder):
        vc = VectorCriteria(search_text="test", top_k=7)
        criteria = EntityQueryCriteria(vector_criteria=vc)
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 100, 50)

        assert "LIMIT 7" in sparql
        assert "OFFSET 0" in sparql

    def test_vector_similarity_min_score_filter(self, builder):
        vc = VectorCriteria(search_text="test", top_k=10, min_score=0.7)
        criteria = EntityQueryCriteria(vector_criteria=vc)
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 10, 0)

        assert "FILTER(?vg_score > 0.7)" in sparql

    def test_vector_nearby_generates_bind(self, builder):
        vc = VectorCriteria(vector="[0.1,0.2,0.3]", index_name="emb_idx", top_k=20)
        criteria = EntityQueryCriteria(vector_criteria=vc)
        sparql = builder.build_entity_query_sparql(criteria, None, 10, 0)

        assert 'vg:vectorNearby(?entity, "[0.1,0.2,0.3]", "emb_idx")' in sparql
        assert "LIMIT 20" in sparql

    def test_vector_custom_score_variable(self, builder):
        vc = VectorCriteria(search_text="test", top_k=5, score_variable="sim")
        criteria = EntityQueryCriteria(vector_criteria=vc)
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 10, 0)

        assert "?sim" in sparql
        assert "ORDER BY DESC(?sim)" in sparql

    def test_vector_does_not_override_explicit_sort_criteria(self, builder):
        """When sort_criteria is provided, vector ORDER BY does not override."""
        from vitalgraph.sparql.kg_query_builder import SortCriteria
        vc = VectorCriteria(search_text="test", top_k=5)
        sc = SortCriteria(
            sort_type="entity_property",
            property_uri="http://vital.ai/ontology/vital-core#hasName",
            sort_order="asc",
        )
        criteria = EntityQueryCriteria(vector_criteria=vc, sort_criteria=[sc])
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 10, 0)

        # Sort criteria takes priority
        assert "ORDER BY DESC(?vg_score)" not in sparql
        assert "ASC(?sort_val_0)" in sparql

    def test_vector_escapes_quotes_in_text(self, builder):
        vc = VectorCriteria(search_text='say "hello"', top_k=5)
        criteria = EntityQueryCriteria(vector_criteria=vc)
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 10, 0)

        assert '\\"hello\\"' in sparql


# ---------------------------------------------------------------------------
# GeoCriteria tests
# ---------------------------------------------------------------------------

class TestGeoCriteria:
    def test_geo_distance_generates_bind(self, builder):
        gc = GeoCriteria(latitude=40.73, longitude=-73.93)
        criteria = EntityQueryCriteria(geo_criteria=gc)
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 10, 0)

        assert "vg:geoDistance" in sparql
        assert "40.73" in sparql
        assert "-73.93" in sparql
        assert "?vg_distance" in sparql

    def test_geo_radius_generates_filter(self, builder):
        gc = GeoCriteria(latitude=40.73, longitude=-73.93, radius_m=5000.0)
        criteria = EntityQueryCriteria(geo_criteria=gc)
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 10, 0)

        assert "vg:withinRadius" in sparql
        assert "5000.0" in sparql

    def test_geo_no_radius_no_filter(self, builder):
        gc = GeoCriteria(latitude=40.73, longitude=-73.93)
        criteria = EntityQueryCriteria(geo_criteria=gc)
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 10, 0)

        assert "vg:withinRadius" not in sparql

    def test_geo_sort_by_distance(self, builder):
        gc = GeoCriteria(latitude=40.73, longitude=-73.93, sort_by_distance=True)
        criteria = EntityQueryCriteria(geo_criteria=gc)
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 10, 0)

        assert "ORDER BY ASC(?vg_distance)" in sparql

    def test_geo_top_k_overrides_limit(self, builder):
        gc = GeoCriteria(latitude=40.73, longitude=-73.93, top_k=15)
        criteria = EntityQueryCriteria(geo_criteria=gc)
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 100, 50)

        assert "LIMIT 15" in sparql
        assert "OFFSET 0" in sparql

    def test_geo_custom_distance_variable(self, builder):
        gc = GeoCriteria(latitude=40.73, longitude=-73.93, distance_variable="dist")
        criteria = EntityQueryCriteria(geo_criteria=gc)
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 10, 0)

        assert "?dist" in sparql


# ---------------------------------------------------------------------------
# Combined vector + geo tests
# ---------------------------------------------------------------------------

class TestCombinedVectorGeo:
    def test_combined_generates_both_binds(self, builder):
        vc = VectorCriteria(search_text="nearby coffee", top_k=10)
        gc = GeoCriteria(latitude=40.73, longitude=-73.93, radius_m=1000.0)
        criteria = EntityQueryCriteria(vector_criteria=vc, geo_criteria=gc)
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 10, 0)

        assert "vg:vectorSimilarity" in sparql
        assert "vg:geoDistance" in sparql
        assert "vg:withinRadius" in sparql

    def test_combined_vector_takes_order_priority(self, builder):
        vc = VectorCriteria(search_text="test", top_k=10)
        gc = GeoCriteria(latitude=40.73, longitude=-73.93, sort_by_distance=True)
        criteria = EntityQueryCriteria(vector_criteria=vc, geo_criteria=gc)
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 10, 0)

        # Vector ORDER BY takes priority
        assert "ORDER BY DESC(?vg_score)" in sparql
        assert "ORDER BY ASC(?vg_distance)" not in sparql

    def test_combined_vector_limit_takes_priority(self, builder):
        vc = VectorCriteria(search_text="test", top_k=5)
        gc = GeoCriteria(latitude=40.73, longitude=-73.93, top_k=20)
        criteria = EntityQueryCriteria(vector_criteria=vc, geo_criteria=gc)
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 100, 0)

        assert "LIMIT 5" in sparql


# ---------------------------------------------------------------------------
# MultiVectorCriteria tests
# ---------------------------------------------------------------------------

class TestMultiVectorCriteria:
    """Tests for multi-vector weighted fusion SPARQL generation."""

    def _two_nearby_inputs(self):
        return [
            MultiVectorCriteriaInput(vector="[0.1,0.2,0.3]", index_name="idx_a", weight=0.6),
            MultiVectorCriteriaInput(vector="[0.4,0.5,0.6]", index_name="idx_b", weight=0.4),
        ]

    def _two_text_inputs(self):
        return [
            MultiVectorCriteriaInput(search_text="machine learning", index_name="idx_a", weight=0.7),
            MultiVectorCriteriaInput(search_text="data science", index_name="idx_b", weight=0.3),
        ]

    def test_nearby_generates_multi_vector_bind(self, builder):
        mvc = MultiVectorCriteria(vectors=self._two_nearby_inputs(), top_k=10)
        criteria = EntityQueryCriteria(multi_vector_criteria=mvc)
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 20, 0)

        assert "vg:multiVectorNearby" in sparql
        assert "[0.1,0.2,0.3]" in sparql
        assert "idx_a" in sparql
        assert "idx_b" in sparql

    def test_text_generates_multi_vector_similarity(self, builder):
        mvc = MultiVectorCriteria(vectors=self._two_text_inputs(), top_k=10)
        criteria = EntityQueryCriteria(multi_vector_criteria=mvc)
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 20, 0)

        assert "vg:multiVectorSimilarity" in sparql
        assert "machine learning" in sparql
        assert "data science" in sparql

    def test_mixed_inputs_use_similarity(self, builder):
        """When any input uses search_text (no pre-computed vector), use Similarity."""
        inputs = [
            MultiVectorCriteriaInput(vector="[0.1,0.2]", index_name="idx_a", weight=0.5),
            MultiVectorCriteriaInput(search_text="test", index_name="idx_b", weight=0.5),
        ]
        mvc = MultiVectorCriteria(vectors=inputs, top_k=10)
        criteria = EntityQueryCriteria(multi_vector_criteria=mvc)
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 20, 0)

        assert "vg:multiVectorSimilarity" in sparql
        assert "vg:multiVectorNearby" not in sparql

    def test_bound_filter_always_present(self, builder):
        """INTERSECT semantics: FILTER(BOUND(?score)) always emitted."""
        mvc = MultiVectorCriteria(vectors=self._two_nearby_inputs(), top_k=10)
        criteria = EntityQueryCriteria(multi_vector_criteria=mvc)
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 20, 0)

        assert "FILTER(BOUND(?vg_score))" in sparql

    def test_min_score_filter(self, builder):
        mvc = MultiVectorCriteria(vectors=self._two_nearby_inputs(), top_k=10, min_score=0.8)
        criteria = EntityQueryCriteria(multi_vector_criteria=mvc)
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 20, 0)

        assert "FILTER(BOUND(?vg_score))" in sparql
        assert "FILTER(?vg_score > 0.8)" in sparql

    def test_order_by_desc_score(self, builder):
        mvc = MultiVectorCriteria(vectors=self._two_nearby_inputs(), top_k=10)
        criteria = EntityQueryCriteria(multi_vector_criteria=mvc)
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 20, 0)

        assert "ORDER BY DESC(?vg_score)" in sparql

    def test_top_k_overrides_limit(self, builder):
        mvc = MultiVectorCriteria(vectors=self._two_nearby_inputs(), top_k=7)
        criteria = EntityQueryCriteria(multi_vector_criteria=mvc)
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 100, 50)

        assert "LIMIT 7" in sparql
        assert "OFFSET 0" in sparql

    def test_custom_score_variable(self, builder):
        mvc = MultiVectorCriteria(
            vectors=self._two_nearby_inputs(), top_k=5, score_variable="fusion_score"
        )
        criteria = EntityQueryCriteria(multi_vector_criteria=mvc)
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 10, 0)

        assert "?fusion_score" in sparql
        assert "ORDER BY DESC(?fusion_score)" in sparql
        assert "FILTER(BOUND(?fusion_score))" in sparql

    def test_weights_included_in_bind(self, builder):
        mvc = MultiVectorCriteria(vectors=self._two_nearby_inputs(), top_k=10)
        criteria = EntityQueryCriteria(multi_vector_criteria=mvc)
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 20, 0)

        assert "0.6" in sparql
        assert "0.4" in sparql

    def test_takes_precedence_over_single_vector(self, builder):
        """When both vector_criteria and multi_vector_criteria are set, multi wins."""
        vc = VectorCriteria(search_text="single", top_k=5)
        mvc = MultiVectorCriteria(vectors=self._two_nearby_inputs(), top_k=10)
        criteria = EntityQueryCriteria(vector_criteria=vc, multi_vector_criteria=mvc)
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 20, 0)

        assert "multiVectorNearby" in sparql
        assert "vectorSimilarity" not in sparql

    def test_escapes_quotes_in_search_text(self, builder):
        inputs = [
            MultiVectorCriteriaInput(search_text='say "hello"', index_name="idx_a", weight=0.5),
            MultiVectorCriteriaInput(search_text="plain", index_name="idx_b", weight=0.5),
        ]
        mvc = MultiVectorCriteria(vectors=inputs, top_k=10)
        criteria = EntityQueryCriteria(multi_vector_criteria=mvc)
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 20, 0)

        assert '\\"hello\\"' in sparql

    def test_three_vector_inputs(self, builder):
        inputs = [
            MultiVectorCriteriaInput(vector="[0.1]", index_name="a", weight=0.5),
            MultiVectorCriteriaInput(vector="[0.2]", index_name="b", weight=0.3),
            MultiVectorCriteriaInput(vector="[0.3]", index_name="c", weight=0.2),
        ]
        mvc = MultiVectorCriteria(vectors=inputs, top_k=5)
        criteria = EntityQueryCriteria(multi_vector_criteria=mvc)
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 10, 0)

        assert "vg:multiVectorNearby" in sparql
        # All three indexes present
        assert '"a"' in sparql
        assert '"b"' in sparql
        assert '"c"' in sparql


# ---------------------------------------------------------------------------
# MultiVector + Geo combined tests
# ---------------------------------------------------------------------------

class TestMultiVectorWithGeo:
    def test_multi_vector_plus_geo(self, builder):
        mvc = MultiVectorCriteria(
            vectors=[
                MultiVectorCriteriaInput(vector="[0.1]", index_name="a", weight=0.5),
                MultiVectorCriteriaInput(vector="[0.2]", index_name="b", weight=0.5),
            ],
            top_k=10,
        )
        gc = GeoCriteria(latitude=40.73, longitude=-73.93, radius_m=5000.0)
        criteria = EntityQueryCriteria(multi_vector_criteria=mvc, geo_criteria=gc)
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 20, 0)

        assert "multiVectorNearby" in sparql
        assert "vg:geoDistance" in sparql
        assert "vg:withinRadius" in sparql

    def test_multi_vector_order_beats_geo(self, builder):
        mvc = MultiVectorCriteria(
            vectors=[
                MultiVectorCriteriaInput(vector="[0.1]", index_name="a", weight=0.5),
                MultiVectorCriteriaInput(vector="[0.2]", index_name="b", weight=0.5),
            ],
            top_k=10,
        )
        gc = GeoCriteria(latitude=40.73, longitude=-73.93, sort_by_distance=True)
        criteria = EntityQueryCriteria(multi_vector_criteria=mvc, geo_criteria=gc)
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 20, 0)

        assert "ORDER BY DESC(?vg_score)" in sparql
        assert "ORDER BY ASC(?vg_distance)" not in sparql


# ---------------------------------------------------------------------------
# Pydantic model → builder conversion (multi-vector path)
# ---------------------------------------------------------------------------

class TestMultiVectorPydanticIntegration:
    """Tests the Pydantic model → builder dataclass conversion for multi-vector."""

    def _convert_and_build(self, pydantic_mvc):
        from vitalgraph.sparql.kg_query_builder import (
            MultiVectorCriteria as BuilderMVC,
            MultiVectorCriteriaInput as BuilderMVI,
        )
        builder_mvc = BuilderMVC(
            vectors=[
                BuilderMVI(
                    search_text=v.search_text,
                    vector=v.vector,
                    index_name=v.index_name,
                    weight=v.weight,
                )
                for v in pydantic_mvc.vectors
            ],
            top_k=pydantic_mvc.top_k,
            min_score=pydantic_mvc.min_score,
        )
        criteria = EntityQueryCriteria(multi_vector_criteria=builder_mvc)
        b = KGQueryCriteriaBuilder()
        return b.build_entity_query_sparql(criteria, "urn:g:test", 100, 0)

    def test_api_multi_vector_nearby(self):
        from vitalgraph.model.kgentities_model import MultiVectorSearchCriteria, WeightedVectorInput
        mvc = MultiVectorSearchCriteria(
            vectors=[
                WeightedVectorInput(vector="[0.1,0.2]", index_name="a", weight=0.6),
                WeightedVectorInput(vector="[0.3,0.4]", index_name="b", weight=0.4),
            ],
            top_k=15,
        )
        sparql = self._convert_and_build(mvc)
        assert "vg:multiVectorNearby" in sparql
        assert "LIMIT 15" in sparql
        assert "FILTER(BOUND(?vg_score))" in sparql

    def test_api_multi_vector_text(self):
        from vitalgraph.model.kgentities_model import MultiVectorSearchCriteria, WeightedVectorInput
        mvc = MultiVectorSearchCriteria(
            vectors=[
                WeightedVectorInput(search_text="renewable energy", index_name="type_idx", weight=0.3),
                WeightedVectorInput(search_text="solar panels", index_name="desc_idx", weight=0.7),
            ],
            top_k=20,
            min_score=0.5,
        )
        sparql = self._convert_and_build(mvc)
        assert "vg:multiVectorSimilarity" in sparql
        assert "renewable energy" in sparql
        assert "solar panels" in sparql
        assert "FILTER(?vg_score > 0.5)" in sparql

    def test_api_validation_requires_min_two_vectors(self):
        from vitalgraph.model.kgentities_model import MultiVectorSearchCriteria, WeightedVectorInput
        with pytest.raises(Exception):
            MultiVectorSearchCriteria(
                vectors=[WeightedVectorInput(vector="[0.1]", index_name="a")],
                top_k=10,
            )

    def test_api_validation_rejects_empty_input(self):
        from vitalgraph.model.kgentities_model import WeightedVectorInput
        with pytest.raises(Exception):
            WeightedVectorInput(index_name="a")  # no text or vector

    def test_api_validation_rejects_both_text_and_vector(self):
        from vitalgraph.model.kgentities_model import WeightedVectorInput
        with pytest.raises(Exception):
            WeightedVectorInput(search_text="x", vector="[0.1]", index_name="a")

    def test_kgquery_criteria_accepts_multi_vector(self):
        from vitalgraph.model.kgentities_model import MultiVectorSearchCriteria, WeightedVectorInput
        from vitalgraph.model.kgqueries_model import KGQueryCriteria, KGQueryRequest
        mvc = MultiVectorSearchCriteria(
            vectors=[
                WeightedVectorInput(vector="[0.1]", index_name="a", weight=0.5),
                WeightedVectorInput(vector="[0.2]", index_name="b", weight=0.5),
            ],
            top_k=10,
        )
        kgc = KGQueryCriteria(query_type="entity", multi_vector_criteria=mvc)
        req = KGQueryRequest(criteria=kgc, page_size=20)
        assert req.criteria.multi_vector_criteria is not None
        assert len(req.criteria.multi_vector_criteria.vectors) == 2


# ---------------------------------------------------------------------------
# Fusion strategy + oversample tests (builder dataclass level)
# ---------------------------------------------------------------------------

class TestMultiVectorFusionConfig:
    """Tests that fusion_strategy and oversample_factor are accepted on the builder dataclass."""

    def test_default_strategy_is_weighted_sum(self):
        mvc = MultiVectorCriteria(
            vectors=[
                MultiVectorCriteriaInput(vector="[0.1]", index_name="a", weight=0.5),
                MultiVectorCriteriaInput(vector="[0.2]", index_name="b", weight=0.5),
            ],
            top_k=10,
        )
        assert mvc.fusion_strategy == "weighted_sum"
        assert mvc.oversample_factor == 5

    def test_relative_score_accepted(self):
        mvc = MultiVectorCriteria(
            vectors=[
                MultiVectorCriteriaInput(vector="[0.1]", index_name="a", weight=0.5),
                MultiVectorCriteriaInput(vector="[0.2]", index_name="b", weight=0.5),
            ],
            top_k=10,
            fusion_strategy="relative_score",
            oversample_factor=10,
        )
        assert mvc.fusion_strategy == "relative_score"
        assert mvc.oversample_factor == 10

    def test_ranked_accepted(self):
        mvc = MultiVectorCriteria(
            vectors=[
                MultiVectorCriteriaInput(vector="[0.1]", index_name="a", weight=0.5),
                MultiVectorCriteriaInput(vector="[0.2]", index_name="b", weight=0.5),
            ],
            top_k=10,
            fusion_strategy="ranked",
        )
        assert mvc.fusion_strategy == "ranked"

    def test_pydantic_model_has_fusion_fields(self):
        from vitalgraph.model.kgentities_model import MultiVectorSearchCriteria, WeightedVectorInput
        mvc = MultiVectorSearchCriteria(
            vectors=[
                WeightedVectorInput(vector="[0.1]", index_name="a", weight=0.5),
                WeightedVectorInput(vector="[0.2]", index_name="b", weight=0.5),
            ],
            top_k=10,
            fusion_strategy="relative_score",
            oversample_factor=8,
        )
        assert mvc.fusion_strategy == "relative_score"
        assert mvc.oversample_factor == 8

    def test_pydantic_defaults(self):
        from vitalgraph.model.kgentities_model import MultiVectorSearchCriteria, WeightedVectorInput
        mvc = MultiVectorSearchCriteria(
            vectors=[
                WeightedVectorInput(vector="[0.1]", index_name="a", weight=0.5),
                WeightedVectorInput(vector="[0.2]", index_name="b", weight=0.5),
            ],
            top_k=10,
        )
        assert mvc.fusion_strategy == "weighted_sum"
        assert mvc.oversample_factor == 5

    def test_strategy_sparql_unchanged(self, builder):
        """Fusion strategy affects SQL generation, not SPARQL — SPARQL should be identical."""
        for strategy in ("weighted_sum", "relative_score", "ranked"):
            mvc = MultiVectorCriteria(
                vectors=[
                    MultiVectorCriteriaInput(vector="[0.1]", index_name="a", weight=0.5),
                    MultiVectorCriteriaInput(vector="[0.2]", index_name="b", weight=0.5),
                ],
                top_k=10,
                fusion_strategy=strategy,
            )
            criteria = EntityQueryCriteria(multi_vector_criteria=mvc)
            sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 20, 0)
            assert "vg:multiVectorNearby" in sparql
            assert "FILTER(BOUND(?vg_score))" in sparql


# ---------------------------------------------------------------------------
# Backward compatibility tests
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    def test_no_vector_geo_produces_standard_query(self, builder):
        criteria = EntityQueryCriteria()
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 10, 0)

        assert "vg:vectorSimilarity" not in sparql
        assert "vg:geoDistance" not in sparql
        assert "ORDER BY ?entity" in sparql
        assert "LIMIT 10" in sparql
        assert "OFFSET 0" in sparql

    def test_entity_type_filter_still_works(self, builder):
        criteria = EntityQueryCriteria(
            entity_type="http://vital.ai/ontology/haley-ai-kg#CustomType"
        )
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 10, 0)

        assert "hasKGEntityType" in sparql
        assert "CustomType" in sparql

    def test_named_graph_wraps_correctly(self, builder):
        vc = VectorCriteria(search_text="test", top_k=5)
        criteria = EntityQueryCriteria(vector_criteria=vc)
        sparql = builder.build_entity_query_sparql(criteria, "http://g/1", 10, 0)

        assert "GRAPH <http://g/1>" in sparql

    def test_default_graph_no_graph_wrapper(self, builder):
        vc = VectorCriteria(search_text="test", top_k=5)
        criteria = EntityQueryCriteria(vector_criteria=vc)
        sparql = builder.build_entity_query_sparql(criteria, None, 10, 0)

        assert "GRAPH" not in sparql


# ---------------------------------------------------------------------------
# End-to-end: Pydantic model → endpoint conversion → builder SPARQL
# ---------------------------------------------------------------------------

class TestEndToEndApiToSparql:
    """Tests the full pipeline: API Pydantic models → endpoint conversion → SPARQL."""

    def _convert_and_build(self, pydantic_vc=None, pydantic_gc=None, entity_type=None):
        """Simulate endpoint conversion logic and build SPARQL."""
        from vitalgraph.sparql.kg_query_builder import (
            VectorCriteria as BuilderVC,
            GeoCriteria as BuilderGC,
        )

        builder_vc = None
        builder_gc = None
        if pydantic_vc:
            builder_vc = BuilderVC(
                search_text=pydantic_vc.search_text,
                vector=pydantic_vc.vector,
                index_name=pydantic_vc.index_name,
                top_k=pydantic_vc.top_k,
                min_score=pydantic_vc.min_score,
            )
        if pydantic_gc:
            builder_gc = BuilderGC(
                latitude=pydantic_gc.latitude,
                longitude=pydantic_gc.longitude,
                radius_m=pydantic_gc.radius_m,
                sort_by_distance=pydantic_gc.sort_by_distance,
                top_k=pydantic_gc.top_k,
            )

        criteria = EntityQueryCriteria(
            vector_criteria=builder_vc,
            geo_criteria=builder_gc,
        )
        builder = KGQueryCriteriaBuilder()
        return builder.build_entity_query_sparql(criteria, "urn:graph:test", 100, 0)

    def test_api_vector_search_text(self, builder):
        from vitalgraph.model.kgentities_model import VectorSearchCriteria
        vc = VectorSearchCriteria(search_text="machine learning", top_k=5, min_score=0.7)
        sparql = self._convert_and_build(pydantic_vc=vc)

        assert "vg:vectorSimilarity" in sparql
        assert "machine learning" in sparql
        assert "FILTER(?vg_score > 0.7)" in sparql
        assert "ORDER BY DESC(?vg_score)" in sparql
        assert "LIMIT 5" in sparql

    def test_api_vector_pre_computed(self, builder):
        from vitalgraph.model.kgentities_model import VectorSearchCriteria
        vc = VectorSearchCriteria(vector="[0.1,0.2,0.3]", index_name="custom_idx", top_k=20)
        sparql = self._convert_and_build(pydantic_vc=vc)

        assert "vg:vectorNearby" in sparql
        assert "[0.1,0.2,0.3]" in sparql
        assert "custom_idx" in sparql
        assert "LIMIT 20" in sparql

    def test_api_geo_radius(self, builder):
        from vitalgraph.model.kgentities_model import GeoSearchCriteria
        gc = GeoSearchCriteria(latitude=51.5, longitude=-0.12, radius_m=2000, sort_by_distance=True)
        sparql = self._convert_and_build(pydantic_gc=gc)

        assert "vg:geoDistance" in sparql
        assert "vg:withinRadius" in sparql
        assert "51.5" in sparql
        assert "-0.12" in sparql
        assert "2000" in sparql
        assert "ORDER BY ASC(?vg_distance)" in sparql

    def test_api_combined_vector_geo(self, builder):
        from vitalgraph.model.kgentities_model import VectorSearchCriteria, GeoSearchCriteria
        vc = VectorSearchCriteria(search_text="nearby coffee", top_k=10)
        gc = GeoSearchCriteria(latitude=40.73, longitude=-73.93, radius_m=1000)
        sparql = self._convert_and_build(pydantic_vc=vc, pydantic_gc=gc)

        assert "vg:vectorSimilarity" in sparql
        assert "vg:geoDistance" in sparql
        assert "vg:withinRadius" in sparql
        assert "ORDER BY DESC(?vg_score)" in sparql

    def test_api_validation_rejects_empty_vector(self):
        from vitalgraph.model.kgentities_model import VectorSearchCriteria
        with pytest.raises(Exception):
            VectorSearchCriteria()

    def test_api_validation_rejects_both_text_and_vector(self):
        from vitalgraph.model.kgentities_model import VectorSearchCriteria
        with pytest.raises(Exception):
            VectorSearchCriteria(search_text="x", vector="[0.1]")

    def test_api_kgquery_criteria_accepts_vector_geo(self):
        from vitalgraph.model.kgentities_model import VectorSearchCriteria, GeoSearchCriteria
        from vitalgraph.model.kgqueries_model import KGQueryCriteria, KGQueryRequest
        vc = VectorSearchCriteria(search_text="test", top_k=5)
        gc = GeoSearchCriteria(latitude=0.0, longitude=0.0)
        kgc = KGQueryCriteria(query_type="entity", vector_criteria=vc, geo_criteria=gc)
        req = KGQueryRequest(criteria=kgc, page_size=20)

        assert req.criteria.vector_criteria.search_text == "test"
        assert req.criteria.geo_criteria.latitude == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
