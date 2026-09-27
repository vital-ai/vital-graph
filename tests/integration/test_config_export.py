"""Integration tests: exporting a space's search config — issue 233 step 1.

`bulk_export` moves `datatype`, `term` and `rdf_quad` and no config at all, so a
round trip through it silently drops every index mapping. The config IS the
search behaviour: same data, different mappings, different answers, no error.

THE PROPERTY THAT MATTERS MOST is portability — the document has to be
applicable to a DIFFERENTLY-NAMED space, because renaming a space and applying
its old config to the replacement is the entire use case (`issues/232` is the
other half). `test_the_document_does_not_embed_the_space_id_anywhere_else` is
therefore the load-bearing test here: one stray space id in a row value and the
document only works on the space it came from, which is the space that least
needs it.

The other two are diffability (no surrogate keys, no timestamps, stable order —
so a diff shows real differences only) and being safe to commit (a secret in
`provider_config` is redacted, and the redaction is recorded so a later apply can
refuse a placeholder rather than write one).
"""

from __future__ import annotations

import json

import pytest

from vitalgraph.db.sparql_sql.config_export import (
    CONFIG_VERSION, config_to_json, export_space_config)

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

_SURROGATE_KEYS = ("mapping_id", "index_id", "property_id", "config_id", "id")
_TIMESTAMPS = ("created_time", "updated_time")


def _every_dict(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _every_dict(v)
    elif isinstance(node, list):
        for v in node:
            yield from _every_dict(v)


async def _add_mapping(conn, sp, *, type_uri, index_name, props):
    """A search mapping with properties and a junction row, written directly.

    Directly, not through the lifecycle managers, because this is a test of the
    EXPORT — building the fixture through the managers would make a manager bug
    look like an export bug.
    """
    mid = await conn.fetchval(
        f"INSERT INTO {sp}_search_mapping "
        f"(mapping_type, type_uri, index_name, enabled, source_type, separator,"
        f" include_pred_name) VALUES "
        f"('kgslot', $1, $2, true, 'properties', '. ', false) "
        f"RETURNING mapping_id", type_uri, index_name)
    for ordinal, uri in enumerate(props):
        await conn.execute(
            f"INSERT INTO {sp}_search_mapping_property "
            f"(mapping_id, property_uri, property_role, ordinal) "
            f"VALUES ($1, $2, 'include', $3)", mid, uri, ordinal)
    await conn.execute(
        f"INSERT INTO {sp}_search_mapping_index "
        f"(mapping_id, index_type, index_name) VALUES ($1, 'fts', $2)",
        mid, index_name)
    return mid


class TestTheDocumentShape:

    async def test_a_fresh_space_exports_its_bootstrap_config(self, pg_conn, make_space):
        """Creating a space already bootstraps config, so an export is never
        empty — which is also why apply must reconcile rather than insert."""
        sp = await make_space()
        doc = await export_space_config(pg_conn, sp)
        assert doc["version"] == CONFIG_VERSION
        assert doc["source_space_id"] == sp
        assert doc["vector_indexes"], "bootstrap vector index missing"
        for key in ("fts_indexes", "mappings", "fuzzy_mappings",
                    "segmentation_config"):
            assert isinstance(doc[key], list)
        assert "geo_config" in doc          # None is meaningful, absence is not

    async def test_children_are_nested_not_joined_by_id(self, pg_conn, make_space):
        sp = await make_space()
        await _add_mapping(pg_conn, sp, type_uri="urn:t:Slot",
                           index_name="content",
                           props=["urn:p:one", "urn:p:two"])
        doc = await export_space_config(pg_conn, sp)
        mine = [m for m in doc["mappings"] if m["type_uri"] == "urn:t:Slot"]
        assert len(mine) == 1
        assert [p["property_uri"] for p in mine[0]["properties"]] == \
            ["urn:p:one", "urn:p:two"]
        assert mine[0]["indexes"] == [{"index_type": "fts",
                                       "index_name": "content"}]

    async def test_no_surrogate_key_or_timestamp_survives(self, pg_conn, make_space):
        """They are local SERIALs and source provenance. Carrying them would
        break diffs and hand an apply the remapping problem the nesting removes."""
        sp = await make_space()
        await _add_mapping(pg_conn, sp, type_uri="urn:t:Slot",
                           index_name="content", props=["urn:p:one"])
        doc = await export_space_config(pg_conn, sp)
        for d in _every_dict(doc):
            for bad in _SURROGATE_KEYS + _TIMESTAMPS:
                assert bad not in d, f"{bad} leaked into {sorted(d)}"


class TestPortability:

    async def test_the_document_does_not_embed_the_space_id_anywhere_else(
            self, pg_conn, make_space):
        """THE test. `source_space_id` is provenance; every other occurrence of
        the space id would pin the document to its origin, and the whole point is
        applying it to a different space."""
        sp = await make_space()
        await _add_mapping(pg_conn, sp, type_uri=f"urn:t:{sp}",
                           index_name="content", props=["urn:p:one"])
        doc = await export_space_config(pg_conn, sp)
        assert doc.pop("source_space_id") == sp
        # The type_uri above deliberately CONTAINS the space id, to prove the
        # check is looking at structure rather than just passing by luck.
        leaked = json.dumps(doc).count(sp)
        assert leaked == 1, (
            f"space id appears {leaked} times outside source_space_id; only the "
            f"deliberately-planted type_uri should")


class TestDiffability:

    async def test_two_exports_agree_except_for_the_timestamp(
            self, pg_conn, make_space):
        sp = await make_space()
        await _add_mapping(pg_conn, sp, type_uri="urn:t:Slot",
                           index_name="content", props=["urn:p:b", "urn:p:a"])
        first = await export_space_config(pg_conn, sp)
        second = await export_space_config(pg_conn, sp)
        first.pop("exported_at"), second.pop("exported_at")
        assert config_to_json(first) == config_to_json(second)

    async def test_properties_keep_their_ordinal_order(self, pg_conn, make_space):
        """Ordinal is semantic — it is the order values are concatenated into
        search text — so it must not come back in insertion or hash order."""
        sp = await make_space()
        mid = await _add_mapping(pg_conn, sp, type_uri="urn:t:Slot",
                                 index_name="content", props=["urn:p:zero"])
        for ordinal, uri in ((5, "urn:p:five"), (2, "urn:p:two")):
            await pg_conn.execute(
                f"INSERT INTO {sp}_search_mapping_property "
                f"(mapping_id, property_uri, property_role, ordinal) "
                f"VALUES ($1, $2, 'include', $3)", mid, uri, ordinal)
        doc = await export_space_config(pg_conn, sp)
        mine = [m for m in doc["mappings"] if m["type_uri"] == "urn:t:Slot"][0]
        assert [p["ordinal"] for p in mine["properties"]] == [0, 2, 5]


class TestSecrets:

    async def test_a_provider_config_secret_is_redacted_and_recorded(
            self, pg_conn, make_space):
        sp = await make_space()
        await pg_conn.execute(
            f"INSERT INTO {sp}_vector_index "
            f"(index_name, dimensions, distance_metric, provider, model_name, "
            f" provider_config) VALUES "
            f"('secret_idx', 8, 'cosine', 'openai', 'm', "
            f" '{{\"api_key\": \"sk-live-123\", \"endpoint\": \"https://x\"}}')")

        doc = await export_space_config(pg_conn, sp)
        idx = [v for v in doc["vector_indexes"]
               if v["index_name"] == "secret_idx"][0]
        assert idx["provider_config"]["api_key"] == "__REDACTED__"
        assert idx["provider_config"]["endpoint"] == "https://x", \
            "redaction must be surgical, not wholesale"
        assert "sk-live-123" not in json.dumps(doc)
        assert any("api_key" in p for p in doc["redacted"]), doc.get("redacted")

    async def test_include_secrets_returns_the_real_value(
            self, pg_conn, make_space):
        """An applicable document needs the real config; the caller opts in and
        the result is a credential."""
        sp = await make_space()
        await pg_conn.execute(
            f"INSERT INTO {sp}_vector_index "
            f"(index_name, dimensions, distance_metric, provider, model_name, "
            f" provider_config) VALUES ('secret_idx', 8, 'cosine', 'openai', "
            f" 'm', '{{\"api_key\": \"sk-live-123\"}}')")
        doc = await export_space_config(pg_conn, sp, include_secrets=True)
        idx = [v for v in doc["vector_indexes"]
               if v["index_name"] == "secret_idx"][0]
        assert idx["provider_config"]["api_key"] == "sk-live-123"
        assert "redacted" not in doc


class TestOlderSpaces:

    async def test_a_missing_config_table_is_reported_not_fatal(
            self, pg_conn, make_space):
        """A space from an older schema can legitimately lack a table. Failing
        the export would break the tool exactly on the space that most needs
        reading."""
        sp = await make_space()
        await pg_conn.execute(f"DROP TABLE {sp}_geo_config")
        doc = await export_space_config(pg_conn, sp)
        assert doc["absent_tables"] == ["geo_config"]
        assert doc["geo_config"] is None
        assert doc["vector_indexes"], "the rest of the export must still work"

    async def test_a_clean_space_reports_no_absences(self, pg_conn, make_space):
        sp = await make_space()
        doc = await export_space_config(pg_conn, sp)
        assert "absent_tables" not in doc


class TestDiffAgainstALiveSpace:
    """`issues/233` step 2. The pure comparison is covered thoroughly in
    `tests/unit/test_config_diff.py`; what needs a database is that the two
    halves meet — that an export fed straight back reports NO difference, and
    that a real change to a real space is found."""

    async def test_a_space_does_not_differ_from_its_own_export(
            self, pg_conn, make_space):
        """The baseline. If this fails, every later verify is noise."""
        from vitalgraph.db.sparql_sql.config_diff import diff_space_config
        sp = await make_space()
        await _add_mapping(pg_conn, sp, type_uri="urn:t:Slot",
                           index_name="content", props=["urn:p:one"])
        doc = await export_space_config(pg_conn, sp)
        report = await diff_space_config(pg_conn, sp, doc)
        assert report["differs"] is False, report["sections"]
        assert report["space_id"] == sp

    async def test_a_redacted_export_still_does_not_differ(
            self, pg_conn, make_space):
        """A document safe to commit must verify clean against its own space —
        otherwise the safe form is the useless form."""
        from vitalgraph.db.sparql_sql.config_diff import diff_space_config
        sp = await make_space()
        await pg_conn.execute(
            f"INSERT INTO {sp}_vector_index "
            f"(index_name, dimensions, distance_metric, provider, model_name, "
            f" provider_config) VALUES ('secret_idx', 8, 'cosine', 'openai', "
            f" 'm', '{{\"api_key\": \"sk-live-123\"}}')")
        doc = await export_space_config(pg_conn, sp)          # redacted
        report = await diff_space_config(pg_conn, sp, doc)
        assert report["differs"] is False
        assert any("api_key" in u for u in report["unknown"]), report["unknown"]

    async def test_a_change_made_after_the_export_is_found(
            self, pg_conn, make_space):
        from vitalgraph.db.sparql_sql.config_diff import diff_space_config
        sp = await make_space()
        mid = await _add_mapping(pg_conn, sp, type_uri="urn:t:Slot",
                                 index_name="content", props=["urn:p:one"])
        doc = await export_space_config(pg_conn, sp)
        # The issue's named case, performed for real: flip source_type.
        await pg_conn.execute(
            f"UPDATE {sp}_search_mapping SET source_type = 'default' "
            f"WHERE mapping_id = $1", mid)
        report = await diff_space_config(pg_conn, sp, doc)
        assert report["differs"] is True
        changed = report["sections"]["mappings"]["changed"]
        assert any(c["field"].endswith(".source_type") for c in changed), changed

    async def test_one_space_against_another(self, pg_conn, make_space):
        """The real use case: `232` renames `data` to `data_orig`, a fresh `data`
        is created, and this says whether the replacement matches. Two freshly
        created spaces differ only by what was added, NOT by their names."""
        from vitalgraph.db.sparql_sql.config_diff import diff_space_config
        source = await make_space()
        target = await make_space()
        await _add_mapping(pg_conn, source, type_uri="urn:t:Slot",
                           index_name="content", props=["urn:p:one"])

        doc = await export_space_config(pg_conn, source)
        report = await diff_space_config(pg_conn, target, doc)

        assert report["differs"] is True
        assert report["sections"]["mappings"]["only_in_document"] == \
            ["kgslot/urn:t:Slot/content"]
        # Bootstrap config is identical in both, so nothing else may appear.
        assert report["sections"]["mappings"]["only_in_space"] == []
        assert "vector_indexes" not in report["sections"], \
            "two fresh spaces must agree on their bootstrap config"

    async def test_an_empty_target_reports_the_whole_document_as_additions(
            self, pg_conn, make_space):
        from vitalgraph.db.sparql_sql.config_diff import diff_space_config
        source = await make_space()
        target = await make_space()
        await pg_conn.execute(f"DELETE FROM {target}_search_mapping")
        doc = await export_space_config(pg_conn, source)
        report = await diff_space_config(pg_conn, target, doc)
        assert report["sections"]["mappings"]["only_in_document"], report


class TestApplyToASpace:
    """`issues/233` step 3, merge semantics.

    THE TWO ASSERTIONS THAT MATTER are that apply-then-diff is clean (the
    document was actually reproduced, checked by step 2 rather than by the code
    that wrote it) and that applying twice changes nothing. Everything else is
    detail around those.
    """

    async def test_applying_a_document_makes_the_diff_clean(
            self, pg_conn, make_space):
        """The whole point, and the strongest available check: step 2 grades
        step 3, so a field apply quietly failed to set cannot pass."""
        from vitalgraph.db.sparql_sql.config_apply import apply_space_config
        from vitalgraph.db.sparql_sql.config_diff import diff_space_config

        source = await make_space()
        target = await make_space()
        await _add_mapping(pg_conn, source, type_uri="urn:t:Slot",
                           index_name="content", props=["urn:p:a", "urn:p:b"])
        doc = await export_space_config(pg_conn, source, include_secrets=True)

        assert (await diff_space_config(pg_conn, target, doc))["differs"] is True
        report = await apply_space_config(pg_conn, target, doc)
        assert report["changed"] is True
        assert not report["failed"], report["failed"]

        after = await diff_space_config(pg_conn, target, doc)
        assert after["differs"] is False, after["sections"]

    async def test_the_source_type_trap(self, pg_conn, make_space):
        """`add_property` auto-upgrades `source_type` to 'properties'. A document
        that says 'default' WITH properties is the case that silently diverges,
        and the only one that proves the re-assert ordering works."""
        from vitalgraph.db.sparql_sql.config_apply import apply_space_config

        source = await make_space()
        target = await make_space()
        mid = await _add_mapping(pg_conn, source, type_uri="urn:t:Trap",
                                 index_name="content", props=["urn:p:a"])
        await pg_conn.execute(
            f"UPDATE {source}_search_mapping SET source_type = 'default' "
            f"WHERE mapping_id = $1", mid)
        doc = await export_space_config(pg_conn, source, include_secrets=True)
        assert [m for m in doc["mappings"]
                if m["type_uri"] == "urn:t:Trap"][0]["source_type"] == "default"

        await apply_space_config(pg_conn, target, doc)

        got = await pg_conn.fetchval(
            f"SELECT source_type FROM {target}_search_mapping "
            f"WHERE type_uri = 'urn:t:Trap'")
        assert got == "default", (
            "add_property's side effect won — the scalars are not being "
            "re-asserted after the properties")

    async def test_applying_twice_changes_nothing(self, pg_conn, make_space):
        from vitalgraph.db.sparql_sql.config_apply import apply_space_config

        source = await make_space()
        target = await make_space()
        await _add_mapping(pg_conn, source, type_uri="urn:t:Slot",
                           index_name="content", props=["urn:p:a"])
        doc = await export_space_config(pg_conn, source, include_secrets=True)

        await apply_space_config(pg_conn, target, doc)
        second = await apply_space_config(pg_conn, target, doc)
        assert second["created"] == []
        assert second["updated"] == []
        assert second["changed"] is False

    async def test_merge_never_removes_what_the_document_omits(
            self, pg_conn, make_space):
        """Merge, not replace. Removal is step 4 and needs an answer on dropping
        physical tables; until then a mapping the document does not mention must
        survive, and the DIFF is what reports it as extra."""
        from vitalgraph.db.sparql_sql.config_apply import apply_space_config
        from vitalgraph.db.sparql_sql.config_diff import diff_space_config

        source = await make_space()
        target = await make_space()
        await _add_mapping(pg_conn, target, type_uri="urn:t:OnlyHere",
                           index_name="content", props=["urn:p:x"])
        doc = await export_space_config(pg_conn, source, include_secrets=True)

        await apply_space_config(pg_conn, target, doc)

        survived = await pg_conn.fetchval(
            f"SELECT count(*) FROM {target}_search_mapping "
            f"WHERE type_uri = 'urn:t:OnlyHere'")
        assert survived == 1
        report = await diff_space_config(pg_conn, target, doc)
        assert report["sections"]["mappings"]["only_in_space"] == \
            ["kgslot/urn:t:OnlyHere/content"]

    async def test_a_vector_index_arrives_with_its_physical_table(
            self, pg_conn, make_space):
        """The reason the issue insists on the lifecycle managers: a registry row
        without its `_vec_` table is an index that lists correctly and does not
        work."""
        from vitalgraph.db.sparql_sql.config_apply import apply_space_config

        source = await make_space()
        target = await make_space()
        await pg_conn.execute(
            f"INSERT INTO {source}_vector_index (index_name, dimensions, "
            f"distance_metric, provider, model_name) VALUES "
            f"('extra_idx', 1536, 'cosine', 'openai', 'text-embedding-3-small')")
        doc = await export_space_config(pg_conn, source, include_secrets=True)

        report = await apply_space_config(pg_conn, target, doc)
        assert "vector_index/extra_idx" in report["created"], report

        exists = await pg_conn.fetchval(
            "SELECT count(*) FROM pg_class WHERE relname = $1",
            f"{target}_vec_extra_idx")
        assert exists == 1, "registry row written without its data table"

    async def test_a_redacted_document_is_refused_before_anything_changes(
            self, pg_conn, make_space):
        """Writing `__REDACTED__` into a provider config yields an index that
        exists, looks configured and embeds wrongly — `issues/219`'s shape."""
        from vitalgraph.db.sparql_sql.config_apply import (
            ConfigApplyRefused, apply_space_config)

        source = await make_space()
        target = await make_space()
        await pg_conn.execute(
            f"INSERT INTO {source}_vector_index (index_name, dimensions, "
            f"distance_metric, provider, model_name, provider_config) VALUES "
            f"('secret_idx', 1536, 'cosine', 'openai', "
            f" 'text-embedding-3-small', '{{\"api_key\": \"sk-live-1\"}}')")
        doc = await export_space_config(pg_conn, source)       # redacted

        before = await pg_conn.fetchval(
            f"SELECT count(*) FROM {target}_vector_index")
        with pytest.raises(ConfigApplyRefused) as exc:
            await apply_space_config(pg_conn, target, doc)
        assert "api_key" in str(exc.value)
        assert "include_secrets" in str(exc.value)
        assert await pg_conn.fetchval(
            f"SELECT count(*) FROM {target}_vector_index") == before, \
            "refused, but something was already written"

    async def test_a_wrong_version_is_refused(self, pg_conn, make_space):
        from vitalgraph.db.sparql_sql.config_apply import (
            ConfigApplyRefused, apply_space_config)
        sp = await make_space()
        doc = await export_space_config(pg_conn, sp, include_secrets=True)
        doc["version"] = 999
        with pytest.raises(ConfigApplyRefused):
            await apply_space_config(pg_conn, sp, doc)

    async def test_dry_run_writes_nothing(self, pg_conn, make_space):
        from vitalgraph.db.sparql_sql.config_apply import apply_space_config
        from vitalgraph.db.sparql_sql.config_diff import diff_space_config

        source = await make_space()
        target = await make_space()
        await _add_mapping(pg_conn, source, type_uri="urn:t:Slot",
                           index_name="content", props=["urn:p:a"])
        doc = await export_space_config(pg_conn, source, include_secrets=True)

        report = await apply_space_config(pg_conn, target, doc, dry_run=True)
        assert report["created"], "a dry run must still say what it would do"
        assert (await diff_space_config(pg_conn, target, doc))["differs"] is True


class TestReplaceSemantics:
    """`issues/233` step 4 — decided 2026-09-26: replace DOES drop the physical
    `_vec_`/`_fts_` tables for removed indexes.

    These tests are weighted toward what replace DESTROYS, because that is the
    part that cannot be undone by re-applying: the document recreates an index
    empty, it cannot bring the embeddings back.
    """

    async def test_merge_is_the_default(self, pg_conn, make_space):
        """The safe behaviour must be the one you get by not thinking."""
        from vitalgraph.db.sparql_sql.config_apply import apply_space_config
        source = await make_space()
        target = await make_space()
        await _add_mapping(pg_conn, target, type_uri="urn:t:Extra",
                           index_name="content", props=["urn:p:x"])
        doc = await export_space_config(pg_conn, source, include_secrets=True)

        report = await apply_space_config(pg_conn, target, doc)
        assert report["removed"] == []
        assert await pg_conn.fetchval(
            f"SELECT count(*) FROM {target}_search_mapping "
            f"WHERE type_uri = 'urn:t:Extra'") == 1

    async def test_replace_removes_a_mapping_the_document_omits(
            self, pg_conn, make_space):
        from vitalgraph.db.sparql_sql.config_apply import apply_space_config
        from vitalgraph.db.sparql_sql.config_diff import diff_space_config
        source = await make_space()
        target = await make_space()
        await _add_mapping(pg_conn, target, type_uri="urn:t:Extra",
                           index_name="content", props=["urn:p:x"])
        doc = await export_space_config(pg_conn, source, include_secrets=True)

        report = await apply_space_config(pg_conn, target, doc, replace=True)
        assert any("urn:t:Extra" in r["what"] for r in report["removed"]), report
        assert await pg_conn.fetchval(
            f"SELECT count(*) FROM {target}_search_mapping "
            f"WHERE type_uri = 'urn:t:Extra'") == 0
        # And now the space MATCHES the document, which merge could not achieve.
        assert (await diff_space_config(pg_conn, target, doc))["differs"] is False

    async def test_replace_drops_the_physical_vec_table(self, pg_conn, make_space):
        """The decision, asserted: the registry row AND the data table go."""
        from vitalgraph.db.sparql_sql.config_apply import apply_space_config
        from vitalgraph.vectorization.vector_index_lifecycle import ensure_index
        source = await make_space()
        target = await make_space()
        assert await ensure_index(pg_conn, target, "doomed_idx", {
            "dimensions": 1536, "distance_metric": "cosine",
            "provider": "openai", "model_name": "text-embedding-3-small"})
        assert await pg_conn.fetchval(
            "SELECT count(*) FROM pg_class WHERE relname = $1",
            f"{target}_vec_doomed_idx") == 1

        doc = await export_space_config(pg_conn, source, include_secrets=True)
        report = await apply_space_config(pg_conn, target, doc, replace=True)

        assert any(r["what"] == "vector_index/doomed_idx"
                   for r in report["removed"]), report["removed"]
        assert await pg_conn.fetchval(
            "SELECT count(*) FROM pg_class WHERE relname = $1",
            f"{target}_vec_doomed_idx") == 0, "registry row went, table stayed"
        assert await pg_conn.fetchval(
            f"SELECT count(*) FROM {target}_vector_index "
            f"WHERE index_name = 'doomed_idx'") == 0

    async def test_the_report_names_the_rows_it_destroyed(
            self, pg_conn, make_space):
        """The only warning an operator gets. Embeddings cost money and time, and
        re-applying the document recreates the index EMPTY."""
        from vitalgraph.db.sparql_sql.config_apply import apply_space_config
        from vitalgraph.vectorization.vector_index_lifecycle import ensure_index
        source = await make_space()
        target = await make_space()
        assert await ensure_index(pg_conn, target, "doomed_idx", {
            "dimensions": 1536, "distance_metric": "cosine",
            "provider": "openai", "model_name": "text-embedding-3-small"})
        cols = await pg_conn.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = $1", f"{target}_vec_doomed_idx")
        assert cols, "index table missing, cannot test the count"

        doc = await export_space_config(pg_conn, source, include_secrets=True)
        report = await apply_space_config(pg_conn, target, doc, replace=True)
        entry = [r for r in report["removed"]
                 if r["what"] == "vector_index/doomed_idx"][0]
        assert entry["table"] == f"{target}_vec_doomed_idx"
        assert entry["rows_destroyed"] == 0, entry

    async def test_a_replace_dry_run_destroys_nothing_and_still_reports_counts(
            self, pg_conn, make_space):
        """What makes the dry run a safety tool rather than a formality."""
        from vitalgraph.db.sparql_sql.config_apply import apply_space_config
        from vitalgraph.vectorization.vector_index_lifecycle import ensure_index
        source = await make_space()
        target = await make_space()
        assert await ensure_index(pg_conn, target, "doomed_idx", {
            "dimensions": 1536, "distance_metric": "cosine",
            "provider": "openai", "model_name": "text-embedding-3-small"})
        doc = await export_space_config(pg_conn, source, include_secrets=True)

        report = await apply_space_config(pg_conn, target, doc, replace=True,
                                          dry_run=True)
        entry = [r for r in report["removed"]
                 if r["what"] == "vector_index/doomed_idx"][0]
        assert entry["rows_destroyed"] is not None, "a dry run must price it"
        assert await pg_conn.fetchval(
            "SELECT count(*) FROM pg_class WHERE relname = $1",
            f"{target}_vec_doomed_idx") == 1, "dry run dropped the table"

    async def test_replace_is_idempotent(self, pg_conn, make_space):
        from vitalgraph.db.sparql_sql.config_apply import apply_space_config
        source = await make_space()
        target = await make_space()
        await _add_mapping(pg_conn, target, type_uri="urn:t:Extra",
                           index_name="content", props=["urn:p:x"])
        doc = await export_space_config(pg_conn, source, include_secrets=True)

        await apply_space_config(pg_conn, target, doc, replace=True)
        second = await apply_space_config(pg_conn, target, doc, replace=True)
        assert second["removed"] == []
        assert second["changed"] is False

    async def test_removals_run_before_creations(self, pg_conn, make_space):
        """`teardown_index` deletes every mapping naming the index it drops, so
        removing after creating would delete what this apply had just made.

        The scenario: the target has an index the document omits, AND the document
        has a mapping naming an index of its own. Get the order wrong and the new
        mapping is collateral damage.
        """
        from vitalgraph.db.sparql_sql.config_apply import apply_space_config
        from vitalgraph.db.sparql_sql.config_diff import diff_space_config
        from vitalgraph.vectorization.vector_index_lifecycle import ensure_index
        source = await make_space()
        target = await make_space()
        await _add_mapping(pg_conn, source, type_uri="urn:t:Wanted",
                           index_name="content", props=["urn:p:a"])
        assert await ensure_index(pg_conn, target, "doomed_idx", {
            "dimensions": 1536, "distance_metric": "cosine",
            "provider": "openai", "model_name": "text-embedding-3-small"})

        doc = await export_space_config(pg_conn, source, include_secrets=True)
        await apply_space_config(pg_conn, target, doc, replace=True)

        assert await pg_conn.fetchval(
            f"SELECT count(*) FROM {target}_search_mapping "
            f"WHERE type_uri = 'urn:t:Wanted'") == 1, \
            "the mapping this apply created was deleted by a later teardown"
        assert (await diff_space_config(pg_conn, target, doc))["differs"] is False


class TestBulkExportCarriesTheConfig:
    """`issues/233` step 5 — a `bulk_export` round trip must stop dropping config.

    This is the defect the issue opened with: `bulk_export` moved `datatype`,
    `term` and `rdf_quad` and no config at all, so a restored space held the right
    quads and answered searches differently, with no error anywhere.
    """

    async def test_a_round_trip_preserves_the_config(
            self, pg_conn, make_space, tmp_path):
        from vitalgraph.db.sparql_sql.bulk_export import export_space, import_space
        from vitalgraph.db.sparql_sql.config_diff import diff_space_config

        source = await make_space()
        target = await make_space()
        await _add_mapping(pg_conn, source, type_uri="urn:t:Carried",
                           index_name="content", props=["urn:p:a", "urn:p:b"])

        paths = await export_space(pg_conn, source, str(tmp_path))
        assert "config" in paths

        counts = await import_space(pg_conn, target, paths)
        assert counts.get("config"), "import reported no config work at all"

        # Graded by step 2, against the SOURCE's document — so a field the
        # restore failed to set cannot pass.
        doc = await export_space_config(pg_conn, source, include_secrets=True)
        report = await diff_space_config(pg_conn, target, doc)
        assert report["differs"] is False, report["sections"]

    async def test_an_export_without_a_config_sidecar_still_imports(
            self, pg_conn, make_space, tmp_path):
        """Every backup taken before step 5 is in this state. A restore from one
        must work and leave the config alone, not fail."""
        from vitalgraph.db.sparql_sql.bulk_export import export_space, import_space

        source = await make_space()
        target = await make_space()
        paths = await export_space(pg_conn, source, str(tmp_path))
        paths.pop("config")                       # an older export

        counts = await import_space(pg_conn, target, paths)
        assert counts["rdf_quad"] is not None
        assert "config" not in counts, "claimed config work with no sidecar"

    async def test_a_restore_does_not_leave_stale_config_behind(
            self, pg_conn, make_space, tmp_path):
        """REPLACE on import, matching the TRUNCATE it already does to the data.

        A mapping from whatever the space used to be, pointing at an index the
        restore did not bring, is the "faithfully wrong" state `issues/041` and
        `issues/168` are both about.
        """
        from vitalgraph.db.sparql_sql.bulk_export import export_space, import_space

        source = await make_space()
        target = await make_space()
        await _add_mapping(pg_conn, target, type_uri="urn:t:Stale",
                           index_name="content", props=["urn:p:x"])

        paths = await export_space(pg_conn, source, str(tmp_path))
        await import_space(pg_conn, target, paths)

        assert await pg_conn.fetchval(
            f"SELECT count(*) FROM {target}_search_mapping "
            f"WHERE type_uri = 'urn:t:Stale'") == 0, \
            "config from the previous contents survived the restore"

    async def test_a_config_failure_does_not_discard_the_data_restore(
            self, pg_conn, make_space, tmp_path):
        """Aborting a multi-hour restore over a config document that can be
        re-applied in a second would be the wrong trade. The failure is recorded
        and logged instead."""
        import json
        from vitalgraph.db.sparql_sql.bulk_export import export_space, import_space

        source = await make_space()
        target = await make_space()
        paths = await export_space(pg_conn, source, str(tmp_path))

        # A document apply must refuse: a version it does not understand.
        with open(paths["config"], encoding="utf-8") as fh:
            doc = json.load(fh)
        doc["version"] = 999
        with open(paths["config"], "w", encoding="utf-8") as fh:
            json.dump(doc, fh)

        counts = await import_space(pg_conn, target, paths)
        assert "error" in counts["config"], counts["config"]
        assert counts["rdf_quad"] is not None, "the data restore was discarded"
