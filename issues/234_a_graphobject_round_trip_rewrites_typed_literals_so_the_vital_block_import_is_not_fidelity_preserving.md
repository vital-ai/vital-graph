# 234 — A GraphObject round trip rewrites typed literals, so the vital-block import is not fidelity-preserving

## Status: BOTH MEASURED REWRITES FIXED 2026-09-24, in the encoder. NOT CLOSED:
## a literal whose stored datatype disagrees with its property is still
## rewritten, and the block import is still not term-exact. See "After the fix".

Found by measurement on a 259,531-quad sample of local `prod_kg`: nothing
dropped, no value changed, and 3.9% of quads came back as a DIFFERENT TERM.

**Related:** `issues/221` (every `ExportEngine` format dropped `^^<datatype>` —
the same loss, on the export side, FIXED, and its `xsd:string` decision is
contradicted here), `issues/235` (the fixture that produced every difference
this fix does not close — both now fixed in the generator, existing fixture data
still carries them), `issues/042` (CSV import drops datatypes), `issues/126`
(positional datatype ids), `issues/157` (why the datatype must be resolved
before a term is hashed), `issues/036` (predicates silently dropped by the same
conversion)

## The measurement

Found while planning a whole-space rebuild (message-ordinal backfill:
export → per-entity blocks → parallel transform → import into a blank space),
which needed the round trip to be exact and turned out not to be.

Local `prod_kg`, 5,212,669 quads, exported with `export_space_to_nquads` in
62 s inside one `REPEATABLE READ READ ONLY` snapshot — so prod's ~50M is about
10 minutes, and the export is not the problem. A deterministic 5% sample of
SUBJECTS (259,531 quads) was then put through
`quad_list_to_graphobjects` → `graphobjects_to_quad_list`:

| | quads |
|---|---|
| dropped predicates | **0** |
| lexical value changes | **0** |
| `"…"^^xsd:string` → plain `"…"` (text / JSON / choice slot values, `hasName`) | 9,603 |
| `xsd:float` → `xsd:double` (currency / double slot values) | 497 |
| **total rewritten** | **10,100 (3.9%)** |

Both rewrites are value-equivalent in RDF 1.1. Neither is the same TERM.
`_term_uuid` hashes the `datatype_id` into the uuid
(`endpoint/impl/data_import_impl.py:56-64`), so a rewritten datatype is a
different `term` row, a different `rdf_quad` row, and a different checksum.

## Why it matters, in the two ways it bites

1. **Routing a whole space through vital blocks rewrites it.**
   `import_vital_block_incremental` builds its quads from `block.objects`
   (`data_import_impl.py:1321`), so every quad it writes is the CONVERTER's
   idea of that quad, not the source's. At the measured rate that is roughly
   2M rewritten quads on a 50M-quad production space — a rebuild that was
   supposed to touch 325k message frames instead differs from its source
   everywhere.

2. **It defeats the verification of any such rebuild.** Per-entity
   `(count, bit_xor)` over source versus new is the cheapest way to prove a
   transform touched only what it claimed to. With a 3.9% rewrite rate, every
   entity nobody touched disagrees too, and the check tells you nothing.

The rest of the import path is NOT at fault: it resolves datatype ids before
hashing and carries `o_dt` into the term row (`data_import_impl.py:1324-1334`).
It writes faithfully whatever the converter hands it.

## The mechanism

The property-map representation is Python natives, and a Python native does not
carry an RDF datatype. So the loss is on the way IN, and the way OUT re-derives
a datatype from the PYTHON TYPE rather than from the ontology.

**Inbound** (`quad_format_utils.py:532-554`, `_convert_typed_literal`):

  * `xsd:string` falls through to `return value_str` — a plain `str`,
    indistinguishable from what a plain literal produces;
  * `float`, `double` AND `decimal` all become Python `float`;
  * the integer family (`int`, `long`, `short`, `unsignedInt`, …) all become
    Python `int`;
  * `dateTime` becomes a `datetime`.

**Outbound** (`quad_format_utils.py:235-255`, `_value_to_nquads_outbound`) has
one arm per Python type:

  * `str` → `"…"`, never `^^<xsd:string>`;
  * `float` → `^^<xsd:double>`;
  * `int` → `^^<xsd:integer>`;
  * `datetime` → `value.isoformat()` `^^<xsd:dateTime>`.

So the two observed rewrites are exactly the two round trips through that pair.
Three more follow from the same code and were NOT exercised by this sample —
read from the source, not measured:

  * **`xsd:decimal` → `xsd:double`.** This one is not merely a different term:
    it is a lossy numeric conversion. A decimal that does not fit a binary
    double comes back with a different VALUE. The sample contained none;
    `issues/221`'s round trip counted 3,100 `xsd:decimal` quads in
    `sp_lead_types`, so they exist in production spaces.
  * **`xsd:long` / `xsd:int` / the rest of the integer family → `xsd:integer`.**
  * **`"x"@en` → `"x"` on any non-annotation predicate.**
    `_quad_list_to_graphobjects_fast:585` unwraps the language dict for
    anything `is_annotation_property` says no to, because domain properties do
    not support language tags. The tag is then gone, and the outbound `str` arm
    emits a plain literal.

### The datatype is NOT lost by the object model — VitalSigns' own serializer keeps it

This is the part that decides how big the fix is, so it was checked rather than
assumed. Given the SAME GraphObjects, the two serializers disagree:

    IN  : "Alice"^^<xsd:string>          IN  : "12.5"^^<xsd:float>
    OUT : "Alice"                        OUT : "12.5"^^<xsd:double>
      (quads -> quad_list_to_graphobjects -> graphobjects_to_quad_list)

    GraphObject.to_triples_list on those same objects:
      Literal('Alice', datatype=xsd:string)
      Literal('12.5',  datatype=xsd:float)

`to_triples_list` consults the ontology — `hasName` is a `StringProperty`,
`hasCurrencySlotValue` a `FloatProperty` — and emits exactly what the store
holds. So the datatype survives the object; it is thrown away only by
`quad_format_utils`' own encoder, which asks Python what type the value is
instead of asking the ontology what type the PROPERTY is. It already asks the
ontology one question in that very function — `_is_uri_property`
(`:215-233`), cached per property URI. The datatype is the second question,
answered the same way.

### The rdflib fallback elides `xsd:string` on purpose, which contradicts 221

`rdflib_term_to_nquads:54` writes `^^<datatype>` only when the datatype is not
`xsd:string`. `issues/221` decided the opposite for `ExportEngine` — emit
`xsd:string` explicitly, to agree with `bulk_export._nt_term_sql` — and
recorded the reason: *"two exporters disagreeing about the same quad is
precisely how this bug hid."* That is a third opinion about the same quad,
living in the module the whole object API shares.

## Where this reaches, and where it does not

Traced, because the first guess — that the object API writes converter quads and
so every space is quietly drifting — is WRONG, and worth recording as wrong.

**Storage writes are faithful.** Every path that inserts goes through
`GraphObject.to_triples_list` / `to_triples` and hands the backend rdflib
`Literal`s with their datatypes intact: `kgentity_update_impl.py:277`,
`kgentity_frame_create_impl.py:451,700`, `kgframe_create_impl.py:405`,
`kgtypes_create_impl.py:173`, `kgtypes_update_impl.py:309`,
`kgframes_endpoint.py:2622,3312,3421`, `kgdocuments_endpoint.py:910,1533`,
`kg_backend_utils.py:830,1378`. `kgentity_update_impl.py:279-281` says so
explicitly: *"Keep RDFLib objects (especially Literal with datatype/language) so
downstream formatters can preserve type information."*

An entity update is delete-all-subjects + insert (`kg_backend_utils.py:1442`),
so it re-mints every literal on the entity, including unmodified ones — but it
re-mints them from the ontology, so they come back identical. **Spaces are not
drifting through the API.**

**Two places do use the lossy encoder:**

1. **The block import** (`data_import_impl.py:1321`) — the only path that writes
   converter output to STORAGE. This is the defect.
2. **API responses.** `graphobjects_to_quad_list` builds the quad payloads —
   `kgentities_endpoint` (`:528,773,854,1505`), `kgframes_endpoint`
   (`:364,537,917,1036,1128,1372,3113`), `kgtypes_endpoint`,
   `kgdocuments_endpoint`, `files_endpoint`,
   `utils/format_adapter.py:115,156,164`. So a client reading an entity as quads
   is shown plain literals and `xsd:double` where the store holds `xsd:string`
   and `xsd:float`. That is self-healing on write-back (the write re-derives from
   the ontology), but it means **the API's quads cannot be compared against the
   store, against a `bulk_export` dump, or against `ExportEngine` output** — and
   after `issues/221` those other two agree with each other and with the store.
   Anyone checksumming a space through the API is checksumming a third form.

## After the fix — what was changed, and what a real export still shows

**Done (option 1 below), 2026-09-24:**

  * `_value_to_nquads_outbound` (`quad_format_utils.py`) now asks
    `get_rdf_datatype` — the SAME classmethod `IProperty.to_rdf` uses to write
    the store — instead of inferring from the Python type. The property class is
    resolved through the ontology manager and cached per property URI, reusing
    the lookup `_is_uri_property` already did.
  * `rdflib_term_to_nquads` no longer elides `^^<xsd:string>`, which is what
    `issues/221` decided for the exporters. A literal with NO datatype — an
    annotation, which `add_to_list_impl` builds as a bare `Literal(str(av))` —
    still comes out plain, because that is what the store holds for those.
  * `import_vital_block_incremental`'s docstring now states the fidelity
    contract instead of describing the conversion as a performance choice.
  * `tests/unit/test_quad_roundtrip_preserves_datatypes.py` — asserts TERM
    equality across the round trip. 18 tests; 9 of them fail against the old
    encoder, and the 9 that do not are the URI, annotation, language-tag,
    integer and boolean cases, which were never broken.

**VERIFIED BY ROUND TRIP ON A REAL EXPORT, not by reading the code.** A
deterministic 5% subject sample of `sp_lead_types` (`/tmp/rt2.nq`, the
1,483,310-quad export `issues/221` left behind — chosen because it contains
3,100 `xsd:decimal` quads, the case the `prod_kg` sample did not exercise):

    sample                10,602 subjects, 73,830 quads (5.0%)
    unchanged             73,544
    datatype rewrites        152   all xsd:decimal -> xsd:float
    lexical changes            0
    dropped                  134   112 issue-036, 22 the decimal case again
    added                     22   the other side of those 22

`xsd:string` → plain and `xsd:float` → `xsd:double` are **gone: zero of each.**

**The 174 that remain are all one thing, and it is a property of the FIXTURE,
not of the data model.** `hasCurrencySlotValue` is a `DoubleProperty`, which
serialises a Python float as `xsd:float` — so those `xsd:decimal` values were
written by something that is not the object API. Traced: `issues/235`, the lead
fixture generator, which resamples two currency slots as `xsd:decimal` where the
real lead data it clones uses `xsd:float`. **Production data does not have this
shape**, which is why the `prod_kg` sample found no decimals at all.

22 of the 174 also change lexically (`"8778.90"` → `"8778.9"`), because the value
passes through a Python float. **Neither can be fixed in the encoder**:
`DoubleProperty`'s constructor is `float(value)` (`DoubleProperty.py:5-7`), so
the decimal is gone before anything is asked to serialise it. A GraphObject
cannot carry it.

**On real data the round trip is now exact.** The 100 lead entity graphs in
`internal_data/lead_test_data` — the real records the fixture is cloned FROM —
were run through it whole, not sampled:

    192,810 quads    unchanged 192,810    rewritten 0    dropped 0    added 0

**The other 112 are not this issue either.** They are `hasFrameGraphURI` quads on
`Edge_hasEntityKGFrame` subjects, dropped because the edge class does not accept
that property — `issues/036`. Also traced to the same fixture generator
(`issues/235`, defect 2) and also fixed there: no write path can produce that
quad, because setting the property raises `AttributeError`.

So the block import is better, and still not term-exact. The remaining exposure
is bounded and nameable: literals whose datatype disagrees with their property,
and predicates their class does not accept.

## What would fix it

Three options. (2) is the smallest, (1) the one that also fixes the responses,
(3) the only one that does not depend on the ontology being right:

1. **Ask the ontology for the datatype in `_value_to_nquads_outbound`**, the way
   the same function already asks it whether a property is a URI
   (`_is_uri_property:215`, cached per property URI). Needs no VitalSigns
   change, and makes the response encoder agree with `to_triples_list` — which
   is the only reason the two differed. **DONE.** It does NOT preserve a literal
   whose stored datatype disagrees with the ontology, which is what the 174
   remaining rewrites are.

2. **Or route the block import through `to_triples_list`** instead of
   `graphobjects_to_quad_list`, so the one path that writes converter output to
   storage uses the same serializer every other write already uses. Narrower
   than (1) — it leaves the API responses in their third form — but it is the
   smallest change that stops a rebuild rewriting a space. Made redundant by
   (1): the two serializers now agree, so this would change nothing.

3. **A raw-quad mode for blocks**, carrying source N-Quads terms through the
   block file so pass-through data is never converted at all. This is the only
   one that is exact by construction rather than by agreement, and it is what
   the backfill plan does at the level above instead of waiting for any of this:
   blocks hold quads, the transform is quad-level, and the import goes through
   `import_ntriples_incremental`. It works precisely because nothing
   round-trips.

(1) and (2) both leave a literal's fidelity depending on the ontology agreeing
with the data. **Only (3) does not, and the 174 surviving rewrites are exactly
that gap** — so (3) is still worth building if blocks are ever to carry a space
faithfully. The backfill this was found by does not wait for it: it works at
quad level and imports through the N-Quads path.

STILL TO DO, in rough order:

  * **(3), a raw-quad mode for blocks**, if the block format is to be trusted
    for a rebuild at all.
  * **Check whether any space already carries converter-written literals** from
    a past block import. The signature is `^^xsd:string` at or near zero where a
    natively-written space shows thousands. `issues/221` left the same sweep
    open for its own spaces.
  * **`issues/036`'s drops** remain the other way a round trip loses a quad,
    though the 112 this measurement found were the fixture's doing and are fixed
    in `issues/235`. A predicate the class does not accept is still dropped in
    silence for everyone else.

## Measured on PRODUCTION data — `prod_kg`, 2026-09-24

The fix above was verified on local fixtures and on `lead_test_data`. This is the
same round trip on a slice of the **production** space, with the fixed encoder.

**The slice.** Read-only SQL export from `vitalgraph-pg18-prod`, space `prod_kg`,
graph `urn:prod_kg`, inside one `REPEATABLE READ READ ONLY` snapshot
(`14582649:14582649:`). Rendered with `bulk_export._nt_term_sql`, so the lines are
byte-identical to `export_space_to_nquads`. Contents: the 4,756 NurtureActions with
a message frame dated 2026-09-01 → 09-07, each with its complete entity graph (the
entity plus every subject whose `hasKGGraphURI` is the entity), plus 303 controls
(100 each of `KGLead`, `KGBusiness`, `ExamplePerson`, and the 3 `KGCampaign`).
**2,801,296 quads, 398,978 subjects** — the whole slice, not sampled. Export and
scripts: `resource-rest/test_scripts/output/kg_ordinal_rehearsal/prod_sample_2026-09-01_07/`
and `test_scripts/kg_ordinal/export_prod_sample.py`.

**Round trip** (`quad_list_to_graphobjects` → `graphobjects_to_quad_list`, per
subject, fixed encoder from the working tree — `_value_to_nquads_outbound` calls
`get_rdf_datatype`; the released 0.0.42 still has the old encoder):

    quads in 2,801,296    out 2,801,296    rewritten 0    dropped 0    added 0    (29 s)

**Exact on production data.** The old encoder rewrote 3.9% of a local `prod_kg`
sample (the measurement at the top). The fixed one rewrites none of this slice.

**Why: every literal already carries its ontology datatype.** Literal census of the
same 2.8M quads:

| datatype | literals |
|---|---|
| `xsd:string` | 115,287 |
| `xsd:integer` | 56,844 |
| `xsd:dateTime` | 33,272 |
| `xsd:boolean` | 1,168 |
| `xsd:float` | 287 |
| plain (no datatype) | **0** |
| language-tagged | **0** |
| `xsd:decimal` | **0** |

What this answers, for this slice of prod `prod_kg`:

  * **It was written natively, not block-imported.** 115,287 `^^xsd:string` against
    0 plain literals is the natively-written signature this issue describes.
  * **It holds none of the gap the fix leaves open.** No literal's datatype
    disagrees with its property; there are no `xsd:decimal` values and no language
    tags. The 174 surviving rewrites in `sp_lead_types` are a fixture shape
    (`issues/235`), and production does not have it — consistent with
    `issues/235`'s own conclusion.
  * **No `issues/036` drops either.** 0 dropped predicates across 398,978 subjects.

Limits: this is a slice — 4,756 of ~85,300 NurtureActions and a 303-entity control
sample. That covers every entity type in the space (per `hasKGEntityType`:
`NurtureAction` 85,300, `KGLead` 1,254, `KGBusiness` 1,254, `ExamplePerson` 123,
`KGCampaign` 3) but not every entity. Prod has **no NurtureEvent entities at all**
(no type term, no `nurture_event` entity URIs), so those were not exercised; the
local graph has them.

**What the backfill does with this: nothing changes, deliberately.** It stays at
option (3) — quads in blocks, a quad-level transform, import through
`import_ntriples_incremental`. That is exact by construction, and does not depend on
this fix being deployed or on the remaining ~47M prod quads agreeing with the
ontology the way this slice does. Two operational consequences, recorded in
`resource-rest/planning/agent_reporting/kg_ordinal_backfill_plan.md` §4:

  * **Writing entities back through the API is safe on this data.** Storage writes
    re-derive datatypes through `to_triples_list`, and prod data already agrees with
    the ontology, so the quads written equal the source's. That is what the
    backfill's one-day replay relies on.
  * **Never verify through API responses until the fixed encoder is deployed.** The
    deployed server still serialises response quads in the third form (plain
    strings, `xsd:double`), which matches neither the store nor `bulk_export`. The
    backfill verifies from SQL exports only.

## Not established

  * Whether any deployed space already carries converter-canonical literals from
    a past block import, and how to tell — `issues/221` left the same open sweep
    (comparing `datatype_id` distributions against a known-good source). A space
    loaded entirely through `.vital` blocks would show `^^xsd:string` at or near
    zero where a natively-written one shows thousands. **PARTLY ANSWERED
    2026-09-24: prod `prod_kg` is natively written** — 115,287 `^^xsd:string` and
    0 plain literals in a 2.8M-quad slice (see "Measured on PRODUCTION data").
    Other deployed spaces, and a whole-space count on `prod_kg`, are still open.
  * Whether `xsd:decimal` → `float` has already changed a VALUE anywhere.
    ANSWERED IN PART: it is real and it is lexical — `"8778.90"` → `"8778.9"` on
    22 of 174 in the `sp_lead_types` sample. Whether it has ever lost PRECISION
    (a decimal too large or too fine for a binary double) was not checked, and a
    count-based check cannot see it.
  * Whether any portal or Resource API consumer compares API-returned quads
    against exported or stored ones. That comparison is broken today and the
    difference is value-equivalent, so it would show up as a checksum mismatch
    nobody can explain rather than as an error.
  * ~~Where the `xsd:decimal` currency values came from.~~ ANSWERED: the lead
    fixture generator, `issues/235`. Not `issues/042`'s CSV path, which writes
    NO datatype rather than a wrong one, and not any production writer.
  * Whether the ontology's answer is the RIGHT one for currency. A
    `DoubleProperty` serialising as `xsd:float` is odd on its face — `float` is
    single-precision — and currency in a single-precision float is a poor
    choice regardless of which side of this issue it is written from. Note this
    is what production already holds, so it is a question about the ontology,
    not about anything this issue changed.
  * Whether `to_property_maps` / `from_property_maps` could carry a datatype
    alongside the value, the way the annotation path already carries
    `{"value": …, "lang": …}`. It would not help the decimal case on its own —
    `DoubleProperty.__init__` is `float(value)`, so the object never sees the
    decimal — but it is the only route to a datatype-exact GraphObject.
