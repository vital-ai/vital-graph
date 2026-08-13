# `vitalgraph1__{space}__*` — a dead schema generation

Everything here addresses tables named

    vitalgraph1__{space}__term_unlogged
    vitalgraph1__{space}__rdf_quad_unlogged
    vitalgraph1__{space}__quad_cpso        (and the other index-order variants)
    vitalgraph1__{space}__edge_structure_mv

**No table with that naming exists in any database.** The current schema is
`{space}_term`, `{space}_rdf_quad` and so on, so none of this can run — not
after a rename, not after fixing the constants. It is kept as a record of the
experiments, not as tooling.

Archived 2026-08-13, when the `wordnet_exp` space these were built against was
removed.

## What is here

    sql_reference/     21 files — the happy_frame_query 1..17 series, the
                       iterations of the frame-query investigation behind
                       issues/048, plus get_constants, find_unused_terms and
                       debug_frame_query_steps
    test_scripts/      8 files — mirrors of their original paths under
                       test_scripts/ (database, debug_scripts, sparql,
                       sparql_orig, archive)

## Two things worth knowing before reading them

**Six constants were wrong, and are now corrected.** These files looked up
`vital-core#KGEntity`, `hasEntitySlotValue`, `hasSlotType`, `hasDescription`,
`hasSourceEntity` and `hasDestinationEntity` under the `vital-core#` namespace,
where the data has `haley-ai-kg#` and `urn:`. Every one resolved to nothing, so
the queries returned zero rows for that reason as well as the table names. The
corrected forms are in place (commit `f021a0c`); the role each plays was checked
against the data, since `hasSourceEntity`/`hasDestinationEntity` are slot-role
VALUES in object position, not the `hasEdgeSource`/`hasEdgeDestination`
predicates they resemble.

**The matviews are gone too.** `wordnet_exp_edge_mv` and
`wordnet_exp_frame_entity_mv` lived in the `fuseki_sql_graph` database — not a
database this project uses — and were dropped with the space. So
`vitalgraph_sparql_sql_dev/jena_sql_frame_entity_mv.py`, which gates on
`pg_matviews`, now has nothing anywhere to match. See `issues/048`.

## What deliberately stayed behind

`vitalgraph_sparql_sql_dev/sql_reference/happy_frame_query.sparql` is NOT here.
It is SPARQL rather than SQL, carries no schema names, and `issues/048` cites it
by path as the canonical query the `frame_entity` rewrite was built for — which
is still open work.
