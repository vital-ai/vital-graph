"""BACKFILL_EXCLUDE_SPACES falls back to the maintenance exclusion list.

Both variables answer the same question -- which spaces are benchmark fixtures
that must not be written to while a run measures them -- and the test stack had
twelve spaces in one and none in the other. Reloading a fixture then left the
backfill free to append server properties to the very spaces the operator had
declared off-limits, at ~3 quads per KGEntity.

The precedence has three cases and the third is the one worth pinning: an
explicitly EMPTY BACKFILL_EXCLUDE_SPACES must keep meaning "back-fill
everything", not silently inherit the maintenance list. Treating unset and
empty alike would take that override away.
"""
from __future__ import annotations

import pytest

from vitalgraph.tasks.backfill_server_properties_task import (
    BackfillServerPropertiesTask)

MAINT = "VG_MAINTENANCE_EXCLUDE_SPACES"
BACK = "BACKFILL_EXCLUDE_SPACES"


def _excluded(monkeypatch, backfill, maintenance):
    for name, value in ((BACK, backfill), (MAINT, maintenance)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    return BackfillServerPropertiesTask(pool=None, space_manager=None).exclude_spaces


def test_own_setting_wins(monkeypatch):
    assert _excluded(monkeypatch, "a,b", "c,d") == {"a", "b"}


def test_falls_back_to_maintenance_list_when_unset(monkeypatch):
    assert _excluded(monkeypatch, None, "sp_lead_synth_100k, wordnet_frames") == {
        "sp_lead_synth_100k", "wordnet_frames"}


def test_explicit_empty_means_backfill_everything(monkeypatch):
    # NOT the maintenance list. Setting it empty is how an operator says "I know
    # what maintenance skips, back-fill anyway".
    assert _excluded(monkeypatch, "", "sp_lead_synth_100k") == set()


def test_neither_set_excludes_nothing(monkeypatch):
    assert _excluded(monkeypatch, None, None) == set()
