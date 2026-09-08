"""The frame sort registry must name predicates the data actually carries.

`hasKGFrameTypeURI` was in `_FILTERABLE_FRAME_PROPERTIES` and nothing carries
it: measured on `wordnet_frames`, all 285,348 frames have `hasKGFrameType` and
zero have `hasKGFrameTypeURI`. The effect was not an error — it was a sort
option that validated, ran, and returned an unordered page, because the
property it ordered by did not exist.

That is the failure mode worth a test: a registry entry costs nothing to add
and produces a silently empty result rather than a complaint.
"""

from __future__ import annotations

HALEY = "http://vital.ai/ontology/haley-ai-kg#"


def test_the_removed_predicate_stays_removed():
    from vitalgraph.model.kgframes_model import _FILTERABLE_FRAME_PROPERTIES
    from vitalgraph.db.sparql_sql.sync_frame_prop_sort import SORTABLE_PROPERTY_URIS
    from vitalgraph.db.sparql_sql.fast_frame_prop_sort import _DATATYPES

    ghost = f"{HALEY}hasKGFrameTypeURI"
    for name, coll in (("model registry", _FILTERABLE_FRAME_PROPERTIES),
                       ("sync property list", SORTABLE_PROPERTY_URIS),
                       ("read-path datatypes", _DATATYPES)):
        assert ghost not in coll, (
            f"{ghost} is back in the {name}. Nothing in the corpus carries it, "
            f"so sorting by it returns an unordered page rather than an error. "
            f"The frame's type is `hasKGFrameType`, a haley-ai-kg#KGFrameType.")


def test_the_real_type_predicates_are_registered():
    from vitalgraph.model.kgframes_model import _FILTERABLE_FRAME_PROPERTIES
    from vitalgraph.db.sparql_sql.sync_frame_prop_sort import SORTABLE_PROPERTY_URIS

    for uri in (f"{HALEY}hasKGFrameType", f"{HALEY}hasKGFrameTypeDescription"):
        assert uri in _FILTERABLE_FRAME_PROPERTIES, f"{uri} missing from the model"
        assert uri in SORTABLE_PROPERTY_URIS, f"{uri} missing from the sync"


def test_the_three_declarations_agree():
    """Duplicated across layers because the db layer does not depend upwards."""
    from vitalgraph.model.kgframes_model import _FRAME_SORT_PROPERTIES
    from vitalgraph.db.sparql_sql.sync_frame_prop_sort import SORTABLE_PROPERTY_URIS
    from vitalgraph.db.sparql_sql.fast_frame_prop_sort import _DATATYPES

    assert set(SORTABLE_PROPERTY_URIS) == set(_FRAME_SORT_PROPERTIES), (
        "the sync indexes a different property set than the listing offers.\n"
        f"  only in the model: {set(_FRAME_SORT_PROPERTIES) - set(SORTABLE_PROPERTY_URIS)}\n"
        f"  only in the sync:  {set(SORTABLE_PROPERTY_URIS) - set(_FRAME_SORT_PROPERTIES)}")
    assert set(_DATATYPES) == set(SORTABLE_PROPERTY_URIS), (
        "the read path knows a different property set than the sync writes.\n"
        f"  difference: {set(_DATATYPES) ^ set(SORTABLE_PROPERTY_URIS)}")
