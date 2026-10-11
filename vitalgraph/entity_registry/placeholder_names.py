"""Placeholder names: stored, rendered, never fuzzy-indexed or fuzzy-queried.

`issues/249`. A third of production's business entities (212,360 of 1.28M active
on 2026-10-11) have a `primary_name` of the form `company-<digits>`, minted
upstream by a backfill. Every pair of them scores above the default
`min_score` (`company-4471000` vs `company-4471008` is a 93.3 "high"), so each
was a confident duplicate of every other, and `compute_phonetic_codes` drops
digits, so all of them shared one phonetic band cell in all 21 bands.

The decision is stored per NAME (`entity.is_placeholder_name`,
`entity_alias.is_placeholder_name`), not re-derived inside the indexers: the bulk
rebuild and the incremental add must agree exactly, and a rule evaluated in both
is a drift source. The writer may state it; when it does not, the name is
checked against KNOWN upstream placeholder formats only — not a general "is this
name useful" heuristic, which would silently suppress real dedup.

`indexable_names` is the one place every index and query path asks. It reads the
stored flag when the dict carries one and falls back to the same pattern list
when it does not (a dict built in memory before the row exists), so both paths
give the same answer either way.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

#: Known upstream placeholder formats. Measured on production 2026-10-11 by a
#: GROUP BY over name shapes: `company-<digits>` is the ONLY one (212,360
#: entities; every other `word-<digits>` name occurs once and is a real
#: business), and no alias has a placeholder shape. Add a format here only
#: after measuring it the same way.
KNOWN_PLACEHOLDER_PATTERNS = (
    re.compile(r"^company-\d+$", re.IGNORECASE),
)


def is_known_placeholder(name: Optional[str]) -> bool:
    if not name:
        return False
    s = name.strip()
    return any(p.match(s) for p in KNOWN_PLACEHOLDER_PATTERNS)


def resolve_placeholder_flag(name: Optional[str], explicit: Optional[bool]) -> bool:
    """The writer's statement wins; otherwise the known-format policy decides."""
    return bool(explicit) if explicit is not None else is_known_placeholder(name)


def _flag(holder: Dict[str, Any], name: str) -> bool:
    stored = holder.get("is_placeholder_name")
    return bool(stored) if stored is not None else is_known_placeholder(name)


def all_names(entity: Dict[str, Any]) -> List[Tuple[str, bool]]:
    """`[(name, is_placeholder)]` in index order: primary first, then aliases."""
    out: List[Tuple[str, bool]] = []
    primary = entity.get("primary_name") or ""
    if primary:
        out.append((primary, _flag(entity, primary)))
    for alias in (entity.get("aliases") or []):
        if not isinstance(alias, dict):
            continue
        name = alias.get("alias_name")
        if name:
            out.append((name, _flag(alias, name)))
    return out


def indexable_names(entity: Dict[str, Any]) -> List[Tuple[int, str]]:
    """`[(variant_idx, name)]` for the names that may enter the fuzzy index.

    The index is the name's position among ALL names, placeholders included —
    skipped, not renumbered. The memory backend removes bands by reconstructing
    keys from `_variant_count = len(all_names)`, so stable numbering keeps its
    removal a superset of what was written (`issues/249`, "Two traps").
    """
    return [(i, n) for i, (n, ph) in enumerate(all_names(entity)) if not ph]


def placeholder_hash_suffix(entity: Dict[str, Any]) -> str:
    """Extra input for the fuzzy hash, EMPTY unless some name is a placeholder.

    The flag must move the hash, or a manual "this one is a real name" correction
    would never reach the sync path. But appending it unconditionally would change
    every entity's hash and make the next sync re-index all 1.28M of them; this
    way only the placeholder entities' hashes change — and re-indexing those is
    exactly what drops their bands.
    """
    flagged = sorted(n.lower().strip() for n, ph in all_names(entity) if ph)
    return ("|placeholder:" + ",".join(flagged)) if flagged else ""
