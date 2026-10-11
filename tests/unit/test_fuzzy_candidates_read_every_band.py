"""Candidate generation reads every band, in one statement per stage — issue 254.

It used to read 3 bands per round trip and stop once 20 entities had hits on half
the bands read so far. On names built from common words that bar is met after the
first 3 bands, so a typo whose distinctive token matched only in later bands was
never reached: measured on a 1.04M-entity registry, `Enjamb Armstrnog Transport
Group` shared 12 of 21 bands with its target and was missed, because 44
`... Transport Group` names had 2 hits in the first batch. Reading every band is
also one round trip instead of seven.
"""

from __future__ import annotations

import asyncio

from vitalgraph.entity_registry.entity_fuzzy_pg import EntityFuzzyIndexPG
from vitalgraph.entity_registry.entity_fuzzy_storage import TABLE_PRIMARY


class _Storage:
    """Answers the first 3 primary bands with 25 common-word decoys at 2 hits each
    (enough to have tripped the old early stop) and the target in later bands."""

    def __init__(self, target_bands):
        self.calls = []
        self.target_bands = target_bands

    async def query_bands(self, table, band_queries):
        self.calls.append((table, [b for b, _ in band_queries]))
        hits = {}
        bands = [b for b, _ in band_queries]
        if table == TABLE_PRIMARY:
            if 0 in bands:
                hits.update({f"decoy{i}::0": 2 for i in range(25)})
            n = sum(1 for b in bands if b in self.target_bands)
            if n:
                hits["target::0"] = n
        return hits


def _index(storage):
    idx = EntityFuzzyIndexPG.__new__(EntityFuzzyIndexPG)
    EntityFuzzyIndexPG.__init__(idx, pool=None)
    idx.storage = storage
    return idx


def test_every_primary_band_is_read_in_one_statement():
    storage = _Storage(target_bands=set(range(9, 21)))
    idx = _index(storage)
    ids = asyncio.run(idx.get_candidate_ids({"primary_name": "Enjamb Armstrnog Transport Group"}))
    primary = [bands for t, bands in storage.calls if t == TABLE_PRIMARY]
    assert primary[0] == list(range(len(idx.primary_band_ranges))), primary
    assert len(primary) == 1, "the primary bands took more than one statement"
    assert "target" in ids, "the target matched only in later bands and was not reached"


def test_the_storage_layer_has_no_progressive_query():
    from vitalgraph.entity_registry.entity_fuzzy_storage import PostgreSQLFuzzyStorage
    assert not hasattr(PostgreSQLFuzzyStorage, "query_bands_progressive")
