"""One malformed subject must not empty a whole page.

`from_property_maps` is all-or-nothing over its batch, and the caller returned
[] on any exception. A single production entity carrying three values for
`hasObjectCreationTime` (repeated quads group into a list, and a list is not a
datetime) made page 9 of the KG entity listing render zero of twenty-five rows,
with no error surfaced — pages 1-8 and 10+ were fine, so it read as "paging
breaks at page 9".
"""
import pytest

from vitalgraph.db.sparql_sql.sparql_sql_db_objects import SparqlSQLDbObjects


def _entry(uri, bad=False):
    return {"subject_uri": uri, "type_uri": "urn:t",
            "properties": {"p": ["a", "b"] if bad else "a"}}


@pytest.fixture
def fake_from_property_maps(monkeypatch):
    """Stand in for VitalSigns: raise if ANY entry in the batch is malformed."""
    import vital_ai_vitalsigns.model.GraphObject as go_mod

    def fake(entries):
        for e in entries:
            if isinstance(e["properties"].get("p"), list):
                raise ValueError(
                    f"Unsupported type in value {e['properties']['p']} "
                    f"for datetime property: list")
        return [e["subject_uri"] for e in entries]

    monkeypatch.setattr(go_mod.GraphObject, "from_property_maps",
                        staticmethod(fake))
    return fake


class TestMaterializeDegradesPerObject:
    def test_clean_batch_passes_straight_through(self, fake_from_property_maps):
        entries = [_entry(f"urn:{i}") for i in range(25)]
        assert SparqlSQLDbObjects._materialize(entries) == [f"urn:{i}" for i in range(25)]

    def test_one_bad_subject_costs_only_itself(self, fake_from_property_maps):
        # THE PRODUCTION CASE: 25 on a page, one malformed. Was 0, must be 24.
        entries = [_entry(f"urn:{i}", bad=(i == 7)) for i in range(25)]
        got = SparqlSQLDbObjects._materialize(entries)
        assert len(got) == 24
        assert "urn:7" not in got
        assert "urn:0" in got and "urn:24" in got

    def test_the_skipped_subject_is_named_at_error(self, fake_from_property_maps, caplog):
        # Returning a short page silently is worse than an empty one: nothing
        # downstream could tell the page was missing a row.
        import logging
        caplog.set_level(logging.ERROR)
        SparqlSQLDbObjects._materialize([_entry("urn:good"), _entry("urn:bad", bad=True)])
        assert "urn:bad" in caplog.text
        assert "urn:good" not in caplog.text

    def test_every_subject_bad_returns_empty_not_an_exception(self, fake_from_property_maps):
        # Degrading must not turn into raising; the caller treats [] as "no rows".
        assert SparqlSQLDbObjects._materialize(
            [_entry("urn:a", bad=True), _entry("urn:b", bad=True)]) == []
