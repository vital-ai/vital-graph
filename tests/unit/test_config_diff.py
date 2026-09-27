"""Comparing a config document against a space's config — issue 233 step 2.

The comparison is PURE (`export_space_config` normalises both sides first), so it
is testable without a database and tested thoroughly here. The thin DB wrapper is
covered in `tests/integration/test_config_export.py`.

WHAT THIS IS FOR. The issue puts diff before apply because it is what makes apply
trustworthy, and names the case it would have caught: `source_type` flips from
`default` to `properties` as a SIDE EFFECT of adding a property, so a config
rebuilt by replaying API calls differs from the original in a field nobody
thought about. A diff that reports field-level changes finds that; one that
reports "these mappings both exist" does not.

THE THREE FALSE POSITIVES IT MUST NOT HAVE are each pinned below, because each
would make the tool stop being used: provenance differing (every cross-space diff
dirty — and cross-space is the whole use case), a redacted secret reading as
changed (every committed document dirty), and absent-vs-null reading as changed.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.config_diff import (
    _IDENTITY, _PROVENANCE, diff_documents)
from vitalgraph.db.sparql_sql.config_export import CONFIG_VERSION

pytestmark = [pytest.mark.unit]


def _doc(**sections):
    base = {"version": CONFIG_VERSION, "exported_at": "2026-09-26T00:00:00+00:00",
            "source_space_id": "src", "vector_indexes": [], "fts_indexes": [],
            "mappings": [], "fuzzy_mappings": [], "geo_config": None,
            "segmentation_config": []}
    base.update(sections)
    return base


def _mapping(type_uri="urn:t:A", index_name="content", **over):
    m = {"mapping_type": "kgslot", "type_uri": type_uri,
         "index_name": index_name, "enabled": True, "source_type": "default",
         "separator": ". ", "include_pred_name": False,
         "properties": [], "indexes": []}
    m.update(over)
    return m


class TestIdenticalConfigDoesNotDiffer:

    def test_empty_against_empty(self):
        r = diff_documents(_doc(), _doc())
        assert r["differs"] is False
        assert r["sections"] == {}

    def test_same_config_different_provenance(self):
        """The load-bearing false positive: applying a document to a
        differently-named space is the entire use case, so provenance must not
        count."""
        a = _doc(mappings=[_mapping()])
        b = _doc(mappings=[_mapping()])
        b["source_space_id"] = "a_completely_different_space"
        b["exported_at"] = "2027-01-01T00:00:00+00:00"
        b["absent_tables"] = ["geo_config"]
        assert diff_documents(a, b)["differs"] is False

    def test_provenance_keys_are_never_read(self):
        """Gives `_PROVENANCE` teeth: set every one of them to junk on both
        sides and the verdict must not move."""
        a, b = _doc(), _doc()
        for k in _PROVENANCE:
            if k == "version":
                continue          # version IS read, deliberately — see below
            a[k], b[k] = "junk-a", "junk-b"
        assert diff_documents(a, b)["differs"] is False


class TestItFindsRealDifferences:

    def test_the_source_type_flip(self):
        """The case the issue names. Same mapping by identity, one field apart."""
        want = _doc(mappings=[_mapping(source_type="default")])
        have = _doc(mappings=[_mapping(source_type="properties")])
        r = diff_documents(want, have)
        assert r["differs"] is True
        changed = r["sections"]["mappings"]["changed"]
        assert len(changed) == 1
        assert changed[0]["field"].endswith(".source_type")
        assert changed[0]["document"] == "default"
        assert changed[0]["space"] == "properties"

    def test_a_mapping_only_in_the_document_would_be_added(self):
        r = diff_documents(_doc(mappings=[_mapping(type_uri="urn:t:New")]), _doc())
        sec = r["sections"]["mappings"]
        assert sec["only_in_document"] == ["kgslot/urn:t:New/content"]
        assert sec["only_in_space"] == []

    def test_a_mapping_only_in_the_space_is_extra(self):
        r = diff_documents(_doc(), _doc(mappings=[_mapping(type_uri="urn:t:Old")]))
        sec = r["sections"]["mappings"]
        assert sec["only_in_space"] == ["kgslot/urn:t:Old/content"]
        assert sec["only_in_document"] == []

    def test_a_changed_property_list_is_reported(self):
        want = _doc(mappings=[_mapping(properties=[
            {"property_uri": "urn:p:a", "property_role": "include", "ordinal": 0}])])
        have = _doc(mappings=[_mapping(properties=[
            {"property_uri": "urn:p:b", "property_role": "include", "ordinal": 0}])])
        r = diff_documents(want, have)
        assert r["differs"] is True
        assert r["sections"]["mappings"]["changed"][0]["field"].endswith(
            ".properties")

    def test_a_nested_provider_config_change_names_the_field(self):
        want = _doc(vector_indexes=[{"index_name": "v", "dimensions": 8,
                                     "provider_config": {"endpoint": "https://a"}}])
        have = _doc(vector_indexes=[{"index_name": "v", "dimensions": 8,
                                     "provider_config": {"endpoint": "https://b"}}])
        changed = diff_documents(want, have)["sections"]["vector_indexes"]["changed"]
        assert changed[0]["field"] == "vector_indexes[v].provider_config.endpoint"

    def test_a_dimension_change_is_found(self):
        want = _doc(vector_indexes=[{"index_name": "v", "dimensions": 1536}])
        have = _doc(vector_indexes=[{"index_name": "v", "dimensions": 768}])
        assert diff_documents(want, have)["differs"] is True

    def test_every_section_is_actually_compared(self):
        """A section missing from `_IDENTITY` would silently never be checked —
        the failure mode of a hand-kept list, so derive the assertion from it."""
        for section, identity in _IDENTITY.items():
            item = {f: f"x-{f}" for f in identity}
            r = diff_documents(_doc(**{section: [item]}), _doc())
            assert r["differs"] is True, f"{section} is not compared"
            assert section in r["sections"]


class TestARedactedSecretIsUnknownNotChanged:

    def test_it_does_not_count_as_a_difference(self):
        """Every committed document carries `__REDACTED__`. If that read as a
        change, verify would fail on every document and stop being run."""
        want = _doc(vector_indexes=[{"index_name": "v",
                                     "provider_config": {"api_key": "__REDACTED__"}}])
        have = _doc(vector_indexes=[{"index_name": "v",
                                     "provider_config": {"api_key": "sk-live-1"}}])
        r = diff_documents(want, have)
        assert r["differs"] is False
        assert r["unknown"] == ["vector_indexes[v].provider_config.api_key"]

    def test_it_is_reported_rather_than_silently_equal(self):
        """The other error: treating it as equal hides a rotation. It has to be
        visible as something the document cannot see."""
        want = _doc(vector_indexes=[{"index_name": "v",
                                     "provider_config": {"api_key": "__REDACTED__"}}])
        have = _doc(vector_indexes=[{"index_name": "v",
                                     "provider_config": {"api_key": "sk-live-1"}}])
        assert diff_documents(want, have)["unknown"]

    def test_a_non_secret_beside_a_redacted_one_is_still_compared(self):
        want = _doc(vector_indexes=[{"index_name": "v", "provider_config": {
            "api_key": "__REDACTED__", "endpoint": "https://a"}}])
        have = _doc(vector_indexes=[{"index_name": "v", "provider_config": {
            "api_key": "sk-live-1", "endpoint": "https://b"}}])
        r = diff_documents(want, have)
        assert r["differs"] is True
        assert [c["field"] for c in
                r["sections"]["vector_indexes"]["changed"]] == \
            ["vector_indexes[v].provider_config.endpoint"]


class TestAbsentAndNullReadTheSame:

    def test_a_missing_optional_key_equals_an_explicit_none(self):
        want = _doc(vector_indexes=[{"index_name": "v", "description": None}])
        have = _doc(vector_indexes=[{"index_name": "v"}])
        assert diff_documents(want, have)["differs"] is False

    def test_an_absent_section_equals_an_empty_one(self):
        have = _doc()
        del have["fuzzy_mappings"]
        assert diff_documents(_doc(), have)["differs"] is False


class TestGeoConfigIsASingleton:

    def test_present_on_one_side_only(self):
        r = diff_documents(_doc(geo_config={"enabled": True}), _doc())
        assert r["differs"] is True
        assert r["sections"]["geo_config"]["only_in_document"] == ["geo_config"]

    def test_a_field_change(self):
        r = diff_documents(_doc(geo_config={"enabled": True}),
                           _doc(geo_config={"enabled": False}))
        assert r["sections"]["geo_config"]["changed"][0]["field"] == \
            "geo_config.enabled"

    def test_both_absent_is_not_a_difference(self):
        assert diff_documents(_doc(), _doc())["differs"] is False


class TestVersion:

    def test_a_mismatched_version_is_noted_not_raised(self):
        """A caller comparing an archived document needs to SEE this; an apply
        needs to refuse on it. Raising would deny the first."""
        old = _doc()
        old["version"] = CONFIG_VERSION - 1
        r = diff_documents(old, _doc())
        assert any("version" in n for n in r["notes"])
        assert r["differs"] is False, "a version note is not a config difference"
