# The Semi-Join Marks A Join And Disables `selective-driven`, Costing 20,000x

## Status: FIXED 2026-09-01 — two call sites truncated a term identity, so the
## gate could not see the selective leaf and probed instead of joining:
## **2.7 ms -> 54,949 ms** on the same query with the same bound value.
## Fix verified against production. The FIRST diagnosis in this file was wrong
## and is retracted at the end.

## How this was measured

Production is built from a separate repo (`issues/137`), so the deployed tree
was extracted at the deployed commit and used as an import path. Both generators
were then run **on the same SPARQL, taken verbatim from production logs, with the
same bound values, against the same live database**, and the resulting SQL was
`EXPLAIN (ANALYZE, BUFFERS)`-ed. The only variable is the generator.

Both shapes are real: `kg_query_builder` output logged by the running service.

## The result

| shape | deployed | `main` | |
|---|---|---|---|
| one frame, one slot (`CtRefSFLeadId`), selective value | **2.720 ms** | **54,949 ms** | **~20,000x worse** |
| two frames, two slots — the 24,340-call statement | 133,783 ms | **>240,000 ms** (hit the fence) | >1.8x worse |

Buffers tell the same story without any timing noise:

    one frame   deployed   shared hit=47         read=6
                main       shared hit=1,688,203  read=62,067

    two frames  deployed   shared hit=12,998,472 read=82,025
                main       did not complete

`LIMIT` is identical in both generated statements (10 and 1 respectively), both
return the same single row, and the deployed plan touches 53 buffers total — so
this is not a caching artefact.

## The mechanism, from the generator's own log

    semijoin gate: resolved 5/5 pair stats (0 counted), 0 range(s), 0 text(s)
    semijoin: split BGP on ?entity — anchor ['q0'], probe ['mv0','mv1','q1','q4','q5','q8','q9']
    semijoin selectivity: 10/10 = 1.000 -> probe
    semijoin: marked 1 join(s) (1 split BGP, 0 reverted)
    selective-driven declined: semijoin marked and not text-driven

The last line is the defect. **The semi-join firing switches OFF
`selective-driven`** — and `selective-driven` is precisely what makes the
deployed plan fast. The two optimisations both exist in `main`, they are mutually
exclusive, and the wrong one wins.

What each does on this query:

* **`selective-driven` (deployed behaviour)** — drives from the slot value. An
  `SFLeadId` / `CtRefSFLeadId` is a near-unique key, so this starts at one row
  and walks up four edge hops to the entity. 53 buffers, 2.7 ms.
* **semi-join (`main` behaviour)** — anchors on `q0`, the entity-type predicate,
  and probes. `q0` is `hasKGEntityType = NurtureAction`:

      Bitmap Heap Scan on prod_kg_rdf_quad q0   (actual rows=76,254)
        ->  Nested Loop  (actual rows=0.00 loops=76254)

  It enumerates **every NurtureAction entity in the graph** and runs the EXISTS
  probe once per entity, 76,254 times, each returning nothing.

The estimate actually gets *more honest* under `main` — `rows=39,098` at the top
instead of the `rows=1` the deployed plan carries — and the plan gets far worse.
That is `issues/119` §9 exactly ("the good plan depends on an estimate being
wrong in a specific direction"), now reproduced on production data at a magnitude
far beyond the 20-93x recorded there.

## Why the gate did not stop it — the actual cause

`constants` has been keyed on the FULL term identity `(text, type, lang,
datatype)` since `a2b623a`. `leaf_terms` carries that same 4-tuple:

    leaf_terms[q9,object_uuid] = ('00QUg...', 'L', None,
                                  'http://www.w3.org/2001/XMLSchema#string')

Two call sites threw half of it away:

    for (alias, col), _t in (bgp.leaf_terms or {}).items():
        text, ttype = _t[0], _t[1]          # <-- drops lang and datatype
        ...
        by_alias.setdefault(alias, {})["p"] = (text, ttype)

`_term_uuid` then looks up `('00QUg...', 'L', None, None)` against a map holding
`('00QUg...', 'L', None, 'xsd:string')`, and misses. Confirmed live:

    UNRESOLVED constant: text='00QUg00000mPfkIMAS' type='L'
    LOOKUP KEY : ('00QUg00000mPfkIMAS', 'L', None, None)
    CONSTANTS  : ('00QUg00000mPfkIMAS', 'L', None, 'http://www.w3.org/2001/XMLSchema#string')

The two sites are `_leaf_rows` and `needed_pairs`, and each miss compounds:

* **`needed_pairs`** builds the set of pairs the generator counts on demand. The
  literal is not in it, so the on-demand count never runs —
  `semijoin gate: resolved 5/5 pair stats (0 counted)`.
* **`_leaf_rows`** wants the SMALLEST constant leaf. The 1-row literal is
  invisible, so it silently returns the next smallest RESOLVABLE leaf — the
  entity type, 76,328 — for the probe side. The anchor resolves to the same
  leaf. Hence `76,328/76,328 = 1.000 -> probe`.

**The `if not matches or not candidates: return False` guard cannot fire**, which
is the sharp part. The function did not fail to get a number; it got a
confidently wrong one. Absence of the selective leaf is indistinguishable from
its not existing.

This is `a2b623a`'s own bug class — "it broke as lookups that return None, and
every consumer reads None as unmeasured" — except here the consumer does not
read None at all. It reads a different leaf.

## The fix

Keep the full identity at both sites:

    -        text, ttype = _t[0], _t[1]
             if col == "predicate_uuid":
    -            by_alias.setdefault(alias, {})["p"] = (text, ttype)
    +            by_alias.setdefault(alias, {})["p"] = _t

Verified end to end against production, same SPARQL and bound value:

    before fix, prod stats     76,328/76,328 = 1.000 -> probe    54,949 ms
    after  fix, prod stats          1/8      = 0.125 -> probe    (still wrong: see 139)
    after  fix, correct stats       1/76,335 = 0.000 -> join          0.562 ms

The middle line matters and is why this issue alone is not sufficient. With the
identity fixed the NUMERATOR is right — the gate finds the 1-row literal — but
the DENOMINATOR comes from `{space}_rdf_stats`, which on production says **8**
for a pair whose true count is 76,323. That is `issues/139`.

Full `tests/unit` passes with the change (2 pre-existing skips).

### Two things the first cut of the fix got wrong

**The fix has a second half.** Making typed literals resolve changes the KEY
SPACE of `generator._pair_count_cache`, which was a plain unbounded dict. While
only URI constants resolved its object side was entity/frame/slot TYPES — a
small fixed set per space. Typed literals make it one entry per distinct slot
value ever queried, and the hot production shape is a per-lead-id lookup: 24,340
distinct ids in 33.5 days, growing. That is an unbounded cache in a long-lived
process, and the module already has `_LRUCache` guarding `_term_cache` against
exactly this ("could otherwise push it to tens of GB and OOM the process").
`_pair_count_cache` is now `_LRUCache(50_000)`.

**The two call sites are now one.** They were fixed independently with the same
comment copied twice, which leaves a third site free to reintroduce the
truncation — the argument `_checked_query` already makes about checking at 28
call sites. Both now consume `semijoin._constant_pairs(bgp)`, a single producer
that yields full identities.

### Residual risk, not eliminated

`_leaf_rows` has three callers outside the gate — `emit_slice.py:611`, `:624`,
`:714`, serving `selective-driven`. They now see smaller, more accurate counts
for typed literals, which is the intended direction, but no test specifically
exercises those paths at a changed value. Unit tests pass; that is not the same
thing.

The sibling instance at `traversal_chain.py:190` has now been CHECKED and is
**not** a defect — a `p_type != "U" or o_type != "U"` guard two lines above means
only plain URIs reach the two-argument call, and those have no lang or datatype
to lose. But the comments there still assert `leaf_terms` is a 2-tuple, the same
false belief that caused this issue, and the guard it justifies now costs a
missed optimisation on exactly the production hot shape. Written up at the end of
`issues/135`.

## What this means for the deploy — REVISED

`main` carries real, verified fixes for production defects — `_checked_query`
(a failed read currently returns `200` + `0 results`), the 55s read fence, and
the bulk-insert raise. Those are all in `issues/136` and all still worth having.

**They cannot ship with the current generator.** Trading a 2.7 ms lookup for a
54,949 ms one across the dominant read path would take a P1 and make it an
outage, and the correctness fixes would not be visible underneath it.

Disabling the semi-join was considered and rejected — it treats the symptom and
leaves the gate blind to every typed literal. The identity fix above is the
actual repair and is landed.

It is NOT sufficient on its own. `issues/139` must land with it, because the
gate's denominator is read from a stats table that production has in a corrupt
state. Fix order does not matter; both are required.

## What is NOT claimed

One bound value per shape was measured. Query cost here is strongly
value-dependent — a `NurtureCampaignURI` matching ~35k rows is a different
regime from an `SFLeadId` matching one, and the semi-join is expected to HELP
the former (that is what it was built for). The claim is narrower and
sufficient: **for the selective-value shape that dominates production traffic,
`main` is catastrophically slower**, and nothing in the pipeline currently
distinguishes the two regimes.

The two-frame number for `main` is a lower bound — it hit a 240s fence rather
than completing.

## Retraction — the first diagnosis in this file was wrong

Originally this file said the gate "is not mis-tuned by a threshold, it is
measuring the wrong quantity", reading `10/10 = 1.000` as "page size over
itself". **Wrong.** `10` was a real `row_count` from a corrupt stats table, on
both sides, because the selective leaf was invisible. The gate measures exactly
the right quantity; it was handed a truncated key and a corrupt table.

The proposed remedy that followed from it — disable the semi-join, or rewrite
the gate's arithmetic — would have left both real defects in place. Recorded
because the wrong reading is the one the log invites: `10/10` genuinely does
look like a hardcoded page size.

## Related

- `issues/119` §9 — measured that correcting this estimate flips to a 20-93x
  worse plan and concluded "do not fix the estimate". This is that prediction
  coming true on production data.
- `issues/090` — a criterion that SHRINKS a traversal makes it hundreds of times
  slower. Same family, opposite direction: here a criterion that shrinks the
  traversal is being ignored in favour of a scan.
- `issues/096` — records the semi-join being structurally unavailable to a SORT.
- `issues/136` — the correctness fixes this issue blocks.
