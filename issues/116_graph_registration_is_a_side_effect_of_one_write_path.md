# Graph Registration Is a Side Effect of One Write Path, So Every Other Path Leaves the Catalog Silent

## Status: OPEN — found 2026-08-21. One instance fixed (`ee086a5`), one open,
## and the general rule not established.

Quads can be in a graph that the `graph` catalog has never heard of. The data
is queryable by naming the URI, so anything that hardcodes the graph works,
while everything that *lists* graphs sees nothing.

## The mechanism

`_ensure_graphs_registered` (`sparql_sql_space_impl.py:768`) inserts the
missing `graph` rows, and its own docstring states the intent:

> Auto-register every graph URI found in *quads* that is not yet in the
> `graph` table. This replicates the side-effect that the fuseki_postgresql
> backend has: inserting data into a graph URI implicitly creates the graph
> record.

So registration is meant to be implicit on write. But it is implicit on
**three specific functions** — `add_rdf_quad`, `add_rdf_quads_batch`,
`add_rdf_quads_batch_bulk` — rather than on the act of landing quads. Any path
that writes quads another way silently skips it, and nothing detects that.

## Instances

**1. `scripts/load_wordnet_csv.py` — FIXED 2026-08-21 (`ee086a5`).** It COPYs
straight into the quad and term tables, so no impl hook fires. Three fixtures
held 31M quads between them with no catalog row:

    sp_graph_synth_100k   19,632,351 quads    urn:sp_graph_synth_100k
    sp_graph_synth_10k     2,455,530 quads    urn:sp_graph_synth_10k
    wordnet_frames         8,911,591 quads    urn:wordnet_frames

`sp_lead_synth_100k`, loaded another way, had its row — which is why this
survived: the fixture most often looked at was the one that was fine. The
loader now registers from the contexts actually present, and
`tests/performance/test_fixture_graphs_are_registered.py` guards the result on
both clusters.

**2. `bulk_export.import_space` — OPEN.** `vitalgraph/db/sparql_sql/bulk_export.py`
does not contain the string `graph` at all. It copies a space's tables into a
destination, so the destination ends up with quads and no catalog row:

    vg-test   inttest_exp_dst_75b278b0   20 quads   urn:export:g
              inttest_exp_dst_e8a03b16   90 quads   urn:export:g
    host      inttest_exp_dst_46ef0897   90 quads
              inttest_exp_dst_ee7049f7   90 quads
              inttest_exp_dst_4c7c68b7   20 quads
              inttest_ba8e42f9241a       20 quads

These come from `tests/integration/test_bulk_export.py`, which writes the
SOURCE through `add_rdf_quads_batch_bulk` (registered) and populates the
DESTINATION through `import_space` (not registered). The same space pair,
loaded two ways, disagrees.

## A correction to how this was first described

It was first reported as "integration tests write into unregistered graphs,
because `make_space` creates the space and tables but no graph row." That is
wrong on both halves.

`make_space` not creating a graph is **correct**. A space may hold many graphs
and holds none until data arrives; inventing one at creation would be the
`spaces are explicitly managed` mistake in a new place.

And most unregistered spaces are simply **empty**, where having no graph is the
right answer:

    vg-test   9 unregistered spaces   7 empty   2 with data
    host     19 unregistered spaces  14 empty   5 with data

So the population that matters is small and specific: spaces with quads and no
catalog row, all of them from a path that bypasses the impl.

## The goal

Consistency. Every path that lands quads should leave the catalog describing
what is there, whoever wrote it — with exceptions only for tests that genuinely
need to sit outside normal space creation and management because of what they
are testing, and those declared somewhere a sweep reads rather than left to be
inferred from a space name.

## Approach, not yet decided

1. **Make registration a property of landing quads, not of three functions.**
   One helper that every writer calls — impl paths, `import_space`, and any
   future COPY loader. `load_wordnet_csv.py` currently has its own copy of the
   SQL, which is the second implementation already.
2. **Derive from the data, never from a flag.** Both fixes so far register from
   `SELECT DISTINCT context_uuid` joined to the term table, so the catalog
   cannot disagree with the quads it describes. A parameter saying which graph
   was *meant* to be written can be wrong; the contexts present cannot.
3. **Declared exceptions.** `devtools/reserved_spaces.py` already holds
   `UNREGISTERED_BY_DESIGN` for spaces the orphan sweep must not drop, for
   exactly this kind of "deliberately outside the normal process" case. A
   parallel declaration fits there rather than in a second list.
4. **Widen the guard.** The existing test covers named perf fixtures. The
   general invariant — *no space has quads in a context the catalog does not
   list* — is one query and would have caught both instances.

## Not to do

Do not register graphs from a sweep or a maintenance job. That repairs the
symptom on a schedule and leaves every writer free to keep skipping it, and it
is the same shape as the `issues/092` repair that wrote rows to make a detector
stop reporting. The write path should be correct.
