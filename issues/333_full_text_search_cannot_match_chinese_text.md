# 333 — Full-text search cannot match Chinese text

## Status: OPEN. `cjk` BUILT 2026-11-07 (`0d75566f`). D2 DECIDED AND BUILT 2026-11-08: rarity-weighted scoring, hit@3 0.703 (production) -> 0.835 on DRCD.

- **Built and verified on the vg test stack, rebuilt for the change:**
  - both live defects
  - the `cjk` pseudo-language (§1-§6)
  - the transactional, batched language update
  - `get_fts_index` returning `rank_normalization`

  See "What was built".
- **D2 is not settled.** At 320k synthetic messages, ORing every pair of a
  whole question matches 6-88% of the corpus and costs 0.4-13 s for a ranked
  page of 25. See "Measured at scale". The narrowing rule needs a REAL
  corpus to choose, because the synthetic one inverts which pairs are rare.
- **The memory service's recall does not hit that latency** (2026-11-08).
  Its recall is a hybrid search inside one member graph, so cost is bounded by
  the member's messages. It was dominated by scoring each candidate two or
  three times; that is FIXED (`8e797759`): 967 → 403 ms default and 439 →
  340 ms planner, on a 20,000-message member. See "The memory service's
  actual query".

Requested by vital-saas-memory: their zh-Hant recall questions find nothing
through vitalgraph FTS, and the shared-character reorder in their own code is
working around it. The request is a `cjk` pseudo-language that indexes runs of
CJK characters as overlapping bigrams.

The approach holds up, and this file is now the implementation plan. Reviewing
the request found:
- three more sites that must change
- one live defect in the KGQuery FTS fast path
- one live defect in language validation, with a DDL-injection side
- one wrong claim: Simplified and Traditional do not match each other

Every SQL body below was run on PG 18.4, under the local C-locale cluster and
under the vg test stack's `en_US.utf8`, in `pg_temp` sessions with nothing
persisted. Prototype scripts: `/tmp/cjk333/` (not tracked).

## The defect, measured

PostgreSQL's default parser splits on whitespace and punctuation, and Chinese
has no spaces. What happens to punctuation depends on the database's
`LC_CTYPE`:

    C locale (local cluster):
      to_tsvector('simple', '我夢到樓梯，海邊。記得嗎') -> '我夢到樓梯，海邊。記得嗎':1
    en_US.utf8 (vg test stack):
      to_tsvector('simple', '我夢到樓梯，海邊。記得嗎') -> '我夢到樓梯':1 '海邊':2 '記得嗎':3

Either way, a query matches only if it is a whole run between punctuation
marks. "樓梯" does not match "我夢到樓梯". No configuration we ship can fix
this, and adding another language does not help.

## The request

- A SQL function that turns each CJK run into overlapping pairs
  ("我夢到樓梯" → "我夢 夢到 到樓 樓梯"), indexed with the built-in `simple`
  configuration.
- `cjk` as a value accepted in an FTS index's `languages`, used by the trigger
  and the query builder.
- On the query side, the same pairs, ORed rather than ANDed. A whole question
  like "記得我夢到樓梯那個夢嗎" would never match with AND. `ts_rank_cd` orders
  the hits.
- In vital-saas-memory: add `cjk` to `FTS_LANGUAGES`. Their reorder becomes a
  fallback.

### Alternatives (the request's table, confirmed)

`zhparser` and `pg_jieba` are C extensions that must be pinned per PG version,
as `vg_planner` is, and their dictionaries are tuned for Simplified. Splitting
in Python stores the text twice and needs the splitter on every write path.
`pg_bigm` serves `LIKE`, not the tsvector path. `pg_trgm` uses trigrams, so it
misses two-character words. Pure SQL also keeps us on open-source, self-run
components and runs unchanged on RDS.

### Separate per-language indexes: considered and declined

Keep one FTS index per searchable field, with `cjk` as one more arm of it:
- The `cjk` arm and the stemmer arms read disjoint scripts. Combining them
  costs one dead lexeme per CJK run on the stemmer side, and nothing on the
  `cjk` side for Latin text.
- Messages mix languages ("我在 Starbucks 等你"). Language detection is
  unreliable on short text.
- KGQuery searches ONE named index. Two indexes would push dual queries, a
  merge of incomparable `ts_rank_cd` scores, and cross-index paging onto every
  caller.

Revisit only for stemmers that share a script (`english` + `spanish`), and then
as a per-row language tag, not as split indexes.

## How a string is divided: by script, not by language

There is no encoding check (all text is UTF-8, whatever the language) and no
language detection. The text is NFKC-normalized. Then every character outside
the CJK ranges is replaced with a space, which leaves the runs:

    '我夢到樓梯，海邊。 dream 夢'
     run "我夢到樓梯" → bigrams 我夢 夢到 到樓 樓梯,  unigrams 我 夢 到 樓 梯
     "，"            → out of range, ends the run
     run "海邊"      → bigram 海邊,                unigrams 海 邊
     "dream"         → invisible to cjk; the english arm indexes it
     run "夢"        → unigram 夢

A mixed string therefore needs no segmentation step. "iPhone手機" gives
"iPhone" to `english` and "手機" to `cjk`. The query goes through the same run
extraction, so the index and the query agree on what a run is.

What script detection does and does not give:
- **Japanese** kanji are the same code points as Chinese characters, and kana
  are in the class, so a mixed run like "ひらがなと漢字" pairs across the
  boundary. Nothing needs to tell Chinese and Japanese apart.
- **Korean** (Hangul) is space-delimited and is left to the ordinary parser.
- **Simplified and Traditional do NOT match each other.** Measured: the query
  "楼梯" finds "我梦到楼梯" and not "我夢到樓梯". The method works the same on
  both, but they are different code points. The request's "works the same for
  Traditional and Simplified" is true only per variant. A member who writes in
  zh-Hant and asks in zh-Hant is served. Cross-variant recall is out of scope;
  see Follow-ups.

## Live defects found reviewing this

**1. `fast_fts_frame.py` uses only the FIRST configured language.** FIXED 2026-11-07.
`_resolve_index` returns `(list(langs) or ["english"])[0]`, and both the page
query (`:165`) and the match-set count (`:291`) build
`websearch_to_tsquery('{cfg}', …)` from it. On an `['english', 'spanish']`
index, a hit through the Spanish stemmer is found by the pipeline and missed by
the fast path, with no error. Under this change, an `['english', 'cjk']` index
would ignore `cjk` on the KGQuery FTS path, which is the path the memory
service's message search uses.

**2. Index languages are not validated, and are interpolated into DDL.** FIXED 2026-11-07.
- A language name is checked nowhere: not in `CreateFtsIndexRequest`, not in
  `ensure_fts_index`, not in `update_fts_languages`, not in `config_apply`.
  PL/pgSQL does not resolve `'x'::regconfig` when it creates the trigger
  function. Verified: the trigger creates cleanly, and the first INSERT fails
  with `text search configuration "cjk" does not exist`. Auto-sync catches that
  per subject and logs a warning (`auto_sync.py:532`). The write returns 200 and
  the subject is never indexed. If vital-saas-memory sends `cjk` to a server
  older than this change, that is exactly what happens.
- The name is pasted into SQL unquoted:
  `f"to_tsvector('{lang}'::regconfig, …)"` in `_build_tsv_concat_expr` and
  `build_tsv_batch_expr`, run with `conn.execute` and no arguments. That is the
  simple-query protocol, which accepts several statements. So any caller with
  space-write access can run arbitrary SQL as the app role by choosing a
  language name.
- Also, `config_apply._apply_fts_indexes` ignores `update_fts_languages`'s
  return value and reports a failed language change as `updated`.

## What the defect fixes built (2026-11-07)

The builder half of Implementation §2 and the validation of §3, without `cjk`:

- **`vitalgraph/db/sparql_sql/fts_languages.py`** (new):
  - `tsvector_expr` and `tsquery_expr`, the one builder per side
  - `check_language_name`: a plain identifier, `^[a-z][a-z0-9_]{0,62}$`.
    Every builder applies it, so a bad name already stored in a registry
    fails loudly instead of being interpolated.
  - `validate_fts_languages(conn, languages)`: non-empty, no duplicates, each
    name a visible `pg_ts_config`
  - `InvalidFtsLanguages(ValueError)`
- **All five sites go through the builders:**
  - `_build_tsv_concat_expr` and `build_tsv_batch_expr`
  - `vg_functions._build_tsquery_expr`, now a wrapper
  - `fast_fts_frame._resolve_index`, which returns `(table, languages)`
    (defect 1), with `_build` and `_match_set_is_small` taking the list
  - the CLI's `search-text`

  SQL for every valid list is byte-identical to before. Pinned against
  verbatim copies of the old builders.
- **Validation, before anything is created or changed:**
  - `ensure_fts_index` validates only when CREATING. An existing index ignores
    *languages* as it always has, so callers passing a default list are
    unaffected.
  - `update_fts_languages` always validates.
  - Both raise `InvalidFtsLanguages`. The endpoint answers `invalid_request`
    in an HTTP 200 body for create and update.
  - `config_apply` validates in the dry run too. It reports a refusal under
    `failed`, with the reason in a new `report["reasons"]`. It no longer
    reports a failed language change as `updated`.

Tests:
- `tests/unit/sparql_sql/test_fts_languages.py`: byte-identical SQL;
  refusal by every builder including the DDL; validation shape.
- `test_fts_frame_fast_path.py`: every language in the page, the count and
  the size probe.
- `tests/integration/test_fts_index_languages.py`, on real PG:
  - The real fast-path SQL is run on a real space. A Spanish-only document
    (`corrían`, queried as `corrimos`) is found by page and count.
  - The same SQL with only the first language finds 0, which is the defect.
  - An unknown or injected language creates no row and no table, and runs
    nothing.
  - A refused update leaves the registry and the trigger source unchanged.
  - The `config_apply` cases.
- `tests/api/test_fts_index_languages_api.py`, through HTTP:
  `invalid_request` for unknown, injected and duplicate lists; nothing
  created or changed.

Results:
- unit: 6,238 passed; 1 failed, the index check for this uncommitted issue file
- integration: FTS, config and space suites green
- API: the new suite and `test_text_search_api.py` green against the
  rebuilt image
- `test_tsquery_parser.py` PART B against the test stack's PG: green

The transaction and batched refresh deferred here were built with `cjk`
(below).

## What was built (2026-11-07, `cjk`)

- **SQL functions:** `vitalgraph_cjk_runs`, `_index_text`, `_tsvector` and
  `_tsquery`, as specified in §1. They live in `sparql_sql_admin.FUNCTIONS`,
  which is keyed by `regprocedure` signature, in dependency order.
  `FUNCTION_DDL` is derived from it, so both installers carry them.
- **`scripts/install_sql_functions.py`** (the pre-deploy step):
  - dry run by default; `--apply` creates what is missing
  - `--replace` is required to touch an existing function
  - refuses a non-UTF8 database
  - prints a census of stored FTS language lists that fail validation (none
    on the test stack's 29 spaces)
  - applied to the test stack; a second run reports all 6 present
- **`fts_languages`:** `cjk` arms on both sides, and the COALESCE NULL
  contract. Validation refuses `cjk` until the functions exist, naming the
  script.
- **`update_fts_languages`:**
  - registry and trigger change in ONE transaction
  - the refresh is `refresh_fts_tsv`: keyset batches of 5,000, each its own
    statement, idempotent
  - not found returns False; a failed refresh raises `FtsRefreshIncomplete`,
    which the endpoint answers as `store_failed` with the remedy; any other
    failure raises with nothing changed
- **`refresh-fts -s SPACE --index N [--batch-size B]`** in
  `vitalgraphsearchutil`.
- **`get_fts_index` / `list_fts_indexes` return `rank_normalization`.** It was
  missing, so `config_apply` read it as 0 and reported, and rewrote, an index
  whose document set a non-zero value on every apply.

Tests:
- **Unit:** `cjk` arms; the COALESCE form; validation with and without the
  functions; both installers carry all four functions, callees first.
- **Integration**, `tests/integration/test_cjk_fts.py` (45 tests, real PG):
  - the functions' lexemes and query shapes, NULL cases, and volatility
  - matching for zh-Hant, zh-Hans (does not cross-match), kana/kanji, mixed
    and English, through the shared builders
  - the trigger and the fast path's real SQL on a loaded index; a `cjk`-only
    index with a Latin query
  - a 2-row-batch refresh that equals a fresh build
  - an interrupted refresh that completes on rerun
  - new writes using the new list at once
  - a failed refresh that raises and says so
  - a failed trigger replace that leaves the registry unchanged
- **Rank normalization** test in `test_fts_index_languages.py`.
- **API**, `tests/api/test_cjk_fts_api.py`: messages written as entity →
  frame → text slot through the server, auto-synced into an
  `['english','cjk']` index, found by KGQuery frame search for all 10 query
  shapes.

Results:
- unit: 6,249 passed; 1 failed, the uncommitted-issue index check
- integration: 89 passed (cjk, languages, config export)
- API: 69 passed (cjk, languages, text search, kgqueries)

**Found while testing, already tracked:** a multi-entity
`create_kgentities` batch leaves its frames and slots without
`hasKGGraphURI` (`issues/257`), so a frame query finds none of them. The API
test creates one conversation per call and says why.

## Measured at scale (2026-11-07)

`test_scripts/perf/issue333_cjk_scale.py`:
- 320,000 synthetic zh-Hant messages, 37 characters on average, Zipf over a
  ~200-word vocabulary, seeded
- temp tables on the vg test stack, with the test app STOPPED for the run
  (its maintenance sweep was at 340% CPU after the restart) and no swap
- 5 runs per cell

| | `english` | `english` + `cjk` |
|---|---|---|
| batched refresh, total (64 × 5,000) | 2.2 s | 20.0 s (median batch 296 ms, max 688 ms) |
| GIN build / size | 2.3 s / 63 MB | 9.3 s / 113 MB |
| lexemes per row | 3.7 | 53.8 |
| trigger, µs per row (med) | 4.8 | 59.2 |

The write side is fine. A batch is well under any `statement_timeout`, and
0.06 ms per write is negligible.

The read side is NOT, with OR across every pair (median top-25 ms):

| question | matches | ms |
|---|---|---|
| 記得我夢到樓梯那個夢嗎 | 40,183 | 457 |
| 我上次說的海邊旅行 | 37,551 | 1,555 |
| 媽媽生日禮物是什麼 | 74,563 | 3,964 |
| 那部電影叫什麼名字 | 282,360 (88%) | 12,973 |
| 我的貓咪生病了 | 81,484 | 3,389 |
| `"夢到樓梯"` (phrase) | 16 | 2 |
| 夢 (unigram) | 71,630 | 1,750 |

The cost is `ts_rank_cd` over every match (~40 µs each), the same O(matches)
shape `filter_pushdown.py:1329` records for English.

**Narrowing tried on the same corpus** (`/tmp/cjk333/narrow.py`, exact
document frequency per query pair):

| question | OR all | drop pairs in >1% of docs | drop >5% | ≥2 of the 4 rarest | AND all |
|---|---|---|---|---|---|
| 記得我夢到樓梯那個夢嗎 | 40,183 / 467 ms | 442 / 3 ms | 40,183 / 442 ms | 0 | 0 |
| 媽媽生日禮物是什麼 | 74,563 / 2,876 ms | 496 / 2 ms | 9,289 / 80 ms | 1 | 0 |
| 那部電影叫什麼名字 | 282,360 / 9,684 ms | 83 / 1 ms | 8,914 / 81 ms | 0 | 0 |
| 我的貓咪生病了 | 81,484 / 2,619 ms | 909 / 4 ms | 7,477 / 65 ms | 8 | 0 |

**Why this corpus cannot decide D2.** Dropping common pairs makes every query
fast, but here it drops the CONTENT words (樓梯, 電影 at 87.5%, 生日, 貓咪)
and keeps the junk pairs that span a word boundary (梯那, 得我, 物是). That
happens because a 200-word vocabulary makes every real word common. In real
chat the relationship roughly inverts: content words are rare and function
pairs (我的, 什麼, 那個) are common. So a frequency rule is plausible, but its
threshold and its effect on recall can only be measured on real messages.
AND and ≥2-of-k are too strict for whole questions in any corpus.

## The memory service's actual query (2026-11-08)

**The scale benchmark above does not measure what vital-saas-memory runs.**
`vital_saas_memory/query.py` recalls with ONE SPARQL query per kind, in
parallel. Each is:
- `BIND(vg:hybridSearch(?s, <cues>, <index>, 0.5) AS ?score)`, vector and
  full text at alpha 0.5
- inside `GRAPH <member graph>`, with one graph per member in one shared space
- `FILTER(?score > 0) ORDER BY DESC(?score) LIMIT 12`

A hybrid has no top-k path. It is a correlated subquery that scores EVERY
candidate the pattern yields, which here means every message in the member's
graph. So the cost is set by the number of messages in that graph, not by how
many pairs the query matches. OR breadth affects the ranking, not the cost.
And there is no real Chinese corpus to measure against: the memory service's
zh-Hant tests are unit-test strings, and the starsign app is not live.

**Fixture** (`test_scripts/perf/issue333_memory_recall_fixture.py`):
- the space provisioned by the memory service's own `config.provision`, with
  `cjk` added to its FTS languages
- messages written as the platform writes them: `KGChatUserMessage` /
  `KGChatBotMessage` through `objects.create_objects`, embedded and indexed by
  auto-sync with MiniLM-multilingual
- one heavy member (20,000 messages) and 20 typical ones (1,000 each): 40,000
  messages in `perf_memcjk` on the vg test stack
- statistics built through the admin resync

**Measurement** (`test_scripts/perf/issue333_recall_explain.py`):
- the exact SPARQL `build_query` emits, with zh-Hant cues
- SQL generated in-process on the default path and with the planner on
  (`planner_ext=True`, `VG_PLANNER_FEATURES=qtree`)
- a stored embedding substituted for the query vector
- EXPLAIN ANALYZE, 5 runs per cell, test app stopped
- the host had swap in use but none being written (0 swap-outs per 10 s)

Median ms:

| member | path | before | `cjk` cost | score computed once |
|---|---|---|---|---|
| heavy, 20,000 | default | 967 | +342 (625 without `cjk`) | **403** |
| heavy, 20,000 | planner `qtree` | 439 | +232 (207 without) | **340** |
| typical, 1,000 | default | 57 | +16 | **47** |
| typical, 1,000 | planner `qtree` | 30 | +12 | **23** |

**Where the time went.** The hybrid score was evaluated more than once per
candidate:
- three times on the default path: the `?score > 0` filter, the sort key and
  the output column, because each companion column carried its own copy of the
  expression and PostgreSQL inlines a flattened sub-select's expression at
  every reference
- twice on the planner path (filter and sort key), the same way

Each evaluation is two index probes plus the scoring arithmetic. `cjk` adds
about 5.8 µs to each (342 ms over 60,000 evaluations, 232 ms over 40,000): the
54-lexeme tsvector and the 10-term query in `ts_rank_cd`. So the multiplier
mattered more than `cjk`.

**Fixed: `emit_extend.compute_once`**, used by both `emit_extend` and
`qplan`'s BIND levels. A `vg:` function in a BIND is emitted as
`LEFT JOIN LATERAL (SELECT <expr> AS val OFFSET 0) AS x ON true`, and every
companion reads `x.val`:
- OFFSET 0 stops the sub-select being pulled up and re-inlined
- because it is a JOIN rather than a fence around the child, a FILTER on the
  child's own columns (the recall's date range) still applies before any score
  is computed
- LEFT JOIN `ON true` never loses a row, and the expression's own NULL survives
- anything that is not a `vg:` function emits byte for byte as before

Tests:
- `tests/integration/test_vg_score_computed_once.py`, on real rows: the FTS
  side table is probed 5 times for 5 candidates, and the page is right.
  Against the reverted code it fails with 15 probes.
- `tests/unit/sparql_sql/test_compute_once.py` pins the helper's scope.

Results with the change:
- unit: 6,257 passed
- integration: 977 passed, 2 skipped, 3 xfailed, 0 failed

**What is left per path** (heavy member):
- planner: about 34 ms of pattern hash joins, then 20,000 single evaluations
  at about 16 µs each. Terms are already resolved only for the 12 rows
  returned.
- default: the same score work, but all six terms are still resolved for every
  candidate before the sort. `_emit_late_text` declines a requested ORDER BY
  and more than one projected variable, and the recall has both. That is the
  remaining gap to the planner, about 60 ms.

**Gap closed: `emit_slice._emit_late_text_ordered`** (2026-11-08). For
`ORDER BY <keys> LIMIT k [OFFSET o]` with a requested order:
- the child is emitted with text suppressed for every projected variable
  nothing inside reads
- the page is cut on the child's own order
- the page is numbered right after the cut, and the outer query sorts by that
  number, so the result is the child's order exactly, whatever the keys are
- each moved variable gets a `LEFT JOIN` to the term table on the page's rows
  only
- columns stay in projection order

"Read inside" means a FILTER or BIND (`compute_late_text_vars`), or an ORDER
key. ORDER keys are held as bare names, which no expression walker reads, so
they are added explicitly, or a text sort key would sort on NULLs (the
`issues/324` shape). Two small changes went with it, both in late-text mode
only:
- a `vg:` function's entity argument counts as a uuid read
- a BIND's expression is read like a FILTER's

Verified equal to the inline form, row for row and in order:
- 36 recall cases: 3 members, 6 cues, with and without the date filter
- 7 general shapes: a text sort key, DESC date, OFFSET, an unbound OPTIONAL, a
  text FILTER, a score with a text key, and one that correctly declines

`tests/integration/test_ordered_page_resolves_text_late.py` pins 7 cases,
including that a text sort key keeps its text inside. All 7 fail with the
bare-name handling removed.

Recall, default path, median ms (test stack, 5 runs, three rounds on the heavy
member):

| member | before | after | planner `qtree` |
|---|---|---|---|
| heavy, 20,000 | 362 | **304-308** | 301 |
| typical, 1,000 | 39 | **26** | 22 |

**Measured as served, and on the planner stack** (2026-11-08). The explain
script now runs each statement the way the executor does, through its own
`_apply_join_order` / `_apply_planner_advice` in a transaction. A `qtree` plan
always has a fixed join order, so the server pins `join_collapse_limit = 1`,
which the first numbers above did not do. `perf_memcjk` was then copied to the
planner stack (dump and restore, test stack stopped, one stack at a time) and
measured with `vg_planner` applying the advice (`VG_PLANNER_EXTENSION=require`).
Median ms, 5 runs, no swap-outs:

| member | default path | planner, vg test stack (in-process, pinned) | planner stack, `vg_planner` 0.2 |
|---|---|---|---|
| heavy, 20,000 | 320-362 | 285 | **299** |
| typical, 1,000 | 34-39 | 20 | **16** |

The extension changes little for this shape, because almost all the cost is the
score evaluations, which are not a join-order question. Copy on the planner
stack: `perf_memcjk`, restored WITHOUT its triggers (read-only: a write into it
is not indexed), and its description says so.

**A second defect, found in the score subquery: it was not graph-scoped.**
The side tables are per space and keyed (subject, context). Every `vg:` side
lookup (score, `textMatch`, vector, geo) and the FTS push-down were keyed on
the subject alone. They were scoped to a graph only under a server-side graph
lock, and a query's own `GRAPH <g>` scoped nothing. So in a space holding the
same subject in two graphs, `LIMIT 1` read whichever graph's row the index
returned first: the full-text score, the text match and the vector all came
from the other graph. Proven on the planner copy, where one subject with rows
in two graphs returned both. The memory service is not exposed, because its
message and document URIs are unique per member. But any space with copied or
archived graphs is.

**Fixed:**
- `collect` records, per variable, the ONE constant graph it is bound in
  (`AliasGenerator.var_graphs`): from the graph lock, `GRAPH <uri>`, or the
  default graph. A variable under `GRAPH ?g`, in two graphs, inside a dataset
  clause, or unscoped is marked ambiguous.
- `_context_clause(ctx, entity_var)` emits
  `AND context_uuid = '<uuid>'::uuid` from that record. It is a literal, as in
  `issues/258`.
- All 11 `vg_functions` call sites, both FTS push-down sites and the FTS leaf
  measurement pass their entity variable, so the measured leaf and the served
  one agree.

Recall timings are unchanged by it (299 / 16 ms planner, 327 / 34 ms default).

`tests/integration/test_vg_search_is_graph_scoped.py`: the same subject in
two graphs. A `GRAPH <g1>` hybrid scores from g1's text and a `GRAPH <g2>` one
does not; `textMatch` matches per graph. Both fail against the reverted
clause. `GRAPH ?g` stays unscoped, which is pinned as a control.

Changing `collect` exposed an unrelated defect in the same function: under
FROM / FROM NAMED a pattern kept only its first triple. It is fixed with its
own issue, `issues/334`.

**What this means for D2.** For the memory service's recall, the 0.4-13 s
latency measured above never happens: the member graph bounds the candidates.
D2 becomes a RANKING question: whether ORed pairs without rarity weighting
rank the right message first. That still needs real messages to answer.

## D2 measured on real Traditional Chinese: DRCD (2026-11-08)

There is no zh-Hant member data, and no public zh-Hant chat-recall benchmark
was found. The closest real dataset is **DRCD** (Delta Reading Comprehension
Dataset, https://github.com/DRCKnowledgeTeam/DRCD, CC-BY-SA 3.0, Taiwan
Wikipedia), and that is what this measures against:
- dev + test give 2,000 paragraphs, split into 19,910 sentences (median 38
  characters, about chat-message length)
- 7,017 annotator-written questions (median 21 characters), each tied to the
  sentence that holds its answer

So every question has one known right item.

**Harness:** `test_scripts/perf/issue333_drcd_eval.py`.
- `prepare` splits the data into items and questions.
- `load` writes the sentences into ONE member graph of `eval_drcd333`,
  provisioned by the memory service's own `config.provision` with `cjk`
  added, as `KGChatUserMessage` objects through the server. Auto-sync
  embeds them with MiniLM-multilingual and indexes them.
- `eval` scores 1,000 questions (seed 333) through the memory service's own
  `build_query` / `fold` / `cjk_first`, and runs the full-text ranking
  candidates as SQL on the same index.

The data stays outside the repo. The first load wrote no message dates, which
the message query requires, so the run uses `--no-date`: it drops that one
pattern, which only feeds date filters. `load` now writes dates.

hit@3 is what the memory service returns per kind:

| variant | hit@1 | hit@3 | hit@12 | MRR@12 | same paragraph @3 | median ms |
|---|---|---|---|---|---|---|
| vector only (Chinese recall today, effectively) | 0.460 | 0.607 | 0.731 | 0.546 | 0.723 | 240 |
| vector + `cjk_first` reorder (TODAY'S PRODUCTION) | 0.649 | 0.703 | 0.731 | 0.679 | 0.825 | 226 |
| hybrid 0.5 with `cjk`, as built | 0.620 | 0.765 | 0.870 | 0.703 | 0.889 | 227 |
| `cjk` full text alone (`ts_rank_cd`) | 0.517 | 0.682 | 0.800 | 0.610 | 0.822 | 221 |
| full text, `ts_rank_cd` normalization 1 (SQL) | 0.589 | 0.717 | 0.818 | 0.665 | 0.852 | 23 |
| **full text, rarity-weighted: sum of ln(N/df) over matched pairs (SQL)** | **0.725** | **0.817** | **0.883** | **0.778** | **0.947** | 16 |
| idf, pairs in >5% of sentences pruned (SQL) | 0.722 | 0.816 | 0.882 | 0.776 | 0.947 | 14 |
| idf, at least 2 matching pairs (SQL) | 0.724 | 0.816 | 0.880 | 0.776 | 0.946 | 16 |

The server's full-text-only result equals the SQL `ts_rank_cd` variant on every
metric, so the SQL variants rank the same arm the server does.

**D2 is decided: weight pairs by rarity.**
- `cjk` as built already beats production: hit@3 0.703 → 0.765, hit@12
  0.731 → 0.870.
- Rarity weighting lifts the full-text arm alone from 0.682 to 0.817 hit@3
  (hit@1 0.517 → 0.725), which beats the hybrid as built.
- Pruning common pairs and requiring two matches add nothing on top: once rare
  pairs dominate the score, common ones stop mattering.

That is BM25's rarity weighting, the mechanism the Lucene engines rely on for
CJK bigrams.

Caveats:
- DRCD questions are factual and share much wording with their answers. Real
  recall cues are vaguer, which favours the vector arm, so the gain will likely
  be smaller on chat.
- The hybrid with a rarity-weighted arm is not measured until it is built.
- Latencies are from a loaded host and only indicative.

## D2 built: rarity-weighted `cjk` scoring (2026-11-08)

**Score.** Every ranked text call on a `cjk` index (`vg:textSearch`, its top-k
form, `vg:hybridSearch`) now scores the CJK part by rarity-weighted COVERAGE:
the summed weights of the query's terms that a row contains, divided by the
summed weights of all of them, with w = ln(1 / freq).
- It lies in [0, 1], because the hybrid adds it to a cosine.
- It orders rows exactly as the raw idf sum does.
- `ts_rank_cd` over the index's other languages is added, so Latin words in a
  mixed query still count.
- `_lexical_rank_sql` is the one place every ranking site gets it from.

**Frequencies.** They come from PostgreSQL's own `ANALYZE` statistics for the
index's `tsv` column (`pg_stats.most_common_elems` and
`most_common_elem_freqs`). A term below the tracked list gets the list's floor.
There is nothing new to maintain.
- They are read once per (index, query) in a generator pre-pass
  (`fts_rarity.load_cjk_weights`) into `aliases.cjk_weights`.
- The query's terms come from a fifth SQL function,
  `vitalgraph_cjk_query_terms`, built from the same token rules as the tsquery,
  so Python never re-implements the tokenizer.
- Anything missing (no statistics yet, an install without the function, a
  failed read) leaves the arm on `ts_rank_cd`. It never fails the query.

**Statistics target.** A `cjk` index's `tsv` column gets
`SET STATISTICS 1000` at creation and when `cjk` is added, and is reset when it
is removed. At the default target the list holds 1,000 elements (floor 0.86%
of rows) and hit@3 was 0.801. At 1000 it holds 10,000 (floor 0.06%) and hit@3
is 0.811, against 0.817 with exact frequencies. ANALYZE of 19,910 rows took
286 ms.

**Measured through the server on DRCD** (1,000 questions, seed 333, 19,910
sentences in one member graph):

| variant | hit@1 | hit@3 | hit@12 | MRR@12 | median ms |
|---|---|---|---|---|---|
| today's production (vector + `cjk_first`) | 0.649 | 0.703 | 0.731 | 0.679 | 218 |
| hybrid, `cjk` with `ts_rank_cd` | 0.620 | 0.765 | 0.870 | 0.703 | 227 |
| **hybrid, `cjk` rarity-weighted** | **0.744** | **0.835** | **0.898** | **0.796** | 195 |
| full text alone, rarity-weighted | 0.717 | 0.811 | 0.884 | 0.771 | 221 |

The server's full-text-only result equals the SQL `idf-pgstats` variant on
every metric. Against today's production recall, that is +13 points of hit@3
and +17 of hit@12.

**Deploy.** `vitalgraph_cjk_query_terms` is new, so every install re-runs
`scripts/install_sql_functions.py --apply` as the app role. Until it does, an
existing `cjk` index keeps `ts_rank_cd`, and a NEW `cjk` index is refused with
a message naming the script.

**Tests:**
- `tests/unit/sparql_sql/test_fts_rarity.py`: weights, the floor, no
  statistics, the CJK-only term guard, the score SQL, the statistics target
- `tests/integration/test_cjk_rarity_ranking.py`: 60 messages repeating a
  common pair against one holding the rare pair. The rare one ranks first, and
  `ts_rank_cd` alone puts a common one first (pinned as a control). It fails
  with the weights disabled.

(The `/tmp/cjk333/` prototype and narrowing scripts cited above were lost in
a reboot on 2026-11-08. The scale benchmark and both recall scripts are in
`test_scripts/perf/`.)

## Design decisions

| # | Question | Decision |
|---|---|---|
| D1 | Single-character queries ("夢") | Index BOTH bigrams and unigrams. The query uses bigrams for a run of ≥2 characters and the unigram for a 1-character run. Otherwise "夢" finds nothing (measured). |
| D2 | Bare CJK terms: AND or OR | **OPEN.** Built as OR, as the request says. The measurement demands narrowing (see "Measured at scale"), and the rule must be chosen on a real corpus. |
| D3 | Quoted phrase `"夢到樓梯"` | The run becomes a bigram chain, `'夢到' <-> '到樓' <-> '樓梯'`, and is REQUIRED (ANDed), as a websearch phrase is. Bigrams first in the tsvector keeps their positions consecutive. Unigrams follow, so they never break a chain. |
| D4 | Exclusion `-樓梯` / `-"夢到樓梯"` | The run becomes a chain and is negated as a unit: `!('夢到' <-> '到樓' <-> '樓梯')`. Negating each pair separately would over-exclude. |
| D5 | `or` keyword | Ignored by the `cjk` arm, whose bare terms are already ORed. The stemmer arms still parse it. |
| D6 | Query with no positive CJK (`dream`, `-樓梯`) | The `cjk` arm returns NULL and contributes nothing (see "The NULL contract"). |
| D7 | Mixed query (`stairs 樓梯`) | Each arm sees the whole query, ORed as today. Under `english`, the CJK run is a required lexeme that never matches, so in practice the CJK part decides recall and the Latin part only adds rank. Measured: `stairs 樓梯` hits "我夢到樓梯 dream" and not "I dreamed of stairs". Accepted for v1 and documented. |
| D8 | NFKC | Applied inside the `cjk` functions only. Applying it to the stemmer arms too would change every existing index's output and force a re-index of every FTS index in every install. Separate follow-up. |
| D9 | Ranges | `U+3040–30FF` (hiragana, katakana), `U+3400–4DBF` (Ext A), `U+4E00–9FFF` (unified), `U+F900–FAFF` (compatibility), `U+20000–3134F` (Ext B–H). Full-width punctuation (`U+3000–303F`, `U+FF00–FFEF`) is outside, so it ends a run. NFKC turns `，` into `,`, which ends a run all the same. |

## Implementation

### 1. SQL functions — `sparql_sql_admin.py`

A new `_VITALGRAPH_CJK_DDL` is added to `FUNCTION_DDL`, so both installers
(`SparqlSQLAdmin.init_tables`, `scripts/perf_init_db.py`) get it. The names
follow the `vitalgraph_*` convention of the existing functions rather than the
request's `vg_*`.

```sql
-- The CJK runs of a string, NFKC-normalized. One definition of the class.
CREATE OR REPLACE FUNCTION vitalgraph_cjk_runs(t text) RETURNS text[]
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $f$
  SELECT array_remove(string_to_array(regexp_replace(normalize(t, NFKC),
    '[^぀-ヿ㐀-䶿一-鿿豈-﫿\U00020000-\U0003134F]+',
    ' ', 'g'), ' '), '')
$f$;

-- Index text: every bigram in order (consecutive positions, so phrases work),
-- then every character as a unigram (D1).
CREATE OR REPLACE FUNCTION vitalgraph_cjk_index_text(t text) RETURNS text
LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE AS $f$
DECLARE r text; n int; bi text := ''; uni text := '';
BEGIN
  FOREACH r IN ARRAY vitalgraph_cjk_runs(t) LOOP
    n := length(r);
    FOR i IN 1 .. n - 1 LOOP bi  := bi  || substr(r, i, 2) || ' '; END LOOP;
    FOR i IN 1 .. n     LOOP uni := uni || substr(r, i, 1) || ' '; END LOOP;
  END LOOP;
  RETURN bi || uni;
END $f$;

CREATE OR REPLACE FUNCTION vitalgraph_cjk_tsvector(t text) RETURNS tsvector
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $f$
  SELECT to_tsvector('simple'::regconfig, coalesce(vitalgraph_cjk_index_text(t), ''))
$f$;

-- Query: websearch-shaped (D3-D6). Bare runs are ORed; quoted runs are
-- required chains; negated runs are negated chains. NULL when there is no
-- positive CJK.
CREATE OR REPLACE FUNCTION vitalgraph_cjk_tsquery(q text) RETURNS tsquery
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $f$
DECLARE tok text[]; neg boolean; quoted boolean; r text; n int;
        terms text[]; part tsquery; chain tsquery; bare tsquery; req tsquery;
        has_pos boolean := false;
BEGIN
  IF q IS NULL THEN RETURN NULL; END IF;
  FOR tok IN SELECT regexp_matches(q, '(-?)"([^"]*)"?|(-?)(\S+)', 'g') LOOP
    neg    := coalesce(tok[1], tok[3]) = '-';
    quoted := tok[2] IS NOT NULL;
    FOREACH r IN ARRAY coalesce(vitalgraph_cjk_runs(coalesce(tok[2], tok[4])), '{}') LOOP
      n := length(r);
      terms := CASE WHEN n = 1 THEN ARRAY[r]
                    ELSE ARRAY(SELECT substr(r, i, 2)
                               FROM generate_series(1, n - 1) i ORDER BY i) END;
      IF quoted OR neg THEN
        chain := NULL;
        FOREACH r IN ARRAY terms LOOP
          part  := quote_literal(r)::tsquery;
          chain := CASE WHEN chain IS NULL THEN part ELSE chain <-> part END;
        END LOOP;
        IF neg THEN chain := !! chain; ELSE has_pos := true; END IF;
        req := CASE WHEN req IS NULL THEN chain ELSE req && chain END;
      ELSE
        FOREACH r IN ARRAY terms LOOP
          part := quote_literal(r)::tsquery;
          bare := CASE WHEN bare IS NULL THEN part ELSE bare || part END;
        END LOOP;
        has_pos := true;
      END IF;
    END LOOP;
  END LOOP;
  IF NOT has_pos THEN RETURN NULL; END IF;
  IF bare IS NULL THEN RETURN req; END IF;
  IF req  IS NULL THEN RETURN bare; END IF;
  RETURN bare && req;
END $f$;
```

Why each is safe:
- **IMMUTABLE is honest.** `normalize`, `regexp_replace` over explicit
  code-point ranges (no locale-dependent class like `[[:alpha:]]`), `substr`,
  and `to_tsvector` with a constant config are all immutable. `normalize` is
  `provolatile = i` on 18.4. The output depends only on the Unicode tables
  compiled into PostgreSQL. A PG major upgrade can change them, so re-check
  `cjk` indexes after one, as for any collation-sensitive index.
- **No query text reaches tsquery syntax.** Every lexeme is drawn from the CJK
  class, which contains no quote, backslash or operator, and is still wrapped
  in `quote_literal`. Measured: `樓梯' | !x \ ) & (` → `'樓梯'`.
- **Changing a body is a re-index.** Changing the ranges or the n-gram rule
  changes what every existing `cjk` row should hold. Treat a body change as a
  migration that refreshes every `cjk` index, never as a silent
  `CREATE OR REPLACE`.

**Pre-deploy step for existing installs:** a new
`scripts/install_sql_functions.py`, on the `install_write_log.py` pattern:
- dry run by default; `--apply` creates the functions that are MISSING (checked
  with `to_regprocedure`)
- `--replace` is required to touch an existing one
- refuses unless `server_encoding = UTF8`, because `normalize` needs it
- run as the app role, not the RDS master, or `vitalgraph_user` cannot use the
  functions

Idempotent. It also prints a census of FTS indexes whose stored languages fail
the new validation (§3), because any such index in the wild is silently
unindexed today.

### 2. One builder per side — new `vitalgraph/db/sparql_sql/fts_languages.py`

```python
PSEUDO_LANGUAGES = frozenset({"cjk"})
LANGUAGE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")

def tsvector_expr(languages, text_sql: str, joiner: str = " || ") -> str:
    """`to_tsvector(lang, text) || …`; `cjk` → `vitalgraph_cjk_tsvector(text)`."""

def tsquery_expr(languages, text_sql: str) -> str:
    """The OR of every arm. Without `cjk` the output is BYTE-IDENTICAL to
    today's `_build_tsquery_expr`. With it:
        others present: COALESCE(<others> || vitalgraph_cjk_tsquery(q), <others>)
        cjk alone:      vitalgraph_cjk_tsquery(q)
    """
```

`text_sql` is whatever the call site has: a doubled-quote literal
(`'{safe_text}'`, `vg_functions`), a parameter (`$1`, `fast_fts_frame` and the
CLI), or `COALESCE(NEW.search_text, '')` (trigger). Both builders refuse a name
that fails `LANGUAGE_NAME` as defence in depth behind §3, so nothing unchecked
ever reaches an f-string again.

**The NULL contract.** `vitalgraph_cjk_tsquery` returns NULL when the query has
no positive CJK. `tsquery || NULL` is NULL, hence the `COALESCE`. For a
`cjk`-only index, NULL means "matches nothing", and every consumer already
reads it that way:
- `tsv @@ NULL` is not true, so WHERE drops the row.
- `text_search_sql`'s correlated subquery then returns no row, which is the
  same NULL score as a non-match.
- The hybrid's `CASE WHEN f.tsv @@ q … ELSE 0` gives 0.
- Counts give 0.

Each case gets a test. This was chosen over an "empty tsquery" sentinel because
every empty-tsquery constructor raises a NOTICE on each call (measured), which
would flood the server log once per query.

### 3. Language validation — `fts_index_lifecycle.py`

```python
async def validate_fts_languages(conn, languages) -> Optional[str]:
    """None if valid, else the reason. Each name must match LANGUAGE_NAME and be
    either a VISIBLE pg_ts_config (`pg_ts_config_is_visible(oid)`) or in
    PSEUDO_LANGUAGES. No duplicates, at least one name. `cjk` additionally
    requires vitalgraph_cjk_tsvector(text) and vitalgraph_cjk_tsquery(text) to
    exist, so a server deployed before the pre-deploy step refuses `cjk` with a
    message naming the script, instead of accepting it and indexing nothing."""
```

Called by:
- `ensure_fts_index`, before the registry INSERT, so a refused index leaves no
  row and no table
- `update_fts_languages`, before anything
- `config_apply._apply_fts_indexes`, in DRY RUN as well, reported under
  `failed`. This also fixes the ignored return value, so a failed language
  change is no longer reported as `updated`.

The two lifecycle functions raise a typed `InvalidFtsLanguages(reason)`. The
endpoint maps it to `OperationStatus.INVALID_REQUEST` in an HTTP 200 body, per
the codebase's contract. Today `create_index` turns every lifecycle failure
into a 500, and `update_languages` turns every failure into NOT_FOUND.

### 4. Call sites

| Site | Change |
|---|---|
| `sparql_sql_schema.py::_build_tsv_concat_expr` | → `tsvector_expr(langs, "COALESCE(NEW.search_text, '')", "\n         || ")` (same joiner, so non-cjk DDL is unchanged) |
| `sparql_sql_schema.py::build_tsv_batch_expr` | → `tsvector_expr(langs, f"COALESCE({text_col}, '')")` |
| `vg_functions.py::_build_tsquery_expr` | → thin wrapper over `tsquery_expr(langs, f"'{safe_text}'")`. Keeps its docstring. Covers `text_search_sql`, `text_top_k_driving_sql`, the match-only EXISTS, the hybrid, and `filter_pushdown._fts_index_and_query`. |
| `fast_fts_frame.py::_resolve_index` | returns `(table, languages)`, not `(table, cfg)` (live defect 1) |
| `fast_fts_frame.py::_build`, `_match_set_is_small` | `tsquery_expr(languages, text_param)`. Reusing `$n` inside the COALESCE is fine with asyncpg, and its type is inferred as `text` from both functions. |
| `vitalgraphsearchutil_cmd.py:719` | `tsquery_expr(languages, "$1")`, replacing its own copy |
| `model/fts_index_model.py` | description lists `cjk`; no regex on the model, so validation stays in one place (§3) |

`sparql_sql_schema.py` and `vg_functions.py` must not import each other for
this. Both import `fts_languages`.

### 5. Re-indexing an existing index — `update_fts_languages`

Today it updates the registry, replaces the trigger function and then runs ONE
`UPDATE {table} SET tsv = …` over the whole table, in no transaction. That
single statement is what production's 60 s `statement_timeout` kills
(`issues/136`). Changed to:
- validate (§3)
- registry UPDATE and `CREATE OR REPLACE` of the trigger function in ONE
  transaction, so new writes and the registry can never disagree
- refresh in keyset batches over the primary key
  (`(subject_uuid, context_uuid) > last ORDER BY … LIMIT 5000`), each batch its
  own statement and transaction, with progress logged. 5,000 rows is about
  0.2 s of `cjk` CPU (measured below) plus the write.

While a refresh is running, a query sees a mix of old and new rows. Adding a
language only adds lexemes, so results grow monotonically toward the final
state, and removing one shrinks them the same way. Neither shows a wrong row,
only a not-yet-found one.

The endpoint is synchronous, and a large message table outlives a caller's
30 s timeout, though the server keeps going. For large spaces the documented
path is `PUT /languages` with `refresh_tsv=false` (registry and trigger only,
instant), then a NEW operator command, `refresh-fts -s SPACE --index N
[--batch-size B]` in `vitalgraphsearchutil` (beside `populate-fts`). It calls
the same batched function and can be resumed, because a batch is idempotent.

### 6. What does not change

- Generated SQL and DDL for every index without `cjk` are byte-identical. A
  unit test pins this, so recorded plans and baselines stay comparable.
- Existing indexes are untouched until someone adds `cjk` to their languages.
- `rank_normalization`, the fast-path gates, `FTS_CANDIDATE_CAP` and the top-K
  hint are unchanged.

## Measured cost

Synthetic data: 100,000 rows of 40 random CJK characters with ~8% full-width
commas. Local PG 18.4, no swap pressure, 5 runs each:

| | min | median | max | per row |
|---|---|---|---|---|
| `to_tsvector('english', t)` | 133 ms | 134 ms | 147 ms | 1.3 µs |
| `vitalgraph_cjk_tsvector(t)` | 3,773 ms | 3,815 ms | 3,913 ms | 38 µs |

About 28x the English stemmer, and negligible per write (0.04 ms in the
trigger). For a re-index, 321k rows (the size of the measured production
message index) is about 12 s of function CPU, hence the batching. Lexemes per
row: 69.6 (≈ 39 bigrams + 40 unigrams, minus repeats), 909 bytes per tsvector.

An earlier set-returning-subquery version cost 120 µs per row. Keep the
plpgsql loop form.

GIN size and write amplification on real data are NOT measured yet (Tests §4).

## Tests

**1. Unit** — `tests/unit/test_fts_languages.py`:
- `tsvector_expr` and `tsquery_expr` for `[english]`, `[english, spanish]`,
  `[english, cjk]` and `[cjk]`
- byte-identical output against today's builders for every non-cjk list
- `LANGUAGE_NAME` refuses `english'::regconfig, …); DROP …`
- `validate_fts_languages` with a fake conn: unknown name, duplicate, empty,
  `cjk` without the functions

**2. SQL functions against real PostgreSQL** —
`test_scripts/search/test_cjk_sql_functions.py`, beside
`test_tsquery_parser.py`. Run once on the vg test stack (`en_US.utf8`) and once
on a C-locale database; both were checked by hand and agree. Cases:
- Traditional, Simplified, and that the two do NOT cross-match (pinned, so a
  future fold is a deliberate change)
- kana and kanji mixed
- single character
- full-width punctuation boundaries
- `ｶﾀｶﾅ` and `ＡＢＣ`, a compatibility ideograph, an Extension B character
- NULL, empty and Latin-only, each giving an empty tsvector or a NULL tsquery
- quoted phrase; a phrase spanning a punctuation boundary (`"樓梯海邊"`, no
  hit)
- negation of a word and of a phrase; negation-only giving NULL
- injection characters
- `pg_proc` showing IMMUTABLE and PARALLEL SAFE on all four functions

**3. Integration on the vg test stack** (rebuilt for this code, through the
API, port 8002):
- **Validation through the API:**
  - an unknown language → `INVALID_REQUEST`, no registry row, no table
  - `cjk` without the functions → `INVALID_REQUEST` naming the script
  - `cjk` with them → `CREATED`
- **Search paths:** create `['english','cjk']`, write zh-Hant, zh-Hans,
  Japanese, mixed and English messages through the normal write path
  (auto-sync, so the trigger runs), then search each through:
  - `vg:textSearch`
  - the hybrid
  - KGQuery FTS with the fast path forced ON, then forced OFF

  The two KGQuery runs must return the same set, with pages partitioning it.
  Compare bindings, not SQL rows.
- **Live defect 1:** a Spanish-only hit on an `['english','spanish']` index,
  found by both paths.
- **`cjk`-only index with a Latin query:** 0 rows, no error, on every path.
- **Language update:** `PUT /languages` adding `cjk` to a populated index,
  with refresh, then search. Interrupt the operator refresh mid-way, re-run it,
  and check the final tsv equals a fresh build.

**4. Scale and cost** (vg test stack at prod scale, quiet DB, 5x per cell,
min/med/max). There is no production Chinese corpus, so use vital-saas-memory's
zh-Hant recall questions against their messages, plus synthetic zh-Hant filler,
to ~320k rows. Measure:
- matches per recall question, and page latency on both KGQuery paths
- recall@k against the expected messages (the request's own success
  criterion)
- GIN size with and without `cjk`
- trigger cost per write
- batched-refresh throughput

If common-pair questions match a large share of the space at an unacceptable
latency, D2's escalation (stop-pairs, or ≥2 matching pairs) is decided on those
numbers.

## Rollout

1. vitalgraph release carrying §1-§6.
2. Per install, pre-deploy: `scripts/install_sql_functions.py`, dry run, then
   `--apply` as the app role. Read its census of invalid stored languages.
3. Deploy the server. Until this point a `cjk` request is refused; it is never
   silently accepted.
4. vital-saas-memory adds `cjk` to `FTS_LANGUAGES`, ONLY after step 3 on that
   install. For existing spaces: `PUT /languages` with `refresh_tsv=false`, then
   the operator refresh.
5. Re-run the zh-Hant recall set. The reorder workaround stays as a fallback
   until the numbers say otherwise.

Rollback: `PUT /languages` without `cjk`, then refresh. The functions can stay
installed.

## Follow-ups (not in this change)

- **Traditional ↔ Simplified folding.** For one-to-one variants,
  `translate(t, '<traditional>', '<simplified>')` inside `vitalgraph_cjk_runs`
  would be immutable and cheap. Many-to-one (後/后, 髮/發 → 发) is safe in the
  T→S direction. Decide from the recall test whether cross-variant questions
  occur at all. Folding changes the index, so it is a re-index.
- **NFKC for the stemmer arms** (D8): makes `ＡＢＣ` match `ABC`; a re-index of
  every FTS index everywhere.
- **Strip CJK runs before the stemmer arms**, to remove the dead per-run
  lexeme and make D7's mixed queries behave as AND-of-scripts.
- **`fts_populator`'s full-population `UPDATE … WHERE tsv IS NULL`** is the
  same unbatched single statement as §5 and has the same timeout exposure.
  Already true for every language.

## Estimate

The request's "about a day" covers §1 and §2. In full:

| Part | Days |
|---|---|
| §1 functions + install script | 0.5 |
| §2 builders and §4 call sites | 0.5 |
| §3 validation (with live defect 2) | 0.5 |
| Live defect 1 (fast path) | 0.5 |
| §5 batched refresh + `refresh-fts` | 0.5 |
| Tests §1-§3 | 1 |
| Tests §4 measurement | 0.5–1 |
| **Total** | **≈ 4–4.5** |

Live defects 1 and 2 are worth doing first, on their own, whatever is decided
here.
