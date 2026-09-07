"""Generated identifiers must fit PostgreSQL's 63-byte limit. `issues/174`.

PostgreSQL truncates a longer identifier to NAMEDATALEN-1 **silently**. The
object is created under the shortened name, so it enforces correctly while every
lookup by the name it was asked for misses it.

That happened: `{space}_segmentation_jobs_one_active_per_document_idx` is 66
bytes for a 20-character space id, so the index existed under a truncated name
and the schema-completeness check could not find it. It fit production's shorter
ids, which is precisely why only a test space surfaced it — and why a guard that
only lives in a test is not enough.
"""
import logging

import pytest

from vitalgraph.db.sparql_sql.sparql_sql_schema import (
    PG_MAX_IDENTIFIER_BYTES, SparqlSQLSchema, assert_identifiers_fit,
    identifiers_in, max_space_id_bytes,
)


class TestOverflowIsRefused:
    """Truncation is silent, so the check must not be."""

    def test_names_within_the_limit_pass(self):
        assert_identifiers_fit([f"CREATE INDEX {'x' * 60} ON t (c)"])

    def test_unique_truncation_is_refused(self):
        # The object would be created and would work, but every lookup by the
        # name it was asked for misses it — which is how an index went missing
        # from the schema-completeness check. Refused rather than warned, so the
        # next one is not found the same way: by something breaking.
        with pytest.raises(ValueError, match="SILENTLY TRUNCATED"):
            assert_identifiers_fit(
                [f"CREATE INDEX {'x' * (PG_MAX_IDENTIFIER_BYTES + 1)} ON t (c)"], "ctx")

    def test_a_collision_after_truncation_raises(self):
        # Two names sharing their first 63 bytes: one object cannot be created,
        # and which one loses depends on statement order. Not survivable.
        base = "z" * PG_MAX_IDENTIFIER_BYTES
        with pytest.raises(ValueError, match="COLLIDE"):
            assert_identifiers_fit([
                f"CREATE INDEX {base}_one ON t (c)",
                f"CREATE INDEX {base}_two ON t (c)",
            ])

    def test_the_error_names_the_offender_and_the_overshoot(self):
        with pytest.raises(ValueError) as e:
            assert_identifiers_fit([f"CREATE UNIQUE INDEX {'y' * 70} ON t (c)"])
        assert "y" * 70 in str(e.value) and "7 byte(s)" in str(e.value)

    def test_it_counts_bytes_not_characters(self):
        # NAMEDATALEN is a byte budget; a non-ASCII id costs more than it looks.
        name = "é" * 40                      # 40 chars, 80 bytes
        assert len(name) < PG_MAX_IDENTIFIER_BYTES
        with pytest.raises(ValueError):
            assert_identifiers_fit([f"CREATE TABLE {name} (c int)"])

    def test_it_finds_names_in_every_ddl_form_used(self):
        found = identifiers_in([
            "CREATE TABLE IF NOT EXISTS a_tbl (c int)",
            "CREATE INDEX IF NOT EXISTS b_idx ON t (c)",
            "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS c_idx ON t (c)",
        ])
        assert set(found) == {"a_tbl", "b_idx", "c_idx"}


class TestTheSchemaEnforcesItAtGeneration:
    """The guard has to run where names are BUILT, not only in a test — a test
    only fires if someone runs it with a long enough space id."""

    def test_a_realistic_space_id_is_accepted(self):
        sch = SparqlSQLSchema()
        for sid in ("prod_kg", "inttest_000000000000"):
            sch.create_space_indexes_sql(sid)
            sch.create_space_tables_sql(sid)

    def test_an_over_long_space_id_is_refused_before_any_ddl_runs(self):
        sch = SparqlSQLSchema()
        with pytest.raises(ValueError, match="SILENTLY TRUNCATED"):
            sch.create_space_indexes_sql("x" * (max_space_id_bytes() + 1))

    def test_the_boundary_is_exact(self):
        sch = SparqlSQLSchema()
        limit = max_space_id_bytes()
        sch.create_space_indexes_sql("x" * limit)              # must not raise
        with pytest.raises(ValueError):
            sch.create_space_indexes_sql("x" * (limit + 1))

    def test_every_space_id_this_suite_uses_fits(self):
        """The discipline is short space ids, not a schema that stretches.

        Scans the suite's own fixtures rather than asserting a number, so adding
        a long-prefixed space fails here — at the moment it is written — rather
        than as a pile of setup errors when someone next runs the integration
        suite. Ten fixtures were over the limit and had been creating spaces with
        silently truncated index names.
        """
        import pathlib
        import re

        limit = max_space_id_bytes()
        root = pathlib.Path(__file__).resolve().parents[1]
        # Matches an interpolated segment too — `{TEST_SPACE_PREFIX}bl{k}_{hex}`
        # builds its id from a runtime value, which an exact-literal pattern
        # misses. Two fixtures were doing that and were over the limit.
        gen = re.compile(
            r'TEST_SPACE_PREFIX\}([a-z0-9_]*(?:\{[a-z_]+\}[a-z0-9_]*)?)'
            r'\{uuid\.uuid4\(\)\.hex\[:(\d+)\]')
        too_long = []
        for f in root.rglob("*.py"):
            text = f.read_text()
            for m in gen.finditer(text):
                # An interpolated `{k}` is counted generously: assume the
                # longest plausible value rather than zero, or the check passes
                # for exactly the ids it should catch.
                mid = re.sub(r"\{[a-z_]+\}", "x" * 6, m.group(1))
                n = len("inttest_") + len(mid) + int(m.group(2))
                if n > limit:
                    too_long.append((n, f"inttest_{m.group(1)}<hex>", f.name))
            for m in re.finditer(r'space_id\s*=\s*["\'](inttest_[a-z0-9_]+)["\']', text):
                if len(m.group(1)) > limit:
                    too_long.append((len(m.group(1)), m.group(1), f.name))
        assert not too_long, (
            f"space id(s) exceed the {limit} bytes this schema can name objects "
            f"for, so their indexes would be silently truncated: "
            f"{sorted(set(too_long), reverse=True)[:5]}")

    def test_the_limit_is_derived_not_hardcoded(self):
        # It must track the schema's longest suffix, so shortening or lengthening
        # one moves the limit rather than silently invalidating a written-down
        # number.
        limit = max_space_id_bytes()
        assert 0 < limit < PG_MAX_IDENTIFIER_BYTES
        longest = max(len(n) for n in
                      identifiers_in(SparqlSQLSchema().create_space_indexes_sql("x")))
        assert limit == PG_MAX_IDENTIFIER_BYTES - (longest - 1)
