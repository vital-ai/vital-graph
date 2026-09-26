"""The retired backend does not come back into `vitalgraph/`.

`issues/241` archived the Fuseki backends and swept the package. This is the gate
that keeps it swept, and it exists because `issues/214` is the precedent: that
issue reached "zero occurrences in tracked files" for a client name, and it held
because a RULE enforced it — three regressions against it landed in uncommitted
work within a month of the sweep. A sweep is a state; a rule is an invariant.

WHY A STRING SEARCH AND NOT AN IMPORT CHECK. An import check passes the moment the
package is gone, which was true before most of this issue's work was done. What
kept reappearing was reference without dependency — docstrings describing
dual-write to a second store, a config section reading `FUSEKI_*`, an `elif` on a
retired backend name. None of those import anything, so nothing breaks and no test
fails; they simply tell the next reader that a backend exists when it does not.
That is what `issues/240` was: a flag read by nothing, believed because it was
written down.

THE ALLOW-LIST IS THE INTERESTING PART. Keep it short and make every entry say
why, or this becomes what `issues/188` describes — a rule that passes by exempting
what it cannot check. Step 7 of `issues/241` deleted two exemptions from
`test_connection_settings_are_required.py` for exactly that reason, so adding a
guard with a long allow-list of its own would trade one for the other.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "vitalgraph"

# Names of stores that were retired. Searched case-insensitively.
RETIRED = ("fuseki",)

# Files allowed to name a retired backend, each with the reason.
#
#   impl/vitalgraph_impl.py   holds RETIRED_BACKENDS: the map from a retired
#                             CONFIG VALUE to the message a caller gets. A value
#                             has to be recognised to be diagnosed, and this map
#                             is why `BackendType` no longer carries dead members
#                             to carry that message for it (`issues/241`).
ALLOWED = {
    "impl/vitalgraph_impl.py",
}


def _offenders() -> list[str]:
    out = []
    for path in sorted(PACKAGE.rglob("*.py")):
        rel = path.relative_to(PACKAGE).as_posix()
        if rel in ALLOWED:
            continue
        text = path.read_text(errors="ignore")
        for n, line in enumerate(text.splitlines(), 1):
            low = line.lower()
            if any(name in low for name in RETIRED):
                out.append(f"{rel}:{n}: {line.strip()[:100]}")
    return out


def test_no_retired_backend_is_named_in_the_package():
    offenders = _offenders()
    assert not offenders, (
        "A retired backend is named in `vitalgraph/` again (`issues/241`).\n\n"
        "If this is a NEW reference, it is describing a store that does not "
        "exist — say what the code does instead.\n"
        "If it is genuinely needed, add the file to ALLOWED with the reason, and "
        "keep in mind that a growing allow-list is how this guard stops "
        "working.\n\n" + "\n".join(offenders))


def test_the_allow_list_entries_still_earn_their_place():
    """An allow-list entry that no longer matches anything is stale and should go.

    Without this, the list only ever grows: an entry added for a real reason
    outlives the reason, and the next person reads it as permission. This is the
    `issues/188` failure in miniature — a rule whose exemptions are not themselves
    checked.
    """
    for rel in sorted(ALLOWED):
        path = PACKAGE / rel
        assert path.exists(), f"ALLOWED names {rel}, which does not exist"
        low = path.read_text(errors="ignore").lower()
        assert any(name in low for name in RETIRED), (
            f"{rel} is in ALLOWED but no longer names a retired backend — "
            f"remove the exemption (`issues/241`)")


@pytest.mark.parametrize("name", RETIRED)
def test_the_retired_name_is_still_recognised_in_config(name):
    """Removing a backend must not make its config value UNRECOGNISED.

    A `.env` in the wild can still say `fuseki_postgresql`. The point of deleting
    the enum member was that an enum is the wrong place to hold a diagnostic — not
    that the diagnostic should go. If this fails, an old config gets "unsupported
    backend type" instead of being told what happened to it.
    """
    from vitalgraph.impl.vitalgraph_impl import RETIRED_BACKENDS
    assert any(name in key for key in RETIRED_BACKENDS), (
        f"'{name}' is swept from the package but no longer recognised as a "
        f"retired config value, so an old .env gets a worse error")


def test_retired_names_are_not_also_live_backend_types():
    """The two lists must not overlap, or a retired name would both resolve and
    be reported as retired — and which one wins would depend on branch order."""
    from vitalgraph.db.backend_config import BackendType
    from vitalgraph.impl.vitalgraph_impl import RETIRED_BACKENDS
    live = {b.value for b in BackendType}
    assert not (live & set(RETIRED_BACKENDS)), (
        f"overlap between live BackendType values and RETIRED_BACKENDS: "
        f"{live & set(RETIRED_BACKENDS)}")
