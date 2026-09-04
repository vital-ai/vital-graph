"""An agent embedding must reach the database as a pgvector literal.

`issues/154`. The batch upsert bound the embedding as a raw Python list into a
column with no cast, so asyncpg raised

    invalid input for query argument $3 ... (expected str, got list)

on EVERY agent write. `_sync_vectors` catches and warns, so the write succeeded,
the API returned success, and the vector table stayed empty — agent similarity
search had nothing to search, and "no results" was indistinguishable from "no
matching agents". Sixteen occurrences in one `tests/api` run.

WHY NOTHING CAUGHT IT. The existing tests assert the API response, which is
success in both cases. Nothing asserted the vector table was non-empty
afterwards, and the only evidence was a WARNING.

Both halves are checked here because both were missing and either alone is
still broken: the `::vector` cast in the SQL, and the string literal in the
argument.
"""

from __future__ import annotations

import inspect

from vitalgraph.agent_registry import agent_registry_vector_populator as P


class TestTheVectorLiteral:

    def test_it_is_pgvector_text_form(self):
        assert P._vector_literal([-0.292, -0.188, 0.5]) == "[-0.292,-0.188,0.5]"

    def test_it_is_a_string_not_a_list(self):
        """The whole defect in one assertion: asyncpg will not convert a list
        for a parameter whose type it cannot infer."""
        assert isinstance(P._vector_literal([0.1, 0.2]), str)

    def test_an_empty_embedding_is_still_well_formed(self):
        assert P._vector_literal([]) == "[]"


class TestTheUpsertBindsItCorrectly:
    """Source-level, because exercising it needs a live pool, a provider and an
    embedding model. A cheap check that names the requirement beats no check —
    which is exactly what this file is correcting."""

    def test_the_embedding_column_is_cast_to_vector(self):
        src = inspect.getsource(P)
        assert "$3::vector" in src, (
            "the agent vector upsert no longer casts $3 to ::vector; pgvector "
            "cannot take an untyped parameter and every agent write will warn "
            "and store nothing")

    def test_the_argument_goes_through_the_literal_builder(self):
        src = inspect.getsource(P)
        assert "_vector_literal(embeddings[idx])" in src, (
            "the embedding is bound directly again instead of through "
            "_vector_literal; that is issues/154 verbatim")
        assert "rec[1], embeddings[idx]," not in src, (
            "the raw-list binding is back")
