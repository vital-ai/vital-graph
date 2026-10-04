"""Get-or-create by a declared-unique identifier, through the API (`issues/227`).

Concurrent callers used to mint duplicates — `lookup_by_identifier` then create,
with a window between — and the registry holds the result (34 SF_LEAD_ID and 26
EIN duplicate groups measured on dev). Uniqueness is now DECLARED per
(namespace, entity_type) as a partial unique index; for a declared pair,
`POST /entities/resolve` returns the one entity holding the value or creates it,
and every write path is held to the declaration.

The declaration here is made by the test itself — a partial unique index for a
namespace unique to this run, on `business` — exactly the index
`declare_unique_identifiers.py --apply` builds, and dropped afterwards. The
concurrency case is the point: N simultaneous calls, through a real pool, must
converge on ONE entity, one `entity_created` change row, and N-1 FOUND.

Runs against the vg-test stack (:8002, Postgres :5433).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio

from vitalgraph.entity_registry.entity_registry_schema import EntityRegistrySchema
from vitalgraph.model.entity_registry_model import (
    EntityCreateRequest, EntityResolveRequest, IdentifierCreateRequest)

pytestmark = [pytest.mark.api, pytest.mark.asyncio(loop_scope="session")]


def _uid():
    return uuid.uuid4().hex[:8]


@pytest_asyncio.fixture(loop_scope="session", scope="module")
async def declared_ns(pg_conn):
    """A namespace declared unique for `business`, for this module only."""
    ns = f"RESOLVE_TEST_{_uid().upper()}"
    type_id = await pg_conn.fetchval(
        "SELECT type_id FROM entity_type WHERE type_key = 'business'")
    assert type_id, "the test stack has no 'business' entity type"
    sql = EntityRegistrySchema.declared_index_sql("business", ns, type_id).replace(
        " CONCURRENTLY", "")
    await pg_conn.execute(sql)
    yield ns
    await pg_conn.execute(
        f"DROP INDEX IF EXISTS {EntityRegistrySchema.declared_index_name('business', ns)}")


def _req(ns, value, name="Resolve Probe", **kw):
    return EntityResolveRequest(identifier_namespace=ns, identifier_value=value,
                                type_key="business", primary_name=name, **kw)


async def test_an_undeclared_pair_is_refused(vg_client):
    r = await vg_client.entity_registry.resolve_or_create_entity(
        _req(f"UNDECLARED_{_uid()}", "1"))
    assert r.status == "invalid_request", f"{r.status}: {r.message}"
    assert "not declared unique" in (r.message or "")


async def test_resolve_creates_then_finds_and_ignores_creation_fields(vg_client, declared_ns):
    value = _uid()
    first = await vg_client.entity_registry.resolve_or_create_entity(_req(declared_ns, value, "First Name"))
    assert first.status == "created", f"{first.status}: {first.message}"
    again = await vg_client.entity_registry.resolve_or_create_entity(_req(declared_ns, value, "Other Name"))
    assert again.status == "found", f"{again.status}: {again.message}"
    assert again.entity_id == first.entity_id
    assert again.entity.primary_name == "First Name", (
        "get-or-create, not upsert: the second call's name must be ignored")


async def test_concurrent_callers_converge_on_one_entity(vg_client, declared_ns, pg_conn):
    value = _uid()
    n = 10
    results = await asyncio.gather(*[
        vg_client.entity_registry.resolve_or_create_entity(_req(declared_ns, value))
        for _ in range(n)])
    ids = {r.entity_id for r in results}
    statuses = sorted(r.status for r in results)
    assert len(ids) == 1, f"{n} concurrent calls minted {len(ids)} entities: {ids}"
    assert statuses.count("created") == 1 and statuses.count("found") == n - 1, statuses
    held = await pg_conn.fetchval(
        "SELECT count(DISTINCT entity_id) FROM entity_identifier "
        "WHERE identifier_namespace = $1 AND identifier_value = $2", declared_ns, value)
    assert held == 1, f"{held} entities hold the identifier"
    created = await pg_conn.fetchval(
        "SELECT count(*) FROM entity_change_log WHERE entity_id = $1 "
        "AND change_type = 'entity_created'", ids.pop())
    assert created == 1, f"{created} entity_created rows for the one entity"


async def test_add_identifier_cannot_hand_a_declared_value_to_a_second_entity(
        vg_client, declared_ns):
    value = _uid()
    holder = await vg_client.entity_registry.resolve_or_create_entity(_req(declared_ns, value))
    other = await vg_client.entity_registry.create_entity(EntityCreateRequest(
        type_key="business", primary_name="Second Business"))
    assert other.success
    r = await vg_client.entity_registry.add_identifier(
        other.entity_id, IdentifierCreateRequest(
            identifier_namespace=declared_ns, identifier_value=value))
    assert r.status == "already_exists", f"{r.status}: {r.message}"
    assert holder.entity_id in (r.message or ""), "the response must name the holder"


async def test_create_with_a_held_declared_identifier_is_refused(vg_client, declared_ns, pg_conn):
    value = _uid()
    holder = await vg_client.entity_registry.resolve_or_create_entity(_req(declared_ns, value))
    name = f"Duplicate {_uid()}"
    r = await vg_client.entity_registry.create_entity(EntityCreateRequest(
        type_key="business", primary_name=name,
        identifiers=[IdentifierCreateRequest(identifier_namespace=declared_ns,
                                             identifier_value=value)]))
    assert r.status == "already_exists", f"{r.status}: {r.message}"
    assert r.entity_id == holder.entity_id
    assert await pg_conn.fetchval(
        "SELECT count(*) FROM entity WHERE primary_name = $1", name) == 0, (
        "the refused create left its entity behind")


async def test_a_person_may_still_share_the_value(vg_client, declared_ns):
    """The declaration is per (namespace, TYPE): a person with the same value is
    the by-design pair, not a duplicate."""
    value = _uid()
    await vg_client.entity_registry.resolve_or_create_entity(_req(declared_ns, value))
    r = await vg_client.entity_registry.create_entity(EntityCreateRequest(
        type_key="person", primary_name="Same Lead, Person Side",
        identifiers=[IdentifierCreateRequest(identifier_namespace=declared_ns,
                                             identifier_value=value)]))
    assert r.status == "created", f"{r.status}: {r.message}"
