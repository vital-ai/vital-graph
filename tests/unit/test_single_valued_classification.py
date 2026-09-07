"""Which predicates the integrity probe polices. `issues/175`.

The probe reports a duplicate as a DEFECT, so classifying a legitimately
multi-valued property as single-valued would report correct data as damage — and
on the production space that is 96 subjects of `MultiChoiceSlot`, every one of
them right.
"""
from vitalgraph.process.maintenance_job import _cardinality_is_single

H = "http://vital.ai/ontology/haley-ai-kg#"
V = "http://vital.ai/ontology/vital"


class TestCardinalityComesFromTheOntology:
    def test_single_valued_properties_are_policed(self):
        for n in ("hasTextSlotValue", "hasDateTimeSlotValue", "hasIntegerSlotValue",
                  "hasKGSlotType", "hasKGEntityType"):
            assert _cardinality_is_single(H + n), n

    def test_a_multi_valued_property_is_left_alone(self):
        # 96 subjects hold several of these on production and all are correct.
        assert not _cardinality_is_single(H + "hasMultiChoiceSlotValues")

    def test_server_stamped_timestamps_are_policed(self):
        assert _cardinality_is_single(f"{V}-aimp#hasObjectCreationTime")
        assert _cardinality_is_single(f"{V}#hasObjectModificationDateTime")


class TestUnknownIsNotTreatedAsSingle:
    def test_rdf_type_is_left_alone(self):
        # A resource may legitimately carry several rdf:type values. The ontology
        # has no trait class for it, and "no opinion" must not become "single".
        assert not _cardinality_is_single(
            "http://www.w3.org/1999/02/22-rdf-syntax-ns#type")

    def test_an_unknown_predicate_is_left_alone(self):
        # Arbitrary RDF loaded into a space is not governed by the KG layer.
        assert not _cardinality_is_single("http://example.org/whatever#someProp")


class TestStructuralPredicate:
    def test_vitaltype_is_single_by_construction(self):
        # No VitalSigns trait class exists for it, so it cannot be derived — one
        # type URI per object is a property of the model, named explicitly.
        assert _cardinality_is_single("http://vital.ai/ontology/vital-core#vitaltype")
