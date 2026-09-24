"""Vector auto-sync embeds what the mapping says, not every literal property.

`issues/219`. `_sync_vectors_for_subjects` called
`build_search_text(props, None)`, which means "every literal property", and
checked nothing about whether the subject was in the index's SCOPE. So every
changed subject was embedded into EVERY vector index in the space.

`issues/217` fixed exactly this for FTS. The vector half stayed open, and it is
the worse of the two: an embedding is opaque, so a wrong one reads as a mediocre
model rather than a defect, and repairing it costs a provider call per row.

WHAT IT COST. Copying nurture actions into an archive whose only vector index is
for DOCUMENT SEGMENTS wrote 291,089 embeddings for subjects that index was never
meant to hold — paid for at the provider, and the write volume then drove an
autovacuum storm that took production query latency from 0.22s to over 50s
(`issues/230`).

These tests pin the two properties separately, because the defect was two
defects: WHAT is embedded (the mapping's properties, not all of them) and WHICH
subjects are embedded at all (those the index's mapping covers).
"""

import inspect

import pytest

import vitalgraph.vectorization.auto_sync as auto_sync


def _vector_sync_source() -> str:
    return inspect.getsource(auto_sync._sync_vectors_for_subjects)


def _code_lines(src: str):
    """Source with comments stripped — the defect's own text appears in the
    comments that explain it, so a naive substring search matches the fix's
    documentation and reports the bug as still present."""
    return "\n".join(line.split("#")[0] for line in src.splitlines())


def test_the_search_text_is_built_from_the_resolved_rule():
    code = _code_lines(_vector_sync_source())
    assert "build_search_text(props, rule)" in code


def test_no_unscoped_build_remains():
    """`build_search_text(props, None)` is the defect itself."""
    code = _code_lines(_vector_sync_source())
    assert "build_search_text(props, None)" not in code, (
        "passing None means 'every literal property' — the whole of issues/219")


def test_the_mapping_is_resolved_per_index():
    code = _code_lines(_vector_sync_source())
    assert "resolve_search_mapping(" in code, (
        "a subject must be checked against THIS index's mapping; without it "
        "every changed subject lands in every index in the space")


def test_subject_scopes_are_fetched():
    code = _code_lines(_vector_sync_source())
    assert "_subject_scopes(" in code, (
        "resolving a mapping needs to know what each subject IS")


def test_an_out_of_scope_subject_is_removed_not_embedded():
    """No mapping means SKIP — and clean up what the unscoped version wrote,
    so the fix repairs its own damage rather than only halting it."""
    code = _code_lines(_vector_sync_source())
    i_rule = code.index("rule = await resolve_search_mapping")
    tail = code[i_rule:]
    j = tail.index("to_embed.append")
    between = tail[:j]
    assert "rule is None or not rule.enabled" in between
    assert "to_delete.append(subj_uuid)" in between, (
        "an out-of-scope subject must be deleted from this index, not embedded")


def test_the_uuid_key_lookup_is_string_on_both_sides():
    """asyncpg returns uuid.UUID keys; a type mismatch does not raise, it
    misses, reads as out-of-scope, and deletes the subject's vectors."""
    code = _code_lines(_vector_sync_source())
    assert "scope.get(str(subj_uuid)" in code


@pytest.mark.parametrize("name", ["_sync_fts_for_subjects", "_sync_vectors_for_subjects"])
def test_both_sync_paths_resolve_a_mapping(name):
    """The two halves must not drift apart again — that drift IS issues/219."""
    code = _code_lines(inspect.getsource(getattr(auto_sync, name)))
    assert "resolve_search_mapping(" in code
