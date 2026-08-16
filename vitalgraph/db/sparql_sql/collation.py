"""The collation SPARQL string ordering requires, pinned in one place.

SPARQL 1.1 §15.1 orders simple literals by Unicode CODE POINT. PostgreSQL orders
`text` by the collation in force, which is whatever the cluster was created with.
They agree only when that is `C` / `C.UTF-8`.

Demonstrated, same three values:

    ORDER BY v COLLATE "C"            ->  Banana < Zebra < apple    (codepoint)
    ORDER BY v COLLATE "en-US-x-icu"  ->  apple < Banana < Zebra    (locale)

Both are legitimate PostgreSQL orderings; only the first is SPARQL. So the
emitter states the collation rather than inheriting one — otherwise conformance
is a property of `initdb` rather than of this repository, and the same code
returns different rows on two deployments with no error anywhere.

The reach is wider than "rows come back in a different order": `LIMIT` over a
sorted query returns DIFFERENT ROWS, and §18.5.1 defines `MIN`/`MAX` by the
ORDER BY ordering, so aggregates return a different term too.

COST: none where it already matches. Measured on a C cluster, the plans with and
without are identical — when the requested collation matches the column's,
PostgreSQL treats them as the same and indexes stay usable. On a non-C cluster a
text index would stop serving the collated ordering and a sort would appear, but
that deployment has no correct plan today, so the trade is correctness for a plan
change rather than speed for correctness.
"""

from __future__ import annotations

# The literal is quoted because `C` is case-sensitive as a collation name.
SPARQL_COLLATION = '"C"'


def collate(sql: str) -> str:
    """Pin `sql` to the collation SPARQL string ordering requires.

    Applied to TEXT operands only. Applying it to a uuid, numeric or timestamp
    column is an error in PostgreSQL, not a no-op, so callers pass the text
    column explicitly rather than wrapping whole expressions.
    """
    return f"{sql} COLLATE {SPARQL_COLLATION}"
