# The `search text` Command Reads A Column The FTS Decoupling Removed, And Its tsquery Parser Rejects Ordinary Input

## Status: FIXED 2026-09-21 — found while scoping keyword search over KG slot values

Both defects fixed in `cmd_search_text`. The query now reads
`{space}_fts_{index}`, resolves its default index from `{space}_fts_index`,
matches the stemmers the index was built with (`languages`, OR-joined), and
parses with `websearch_to_tsquery`. Covered by
`test_scripts/search/test_search_text_cmd.py` — a source-shape check plus a
behavioural run against a real FTS table, including every input that made the
old parser raise. The "no test existed" half of the cause is closed with it.

**Related:** the FTS decoupling that moved these columns
(`planning/planning_vector_geo/text_hybrid_search_plan.md` §6.1 Phase 6B);
`issues/202` (the other place a text search is slower or emptier than it looks)

Two defects in `vitalgraph/search_cmd/vitalgraphsearchutil_cmd.py::cmd_search_text`.
The first makes the command unable to return a row on any space created since
the decoupling. The second is latent behind it and would surface the moment the
first is fixed, so they are filed together.

## Defect 1 — it queries `{space}_vec_{index}` for `tsv` and `search_text`

    vitalgraphsearchutil_cmd.py:692     vec_table = f"{space}_vec_{index_name}"
    vitalgraphsearchutil_cmd.py:707     ts_rank(tsv, to_tsquery('english', $1)) AS rank,
    vitalgraphsearchutil_cmd.py:708     LEFT(search_text, 80) AS text_preview
    vitalgraphsearchutil_cmd.py:710     WHERE tsv @@ to_tsquery('english', $1)

Phase 6B moved `search_text` and `tsv` out of the vector table into
`{space}_fts_{index}`. The current DDL confirms it —
`sparql_sql_schema.py::create_vector_data_table_sql:2281` creates exactly four
columns:

    subject_uuid  UUID
    context_uuid  UUID
    embedding     vector(N)
    updated_time  TIMESTAMP

No `tsv`. No `search_text`. So the query cannot compile against any vector
table the current code creates.

### Measured — host dev cluster, `sparql_sql_graph`, 2026-09-21

    vector data tables                     37
      with a `tsv` column                   3      <- pre-decoupling vintage
      with a `search_text` column          32

Three tables out of 37 still carry `tsv`, and those are the only ones where
this command has ever worked. The 32 with `search_text` but no `tsv` are the
half-migrated middle; every table created from here on has neither.

The index it offers the user is wrong for the same reason. With no `--index`
it picks from the wrong registry:

    vitalgraphsearchutil_cmd.py:696  SELECT index_name FROM {space}_vector_index
                                     ORDER BY index_name LIMIT 1

FTS indexes are registered in `{space}_fts_index`. A space can hold an FTS
index and no vector index at all — which is the normal state for a space that
wants keyword search without embeddings — and there the command reports
"❌ No vector indexes found in space." for a space that does have a full-text
index sitting right there.

### Why nobody noticed

`cmd_search_text` wraps the whole body in

    except Exception as e:
        print(f"❌ Error: {e}")
    return True

`return True` keeps the CLI loop alive and the process exit code is unaffected,
so the failure is a printed line in an interactive shell and nothing else. The
same swallow means the `column "tsv" does not exist` that proves this defect is
never raised to anything that could fail a test.

Nothing in `tests/` covers `search text`.

## Defect 2 — the tsquery parser rejects input a user will type

    vitalgraphsearchutil_cmd.py:704     tsquery = " & ".join(query_text.split())

Whitespace-splitting and joining with `&` was the right instinct — it is what
stops `to_tsquery('english', 'saved application')` erroring outright — but it
only handles the separator. Each token still goes into `to_tsquery`, the
**operator-syntax** parser, unescaped. Measured on the dev cluster:

    query text        to_tsquery result
    ---------------   --------------------------------------------------
    saved application 'save' & 'applic'                        OK
    AT&T              NOTICE: query contains only stop words   matches nothing
    don't             NOTICE: query contains only stop words   matches nothing
    plaid!            ERROR: syntax error in tsquery: "plaid!"
    (x                ERROR: syntax error in tsquery: "(x"
    a | b             ERROR: syntax error in tsquery: "a & | & b"

The two NOTICE rows are the worse half: no error, a rank-ordered empty result,
and a user who concludes the corpus does not contain "AT&T".

`websearch_to_tsquery` is the parser built for untrusted input. It never raises
on user text, and it reads the syntax people already expect from a search box:

    websearch_to_tsquery('english', '"saved app" or plaid -declined')
      -> 'save' <-> 'app' | 'plaid' & !'declin'

There is in-repo precedent — `agent_registry_impl.py:1048` already uses it.
The codebase currently runs three different tsquery parsers:

    websearch_to_tsquery   agent_registry_impl.py:1048
    plainto_tsquery        vg_functions.py:786 (vg:textSearch),
                           entity_registry_search.py:215,367
    to_tsquery             vitalgraphsearchutil_cmd.py:707   <- this defect

They are not interchangeable and the difference is user-visible: `plainto_`
ANDs every term and offers no phrase, OR or negation; `websearch_` offers all
three. Picking one deliberately is a separate decision from fixing this
command, but the raw `to_tsquery` is wrong under any of them, because it is the
only one of the three that can throw on ordinary input.

## What the fix was

All four done.

1. Point the query at `{space}_fts_{index}` — it has `subject_uuid`,
   `context_uuid`, `search_text`, `tsv` and the GIN index, which is exactly
   what this command wants.
2. Resolve the default index from `{space}_fts_index`, and say "no FTS indexes"
   when there are none.
3. Replace `to_tsquery` + the manual `" & ".join` with
   `websearch_to_tsquery`, deleting the tokenizer rather than hardening it.
4. Give it a test. A command with a bare `except Exception: print` and no
   coverage is how a dead column survives a schema migration by two releases.

Do **not** fix this by adding `tsv` back to the vector tables. The decoupling
was deliberate and `vg:hybridSearch` already joins the two tables on their
shared `(subject_uuid, context_uuid)` primary key.
