"""No retired backend is named anywhere in `vitalgraph/`. No exceptions.

`issues/241` archived the Fuseki backends. This gate keeps the package swept, and
it has NO allow-list — a backend that does not exist does not exist, so there is
nothing for the code to say about it.

An earlier version of this file carried a one-entry exemption for a
`RETIRED_BACKENDS` map that translated old config values into "that was retired"
messages. That map is gone too: keeping it meant the code still knew about
something that had been removed, which is the state this issue existed to end. A
stale `.env` now gets

    Unsupported backend type: 'fuseki_postgresql'. Supported: sparql_sql, oxigraph.

which names the bad value and the valid set — everything a reader needs, without
the package carrying a memory of what used to be valid.

WHY A STRING SEARCH AND NOT AN IMPORT CHECK. An import check passes the moment the
package is gone, which was true before most of this issue's work was done. What
kept reappearing was reference WITHOUT dependency — docstrings describing dual-write
to a second store, a config section reading `FUSEKI_*`, an `elif` on a retired
name. None of those import anything, so nothing breaks and no test fails; they just
tell the next reader that a backend exists when it does not. That is exactly what
`issues/240` was: a flag read by nothing, believed because it was written down, and
cited in `issues/241` as evidence about live callers before anyone checked.

WHY A RULE AND NOT A SWEEP. `issues/214` reached "zero occurrences in tracked
files" for a client name; three regressions against it landed in uncommitted work
within a month, and were caught by grep rather than by the rule that was supposed
to hold. A sweep is a state. This is the invariant.

SCOPE IS `vitalgraph/` ONLY, deliberately. 45 files under `test_scripts/` still
name Fuseki (`issues/241`), and a guard that fails on 45 pre-existing hits gets
disabled rather than fixed — the `issues/188` failure. Widen this when those are
archived, not before.
"""

from __future__ import annotations

from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "vitalgraph"

# Names of stores that were retired. Matched case-insensitively.
RETIRED = ("fuseki",)


def _offenders() -> list[str]:
    out = []
    for path in sorted(PACKAGE.rglob("*.py")):
        rel = path.relative_to(PACKAGE).as_posix()
        for n, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
            low = line.lower()
            if any(name in low for name in RETIRED):
                out.append(f"{rel}:{n}: {line.strip()[:100]}")
    return out


def test_no_retired_backend_is_named_in_the_package():
    offenders = _offenders()
    assert not offenders, (
        f"A retired backend is named in `vitalgraph/` again (`issues/241`), "
        f"{len(offenders)} line(s).\n\n"
        "There is no allow-list on purpose. If the reference describes what the "
        "code DOES, say that instead — naming a store that does not exist tells "
        "the next reader it does.\n\n" + "\n".join(offenders))


def test_no_retired_name_is_a_live_backend_type():
    """The registry must not offer one either.

    `BackendType` held `FUSEKI`, `FUSEKI_POSTGRESQL` and `POSTGRESQL` — the last
    of which had outlived `db/postgresql/` entirely, doing nothing but carry an
    error message. Members name packages a caller can get; this asserts that.
    """
    from vitalgraph.db.backend_config import BackendType
    named = {b.value.lower() for b in BackendType}
    assert not [v for v in named if any(r in v for r in RETIRED)], (
        f"BackendType offers a retired backend: {sorted(named)}")
