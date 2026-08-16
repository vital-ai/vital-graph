# `xsd:float` Cast Disagrees With the Manifest on Lexical Form

## Status: OPEN — low confidence this is ours; found 2026-08-16

`cast/xsd:float cast` expects a row with `v = "+33.3300"` (the ORIGINAL lexical
form preserved) alongside `float = 33.33`. We return the row with `v` already
normalised.

The harness classifies it `ACCEPTED: ... [pyoxigraph also differs from .srx]`,
which is the important qualifier: **the reference implementation disagrees with
the manifest here too.** So this may be a manifest that encodes a stricter
lexical-preservation rule than either implementation follows, rather than a
defect in ours.

## Why it is filed anyway

Because "both implementations differ from the spec text" is a claim worth
recording rather than re-deriving. The next person to widen the cast category
will otherwise repeat this investigation from scratch.

## What would settle it

Read XPath F&O §17.1.3 on `xsd:float` casting and decide whether the input's
lexical form must survive into an unrelated projected variable. If it must, this
is ours and the fix is in the cast path; if not, the case belongs on the
xfail list with this reasoning attached.

## Related

- `issues/093` — found in the same pass
- `planning/planning_sparql_features/README.md` §4 — datatype edge cases
