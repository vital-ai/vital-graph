"""The placeholder-name policy, and the hash property that keeps its rollout cheap.

`issues/249`. These pin the parts that need no database: which names are
placeholders, that skipped names keep their variant index, that the query side
drops them, and that adding the flag moves ONLY placeholder entities' hashes —
otherwise the first sync after deploy would re-index all 1.28M entities.
"""

from __future__ import annotations

import hashlib

import pytest

from vitalgraph.entity_registry.entity_fuzzy import compute_entity_hash
from vitalgraph.entity_registry.entity_fuzzy_pg import EntityFuzzyIndexPG, compute_fuzzy_hash
from vitalgraph.entity_registry.placeholder_names import (
    indexable_names, is_known_placeholder, resolve_placeholder_flag)

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize("name,expected", [
    ("company-4471000", True),
    ("Company-99", True),
    ("  company-1  ", True),
    ("company-", False),
    ("company-12a", False),
    ("Acme company-1", False),
    ("zero-1", False),        # a real `word-<digits>` business (measured: occurs once)
    ("Company", False),
    ("", False),
    (None, False),
])
def test_only_the_measured_format_is_a_placeholder(name, expected):
    assert is_known_placeholder(name) is expected


def test_the_writer_overrides_the_policy():
    assert resolve_placeholder_flag("company-123", False) is False
    assert resolve_placeholder_flag("Acme Inc", True) is True
    assert resolve_placeholder_flag("company-123", None) is True


def test_a_skipped_name_keeps_its_variant_index():
    """Renumbering would break the memory backend's removal, which rebuilds keys
    from `_variant_count = len(all_names)`."""
    entity = {"primary_name": "company-4471000",
              "aliases": [{"alias_name": "Acme Holdings"}, {"alias_name": "Acme"}]}
    assert indexable_names(entity) == [(1, "Acme Holdings"), (2, "Acme")]


def test_the_stored_flag_wins_over_the_pattern():
    entity = {"primary_name": "company-123", "is_placeholder_name": False,
              "aliases": [{"alias_name": "Real Name", "is_placeholder_name": True}]}
    assert indexable_names(entity) == [(0, "company-123")]


def test_the_query_side_drops_placeholders():
    idx = EntityFuzzyIndexPG.__new__(EntityFuzzyIndexPG)
    assert idx._get_name_variants({"primary_name": "company-4471000"}) == []
    assert idx._get_name_variants(
        {"primary_name": "company-1", "aliases": [{"alias_name": "Acme"}]}) == ["Acme"]


def _old_hash(entity):
    """The formula before `issues/249`, verbatim."""
    parts = [(entity.get(k) or "").lower().strip()
             for k in ("type_key", "primary_name", "country", "region", "locality")]
    aliases = sorted(a["alias_name"].lower().strip()
                     for a in entity.get("aliases") or [] if a.get("alias_name"))
    parts.append(",".join(aliases))
    return hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()


def test_a_real_named_entity_keeps_its_hash():
    """If this moved, the first sync after deploy would re-index everything."""
    e = {"type_key": "business", "primary_name": "Acme Industrial Supply",
         "country": "US", "region": "NY", "locality": "Albany",
         "aliases": [{"alias_name": "Acme"}], "is_placeholder_name": False}
    assert compute_fuzzy_hash(e) == _old_hash(e)
    assert compute_entity_hash(e) == _old_hash(e)


def test_a_placeholder_entity_gets_a_new_hash_and_a_correction_moves_it_again():
    e = {"type_key": "business", "primary_name": "company-4471000"}
    flagged = compute_fuzzy_hash(e)
    assert flagged != _old_hash(e), (
        "the placeholder entities' hashes must change, so the sync path "
        "re-indexes them and drops their bands")
    corrected = compute_fuzzy_hash({**e, "is_placeholder_name": False})
    assert corrected == _old_hash(e) and corrected != flagged, (
        "a manual 'this is a real name' correction must move the hash, or it "
        "never reaches the sync path")


def test_both_hash_copies_agree():
    for e in ({"primary_name": "company-1"},
              {"primary_name": "Acme", "aliases": [{"alias_name": "company-9"}]},
              {"primary_name": "Acme", "is_placeholder_name": True}):
        assert compute_fuzzy_hash(e) == compute_entity_hash(e)
