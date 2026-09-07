"""The db layer duplicates two lists the read side owns; assert they agree.

`sync_entity_prop_sort` cannot import `_FILTERABLE_ENTITY_PROPERTIES` or
`_KGENTITY_TYPE_URIS` — they live in `kg_impl`/`model` and the db layer does not
depend upwards. So they are duplicated, and duplication drifts.

It drifts in a direction that is silent. A property added to the model but not to
the sync is a property the listing will happily sort and filter by, served from a
table that holds NO rows for it: not an error, an empty or partial answer that
looks like a real one. These tests are the only thing standing between that and
production.
"""

from __future__ import annotations


def test_sortable_properties_match_the_model():
    from vitalgraph.db.sparql_sql.sync_entity_prop_sort import SORTABLE_PROPERTY_URIS
    from vitalgraph.model.kgentities_model import _FILTERABLE_ENTITY_PROPERTIES

    assert set(SORTABLE_PROPERTY_URIS) == set(_FILTERABLE_ENTITY_PROPERTIES), (
        "entity_prop_sort indexes a different property set than the listing "
        "offers.\n"
        f"  only in the model: {set(_FILTERABLE_ENTITY_PROPERTIES) - set(SORTABLE_PROPERTY_URIS)}\n"
        f"  only in the sync:  {set(SORTABLE_PROPERTY_URIS) - set(_FILTERABLE_ENTITY_PROPERTIES)}\n"
        "A property in the model but not the sync is sorted and filtered from a "
        "table with no rows for it.")


def test_population_matches_the_read_side():
    from vitalgraph.db.sparql_sql.sync_entity_prop_sort import KGENTITY_TYPE_URIS
    from vitalgraph.kg_impl.kg_backend_utils import SparqlSQLBackendAdapter

    assert set(KGENTITY_TYPE_URIS) == set(SparqlSQLBackendAdapter._KGENTITY_TYPE_URIS), (
        "entity_prop_sort covers a different entity population than "
        "`fast_entity_page` lists, so the fast path would serve a page from a "
        "table that does not describe every row of it.")
