"""The perf stamp must find a space's tables under its STORAGE KEY.

Since the storage-key migration (2026-10-22) a space's tables are named
`vgs_<key>_*`, not `<space_id>_*`. `fixture_sizes` and `stats_stamp` matched on
the space id, found nothing, and stamped every run with 0 fixture bytes. That
made `reconcile_runner` read every persisted volume as a CLEAN run and block its
promotion (issues/189's flags-disagree check, firing on a measurement defect).
"""
from __future__ import annotations

from tests.performance import perf_record as pr


class _Conn:
    def __init__(self, spaces, tables, stats=None):
        self.spaces, self.tables, self.stats = spaces, tables, stats or []

    async def fetch(self, sql, *a):
        if "FROM space" in sql:
            return [{"space_id": s, "storage_key": k} for s, k in self.spaces]
        if "pg_stat_user_tables" in sql:
            return self.stats
        return [{"relname": n, "bytes": b} for n, b in self.tables]


SPACES = [("sp_lead_synth_100k", "ab12cd34"), ("sp_lead_synth_10k", "zz99yy88"),
          ("legacy_space", None)]
TABLES = [("vgs_ab12cd34_rdf_quad", 30), ("vgs_ab12cd34_term", 5),
          ("vgs_zz99yy88_rdf_quad", 3), ("legacy_space_rdf_quad", 1),
          ("space", 1)]


async def test_sizes_are_attributed_through_the_storage_key():
    sizes = await pr.fixture_sizes(_Conn(SPACES, TABLES))
    assert sizes["space_bytes"] == {
        "sp_lead_synth_100k": 35, "sp_lead_synth_10k": 3, "legacy_space": 1}
    assert sizes["largest_gated_fixture"] == "sp_lead_synth_100k"


async def test_a_dataset_volume_is_classified_persisted_not_clean():
    sizes = await pr.fixture_sizes(_Conn(SPACES[:1], TABLES[:2]))
    r = pr.reconcile_runner({"persist": True, "seeded": True, "pg_port": "5433"},
                            {}, sizes, 8 * 2**30)
    assert r["class"] == "vg-test-docker-persist"
    assert "promotion_blocked" not in r


async def test_stats_pick_the_fixture_tables_by_owner():
    stats = [{"relname": n, "n_live_tup": 10, "analyzed": __import__("datetime").datetime(2026, 1, 1)}
             for n, _ in TABLES]
    out = await pr.stats_stamp(_Conn(SPACES, TABLES, stats))
    # The three sp_lead_synth_* tables; not the legacy space, not `space`.
    assert out["fixture_tables"] == 3
