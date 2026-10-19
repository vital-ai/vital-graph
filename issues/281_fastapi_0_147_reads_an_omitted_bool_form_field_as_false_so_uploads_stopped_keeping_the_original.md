# 281 — FastAPI 0.147 reads an omitted bool form field as False, so uploads stopped keeping the original

## Status: FIXED IN CODE 2026-10-19 (not yet released). Production not affected yet: its image predates FastAPI 0.147. The next image build would be.

**Related:** `issues/280` (the same day's other dependency surprise: a new
release, no change in this repo, E2E red).

## What happened

E2E on `dce5837b`, 2026-10-19: one Playwright test of 277 failed on all three
retries. `kgdocuments-crud` › "HTML is converted to Markdown and the original
is preserved" failed with `the original should be retained`: the upload
succeeded and converted, and `file_node_uri` was null.

`/kgdocuments/upload` declared
`store_original: bool = Form(True, …)`. The portal, like most clients, does not
send the field. **FastAPI 0.147.0 (released 2026-10-19 09:48 UTC) delivers an
omitted `bool` form field as False, whatever its default.** That is checkbox
semantics. It applies to `Optional[bool] = Form(None)` too. `str` and `int`
defaults are unaffected. Measured with a minimal app:

| FastAPI | omitted `bool = Form(True)` |
|---|---|
| 0.146.0 | True |
| 0.147.0 | **False** |
| 0.148.0 | **False** |

Starlette 1.8.0 vs 1.9.0 makes no difference. CI resolves dependencies fresh
on every run (`fastapi` is unpinned), so the change arrived with no commit
here. On the vg test stack after a rebuild, the same upload with the field
omitted returned `file_node_uri: null`; with `store_original=true` it kept the
original.

The behaviour is silent. Uploads succeed, the converted Markdown is stored,
and only the original bytes are dropped. Nothing logs it, because
`store_original=False` is a legitimate request.

## Fixed (code)

* `store_original` is taken as `Optional[str] = Form(None)` and parsed by
  `_form_flag`. Omitted or empty means true. `true/1/yes/on` and
  `false/0/no/off` are accepted, and anything else is INVALID_REQUEST in a 200.
  The wire format is unchanged.
* It was the only `bool` form field in `vitalgraph/`. A unit guard
  (`tests/unit/test_form_flags_survive_fastapi_checkbox_semantics.py`) parses
  every module and fails on any parameter annotated `bool`/`Optional[bool]`
  whose default is `Form(...)`. The local env has FastAPI 0.143, which would
  not show the problem.

## Verification

The unit tests (18) cover the parser, the default, and the guard (which
recognises the old declaration). On the vg test stack, rebuilt (FastAPI 0.147),
the upload was tried with the field omitted, `false`, and an invalid value; see
the commit.

## Production

* Today's production image (v0.0.90, built 2026-10-18 12:26 UTC) has an older
  FastAPI and keeps originals.
* **The next image build will pull FastAPI ≥ 0.147**, so the next release must
  carry this fix or uploads lose their originals. It is on `main` with the
  other fixes since v0.0.90.
* Not done: whether to pin FastAPI as pyoxigraph now is (`issues/280`).
  0.147 changed a form default with no deprecation; pinning would turn such
  changes into Dependabot PRs.
