# 332 — Stored text with a literal backslash before `n` or `r` is rewritten

## Status: RESOLVED 2026-11-01, verified on the vg test stack. Not yet released.

The fix has to reach the CLIENT as well as the server: responses are parsed in
the client (`parse_nquads_object`), so an old client keeps altering correct
stored text against a fixed server.

Existing damaged rows are NOT repaired, and cannot be automatically; see below.

## The defect

`_unescape_nquads_string` existed twice (`quad_format_utils`,
`data_import_impl`) as chained `replace` calls, backslashes last. `a\nb` with a
typed backslash is escaped as `a\\nb`, and the `\n` step matched the SECOND
backslash and the `n`, leaving a backslash and a real line break. No ordering of
the calls is right: backslashes first turns it into `a`, a line break and `b`.

Measured on the test stack, stored bytes read with `psql`:

    written                 C:\new\report
    entity create           C:\<LF>ew\<CR>eport     bytes 5c 0a where 5c 6e belongs
    add_triples             the same
    SPARQL INSERT DATA      C:\new\report           never used the unescape

So it ran on BOTH sides, independently:

| Path | Before |
|---|---|
| Write: KG entity create, `add_triples` | corrupted, stored |
| Import: JSONL, vital-block | corrupted, stored (parser run directly) |
| Read: `get_kgentity` | corrupted, even when the store was right |
| Read: SPARQL `SELECT`, `list_triples` | returned what was stored |
| Write: SPARQL `INSERT DATA` | clean |

Anything with a backslash before `n` or `r` was affected: Windows paths, LaTeX,
regexes, JSON embedded in text. In a save/read fuzz of backslash-heavy random
strings, 28,982 of 200,000 came back changed.

`test_backslashes_survive` missed it because `C:\path\to\file` contains neither.

## Two related defects, fixed with it

**Other escapes were not read at all.** `\t`, `\b`, `\f`, `\'`, `\uXXXX` and
`\UXXXXXXXX` stayed as written. Our own JSONL export writes a real tab as `\t`
(`_escape_ntriples`), so an export and re-import turned a tab into a backslash
and a `t`.

**`nquads_text_to_quads` cut literals short.** `splitlines()` also breaks on
U+2028, U+2029, VT, FF, NEL and FS, which are legal unescaped in a literal.
Latent: no server route reaches this parser, and JSON quads, the default wire,
stored these characters correctly.

## Fix

`vitalgraph/utils/nquads_string.py` holds the one implementation, a single
left-to-right pass over the whole escape grammar. It is its own module because
`data_import_impl` runs it per term and does not otherwise load the VitalSigns
and rdflib imports of `quad_format_utils`. An invalid escape stays as written,
including a surrogate or an out-of-range codepoint, which PostgreSQL could not
store. `nquads_text_to_quads` now splits on CR and LF only.

Cost, per call: 0.13 -> 0.14 us on a short value with no backslash, 2.2 -> 5.1 us
on a 380-character value with 20 escapes.

## Existing data

Rows holding a backslash followed by a real CR or LF, by a direct scan of every
term table:

    test stack    4 of 4.48M literals, all transcript-like text in one space
    dev           4 of 2.67M literals, 2 of them in an application test space
    production    not scanned

These cannot be repaired from the bytes alone. A backslash before a real line
break is also legitimate text (a shell line continuation) and it round-trips
correctly, so the stored form does not say which rows were altered. After this
fix such rows simply read back as stored. A term rewritten from the original
source text lands on a new term, because the text is hashed into its uuid.

## Verification

Test stack rebuilt from the working tree; the 29 spaces intact.

    tests/unit/test_nquads_string_escapes.py        121 passed
    tests/api/test_literal_text_round_trip.py        18 passed
    tests/api/test_triples_api.py                     8 passed
    tests/api/test_kgdocuments_api.py                22 passed
    tests/api/test_import_export_api.py              25 passed
    tests/integration/test_datatype_fidelity.py      17 passed
    tests/unit                                       exit 0

The new unit tests fail with the old `replace` chain patched back in. The API
tests assert the stored bytes as well as the read, and SPARQL-written values
cover the read side alone. The JSONL and vital-block paths are covered at the
parser, not by a live import.
