# Agent Vector Sync Never Stores An Embedding

## Status: FIXED 2026-09-04. Pre-existing, unrelated to the rdf_stats recompute
## work (`agent_registry/` is untouched by it). Found running `tests/api`
## against the vg-test stack for the first time.

## The fix

`agent_registry_vector_populator.py` now casts and builds the literal, matching
the writers that always worked:

    VALUES ($1, $2, $3::vector, $4, CURRENT_TIMESTAMP)
    ...
    (str(rec[0]), rec[1], _vector_literal(embeddings[idx]), rec[2])

`_vector_literal` is a named module function rather than an inline join, because
this bug was two writers disagreeing about whether the driver would convert a
list. One greppable definition makes the next disagreement visible.

Tests: `tests/unit/test_agent_vector_binding.py` checks BOTH halves — the cast
and the literal — because either alone is still broken, and asserts the raw-list
binding has not returned.

## What happens

Every agent write logs:

    WARNING - Vector sync failed for agent agt_s9w1dk49wq: invalid input for
    query argument $3 in element #0 of executemany() sequence:
    [-0.29203009605407715, -0.18812125921249... (expected str, got list)

Sixteen of them in one API test run. `_sync_vectors` catches the exception and
warns, so nothing fails visibly — but NO agent embedding is ever written, and
agent semantic search has nothing to search.

## Why

`agent_registry_vector_populator.py:173` binds the embedding as a raw Python
list, into a column with no cast:

    INSERT INTO {AGENT_VECTOR_TABLE} (subject_uuid, agent_id, {emb}, search_text, ...)
    VALUES ($1, $2, $3, $4, CURRENT_TIMESTAMP)
    ...
    (str(rec[0]), rec[1], embeddings[idx], rec[2])

pgvector's text input is a STRING (`'[0.1,0.2,...]'`), and asyncpg will not
convert a list for an unknown parameter type. Every other vector writer in the
repo does it correctly -- `vector_populator.py:447` and `:360`, both:

    vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
    ... VALUES ($1, $2, $3::vector, CURRENT_TIMESTAMP)

So the agent path is missing BOTH halves: the `::vector` cast and the string
conversion. The FTS `executemany` immediately below it is fine -- it binds only
text -- which is why FTS agent search works and vector agent search does not.

## Impact

Silent. `_sync_vectors` wraps the call and logs at WARNING:

    async def _sync_vectors(self, agent_id: str):
        if self._vector_populator:
            try:
                await self._vector_populator.sync_agent(agent_id)
            except Exception as e:
                logger.warning("Vector sync failed for agent %s: %s", ...)

The write that triggered it succeeds, the API returns success, and the vector
table stays empty. A similarity query then returns nothing or falls back, and
"no results" is indistinguishable from "no matching agents".

Same shape as the boot-time `S3FileManager` failure
(`planning/planning_features/s3_file_manager_reconnect_plan.md`) and the
maintenance swallows of `issues/144` / `issues/148`: a degraded subsystem that
reports healthy, with the only evidence at a level nobody reads.

## Fix

Build the vector literal and cast it, matching the other writers:

    VALUES ($1, $2, $3::vector, $4, CURRENT_TIMESTAMP)
    ...
    (str(rec[0]), rec[1], "[" + ",".join(str(v) for v in embeddings[idx]) + "]", rec[2])

## Testing

Nothing covers this today. A test asserting the vector table is NON-EMPTY after
an agent write would have caught it; the existing tests assert the API response,
which is success either way. Worth pairing with a check that
`_sync_vectors` failures are not merely warned -- if agent vector search is a
supported feature, a sync that never works should be louder than a WARNING.
