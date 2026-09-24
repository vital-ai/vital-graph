"""`preserve_supplied` keeps the timestamps a request carried.

WHY IT EXISTS. `stamp_entity_server_properties` sets `objectCreationTime = now`
unconditionally on create. That is right for a client minting a new entity and
wrong for anything COPYING one: archiving 43,783 nurture actions from
`prod_kg` into `prod_kg_archive` through `POST /api/graphs/kgentities`
would date every one of them to the day of the copy, and the plan is to delete
the originals afterwards — so the real creation dates would not exist anywhere.
The archive is organised by creation month, which is precisely the field being
destroyed.

WHAT THE FLAG MUST NOT DO is change the default. Every existing caller omits it,
so the first two tests here pin the unflagged behaviour; if they ever go green
while asserting something else, the flag has leaked into the default path.

The partial cases matter as much as the whole-object ones: a request may carry a
creation time and no modification time. Preserving one must not leave the other
unset, or a copied entity arrives with a NULL where every consumer expects a
timestamp.
"""

from datetime import datetime, timezone

import pytest
from ai_haley_kg_domain.model.KGEntity import KGEntity

from vitalgraph.kg_impl.kg_server_properties import (
    DEFAULT_STATUS, stamp_entity_server_properties)

NOW = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)
SUPPLIED_CREATED = datetime(2026, 5, 4, 9, 30, 0, tzinfo=timezone.utc)
SUPPLIED_MODIFIED = datetime(2026, 6, 1, 8, 0, 0, tzinfo=timezone.utc)
STORED_CREATED = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def _entity(created=None, modified=None):
    e = KGEntity()
    e.URI = "urn:test:entity:1"
    if created:
        e.objectCreationTime = created
    if modified:
        e.objectModificationDateTime = modified
    return e


def _times(e):
    created = e.objectCreationTime.value if e.objectCreationTime else None
    modified = (e.objectModificationDateTime.value
                if e.objectModificationDateTime else None)
    return created, modified


# --------------------------------------------------------------------------
# the default must not move
# --------------------------------------------------------------------------

def test_create_stamps_now_by_default():
    e = _entity()
    stamp_entity_server_properties(e, NOW, is_create=True)
    assert _times(e) == (NOW, NOW)


def test_create_overwrites_supplied_times_by_default():
    """The behaviour the flag exists to opt out of — pinned so it stays opt-in."""
    e = _entity(SUPPLIED_CREATED, SUPPLIED_MODIFIED)
    stamp_entity_server_properties(e, NOW, is_create=True)
    assert _times(e) == (NOW, NOW)


# --------------------------------------------------------------------------
# with the flag
# --------------------------------------------------------------------------

def test_preserve_keeps_both_supplied_times():
    e = _entity(SUPPLIED_CREATED, SUPPLIED_MODIFIED)
    stamp_entity_server_properties(e, NOW, is_create=True, preserve_supplied=True)
    assert _times(e) == (SUPPLIED_CREATED, SUPPLIED_MODIFIED)


def test_preserve_still_stamps_what_was_not_supplied():
    """Turning the flag on must never leave a timestamp unset."""
    e = _entity()
    stamp_entity_server_properties(e, NOW, is_create=True, preserve_supplied=True)
    assert _times(e) == (NOW, NOW)


@pytest.mark.parametrize("created,modified,expect", [
    (SUPPLIED_CREATED, None, (SUPPLIED_CREATED, NOW)),
    (None, SUPPLIED_MODIFIED, (NOW, SUPPLIED_MODIFIED)),
])
def test_preserve_handles_one_of_the_two(created, modified, expect):
    e = _entity(created, modified)
    stamp_entity_server_properties(e, NOW, is_create=True, preserve_supplied=True)
    assert _times(e) == expect


def test_preserve_on_update_keeps_supplied_over_stored():
    """On update the stored creation time normally wins; supplied outranks it."""
    e = _entity(SUPPLIED_CREATED)
    stamp_entity_server_properties(
        e, NOW, existing_creation_time=STORED_CREATED, is_create=False,
        preserve_supplied=True)
    assert e.objectCreationTime.value == SUPPLIED_CREATED


def test_update_without_supplied_still_uses_the_stored_time():
    e = _entity()
    stamp_entity_server_properties(
        e, NOW, existing_creation_time=STORED_CREATED, is_create=False,
        preserve_supplied=True)
    assert e.objectCreationTime.value == STORED_CREATED


# --------------------------------------------------------------------------
# the flag is about timestamps only
# --------------------------------------------------------------------------

def test_status_default_is_unaffected_by_the_flag():
    e = _entity(SUPPLIED_CREATED, SUPPLIED_MODIFIED)
    stamp_entity_server_properties(e, NOW, is_create=True, preserve_supplied=True)
    assert str(e.objectStatusType) == DEFAULT_STATUS
