# 235 — The lead fixture writes two terms no writer in the system can produce

## Status: BOTH FIXED IN THE GENERATOR 2026-09-24 — existing fixture data and
## every space loaded from it still carry them until regenerated and reloaded.

Found while attributing the one rewrite `issues/234` could not close. Two
defects, same generator, same shape: a fixture built to imitate production emits
a term production cannot emit. Neither breaks a bench — which is why both
survived.

**Related:** `issues/234` (found them; the round trip is the detector),
`issues/042` (the CSV converter that loads this fixture — a different datatype
defect on the same path, and the first, wrong suspect), `issues/036` (the silent
predicate drop that defect 2 walks into), `issues/171` (why the grouping URIs
are in the fixture at all)

## The dataset IS this generator's output — established, not assumed

`sp_lead_types` (`/tmp/rt2.nq`, 1,483,310 quads) was the measurement subject, so
its provenance had to be proved rather than inferred from the `SYN` prefix:

| | `sp_lead_types` | `generate_lead_dataset.py --entities 2000 --trim` |
|---|---|---|
| triples per entity | 741.655 | 741.66 |
| `xsd:decimal` per entity | 1.55 (3,100 / 2,000) | 1.55 (155 / 100) |
| `hasFrameGraphURI` | 207,080 | present, same construction |
| subject ids | `urn:acme:lead:SYN%09d` | `:625`, `SYN{i:09d}` |

Both ratios match to five significant figures. The template data the generator
clones — `internal_data/lead_test_data`, 100 REAL lead graphs — contains
**zero** `xsd:decimal` and **zero** `hasFrameGraphURI`, so both terms are added
by the generator and by nothing else.

## Defect 1 — two currency slots are resampled into `xsd:decimal`

The generator resamples a handful of slots so their selectivity is known in
closed form, under a stated rule:

> Every other slot value is copied verbatim — the fixture stays as close to the
> real data as possible except where selectivity control demands otherwise.

Selectivity demands a different DISTRIBUTION. It does not demand a different
DATATYPE, and one slot family got one anyway:

| resampled slot | real data | generator wrote | |
|---|---|---|---|
| `mqlrating` | `xsd:float` (100) | float | match |
| `mqlratingpoints` | `xsd:integer` (100) | integer | match |
| `leadstatus` | `xsd:string` (100) | string | match |
| `companystatecode` | `xsd:string` (100) | string | match |
| `mqlv2` | `xsd:boolean` (100) | boolean | match |
| **`monthlygrosssales`** | **`xsd:float`** | **decimal** | **DIFFERS** |
| **`verifiedrevenue`** | **`xsd:float`** | **decimal** | **DIFFERS** |

Five of seven agreed. The two that did not are the two sharing a predicate
(`hasCurrencySlotValue` — all 155 template quads for it are `xsd:float`), and
the comment above that line is about the log-normal draw, saying nothing about
the type. An oversight, not a decision.

`hasCurrencySlotValue` is a `DoubleProperty`, and every VitalSigns property
serialises through `IProperty.to_rdf`, which maps a Python float to
**`xsd:float`** (no subclass overrides it). `DoubleProperty.__init__` is
`float(value)`, so the object API cannot write `xsd:decimal` here even in
principle — and production agrees: `prod_kg`'s currency slots are `xsd:float`
(`issues/234`'s 259,531-quad sample found no decimals at all).

The lexical form diverged too: `f"{v:.2f}"` produces `"8778.90"`, where the
template's floats are plain `str(float)` output — `"43503.0"`. Nothing else in
the system emits that trailing zero.

**Fixed:** `lit(str(v), "float")`, and the manifest's `distributions` block now
documents the currency slots, which it had omitted entirely.

## Defect 2 — the entity→frame edge is stamped with `hasFrameGraphURI`

`nurture_triples` put `{entity}:edge:entity_to_nurtureinfoframe_0` in its
`frame_objects` list, so the edge got BOTH grouping URIs. That edge ATTACHES the
frame; it does not live inside it. Three things say so:

  * **`Edge_hasEntityKGFrame` has no such property.** Setting it raises
    `AttributeError: 'Edge_hasEntityKGFrame' object has no attribute
    'frameGraphURI'` — checked directly, against `Edge_hasKGSlot`, which accepts
    it. So no write path can produce the quad, and an object round trip drops it
    without a word (`issues/036`).
  * **The query layer relies on its absence.** `kg_sparql_utils.py:682`:
    *"Only include edges that have frameGraphURI (excludes
    Edge_hasEntityKGFrame)."* Stamping it made fixture spaces answer a
    frame-graph read with one extra subject that production would never return.
  * **The generator's own other frames were already right.** Their entity edges
    are stamped by the URI-shape pass, which only matches subjects containing
    `:frame:` — and `…:edge:entity_to_leadstatusframe_0` does not. Only the
    hand-written nurture frame had the explicit list, and only it was wrong.

One quad per entity: 100 in a 100-entity fixture, ~2,000 in `sp_lead_types`.

**Fixed:** the edge now takes `hasKGGraphURI` only, which `Edge_hasEntityKGFrame`
does accept.

## Verified

Regenerated at 100 entities `--trim` and put through the whole round trip:

    before        74,166 quads   155 datatype rewrites   100 dropped
    after         74,066 quads     0 datatype rewrites     0 dropped

Byte-exact, and the selectivity manifest is unchanged — `MQLRating >= t` still
reads `0→100, 50→50, 65→37, 90→13`, and triples-per-entity is unchanged except
for the 100 removed quads. **No bench moves.** No test asserts on the currency
slots at all; they are generated, counted in the manifest, and unused by any
criterion, which is the other half of why this was invisible.

## What this does NOT invalidate

`xsd:decimal` and `xsd:float` are both in `_NUMERIC_DATATYPES`
(`emit_bgp.py:28-35`), and `num_val` is a NUMERIC generated column, so the range
push-down and its partial index treated the two identically. Nothing measured on
this fixture is wrong BECAUSE of defect 1.

What it cost is narrower and worth stating plainly: **the fixture answered a
datatype question, and a frame-membership question, differently from
production** — on the one path where anyone would trust it to answer the same.
`issues/234`'s verification round trip reported 174 rewrites and 112 drops that
had nothing to do with the code under test, and the same round trip over the
real template data showed zero across all 192,810 quads.

## STILL TO DO

  * **Regenerate the fixtures and reload the spaces.** The generator is fixed;
    the already-generated `.nt` shards and every space loaded from them keep
    both terms. Same shape as `issues/042`: fixed in the converter, existing
    data needs rebuilding.
  * Regenerating changes term uuids for the currency slots, so an existing
    fixture space and a fresh one are no longer comparable. Any recorded uuid
    against the old data is stale.
  * Decide whether `sp_lead_types` and the other fixture-loaded spaces are
    still in use and worth regenerating, or should be dropped when the range
    work finishes.

## Not established

  * Whether the `207,080` `hasFrameGraphURI` quads are otherwise correct. Only
    the entity→frame edge was checked against the object model; the frame, slot
    and slot-edge stamps all land on classes that accept the property, but no
    per-class sweep was done.
  * Whether any OTHER fixture generator in `scripts/` or `internal_data/` makes
    the same kind of substitution. Only this one was examined, because only this
    one produced the term `issues/234` tripped over.
