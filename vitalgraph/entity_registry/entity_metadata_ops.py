"""Unified management for the registry's metadata vocabularies.

Six "kinds" of vocabulary, all managed the same way:

  entity-types, categories, relationship-types, location-types  — FK-enforced
  identifier-types, alias-types                                 — auto-registered

Each is a table with (key, label, description, is_active). This mixin provides
generic list / get / create / update / delete plus a shared `metadata_usage_count`
helper (the counting rules that used to live in `get_metadata_summary`) and an
auto-register upsert for the two tag kinds.

Delete safety: `delete_metadata` refuses (raises `MetadataInUseError`) while any
record references the value.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import asyncpg

from vitalgraph.utils.db_retry import with_db_retry
from .entity_status import ACTIVE, DELETED, RETRACTED


class MetadataInUseError(Exception):
    """Raised when deleting a metadata value that records still reference."""

    def __init__(self, kind: str, key: str, usage_count: int):
        self.kind = kind
        self.key = key
        self.usage_count = usage_count
        super().__init__(f"{kind} '{key}' is in use by {usage_count} record(s)")


class UnknownMetadataKindError(Exception):
    """Raised for a kind not in the registry."""


# Per-kind config. `usage` is a COUNT query taking $1 = key, filtering
# soft-deleted rows by that table's own convention (see get_metadata_summary).
_KINDS: Dict[str, Dict[str, Any]] = {
    'entity-types': {
        'table': 'entity_type', 'key': 'type_key',
        'label': 'type_label', 'desc': 'type_description', 'inverse': None,
        'change': 'entity_type',
        'usage': "SELECT COUNT(*) FROM entity e JOIN entity_type t "
                 "ON t.type_id = e.entity_type_id "
                 f"WHERE t.type_key = $1 AND e.status != '{DELETED}'",
    },
    'categories': {
        'table': 'category', 'key': 'category_key',
        'label': 'category_label', 'desc': 'category_description', 'inverse': None,
        'change': 'category',
        # category is referenced from two tables — count both.
        'usage': "SELECT "
                 "(SELECT COUNT(*) FROM entity_category_map m JOIN category c "
                 " ON c.category_id = m.category_id "
                 f" WHERE c.category_key = $1 AND m.status = '{ACTIVE}') "
                 "+ (SELECT COUNT(*) FROM entity_location_category_map lm JOIN category c "
                 "   ON c.category_id = lm.category_id "
                 f"   WHERE c.category_key = $1 AND lm.status = '{ACTIVE}')",
    },
    'relationship-types': {
        'table': 'relationship_type', 'key': 'type_key',
        'label': 'type_label', 'desc': 'type_description', 'inverse': 'inverse_key',
        'change': 'relationship_type',
        'usage': "SELECT COUNT(*) FROM entity_relationship r JOIN relationship_type rt "
                 "ON rt.relationship_type_id = r.relationship_type_id "
                 f"WHERE rt.type_key = $1 AND r.status != '{RETRACTED}'",
    },
    'location-types': {
        'table': 'entity_location_type', 'key': 'type_key',
        'label': 'type_label', 'desc': 'type_description', 'inverse': None,
        'change': 'location_type',
        'usage': "SELECT COUNT(*) FROM entity_location l JOIN entity_location_type lt "
                 "ON lt.location_type_id = l.location_type_id "
                 f"WHERE lt.type_key = $1 AND l.status = '{ACTIVE}'",
    },
    # Tag kinds: the value IS stored on the data row (no id join), and new values
    # auto-register on write via `register_metadata`.
    'identifier-types': {
        'table': 'identifier_type', 'key': 'type_key',
        'label': 'type_label', 'desc': 'type_description', 'inverse': None,
        'change': 'identifier_type', 'auto_register': True,
        'usage': "SELECT COUNT(*) FROM entity_identifier "
                 f"WHERE identifier_namespace = $1 AND status != '{RETRACTED}'",
    },
    'alias-types': {
        'table': 'alias_type', 'key': 'type_key',
        'label': 'type_label', 'desc': 'type_description', 'inverse': None,
        'change': 'alias_type', 'auto_register': True,
        'usage': "SELECT COUNT(*) FROM entity_alias "
                 f"WHERE alias_type = $1 AND status != '{RETRACTED}'",
    },
}

METADATA_KINDS = tuple(_KINDS.keys())


def _cfg(kind: str) -> Dict[str, Any]:
    cfg = _KINDS.get(kind)
    if cfg is None:
        raise UnknownMetadataKindError(
            f"Unknown metadata kind: {kind}. One of {METADATA_KINDS}")
    return cfg


def _row_to_dict(cfg: Dict[str, Any], row: asyncpg.Record) -> Dict[str, Any]:
    d = {
        'key': row['key'],
        'label': row['label'],
        'description': row['description'],
        'is_active': row['is_active'],
        'created_time': row['created_time'],
    }
    if cfg['inverse']:
        d['inverse_key'] = row.get('inverse_key')
    if 'usage_count' in row:
        d['usage_count'] = row['usage_count']
    return d


class MetadataMixin:
    """Mixed into EntityRegistryImpl; expects self.pool and self._log_change."""

    pool: asyncpg.Pool

    async def _log_change(self, conn, entity_id, change_type, details,
                          changed_by=None) -> None: ...

    # ------------------------------------------------------------------
    # Shared usage count — the delete-safety and dropdown-count source
    # ------------------------------------------------------------------

    @with_db_retry()
    async def metadata_usage_count(self, kind: str, key: str) -> int:
        cfg = _cfg(kind)
        async with self.pool.acquire() as conn:
            n = await conn.fetchval(cfg['usage'], key)
        return int(n or 0)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    @with_db_retry()
    async def list_metadata(
        self, kind: str, *, include_inactive: bool = False,
        include_usage: bool = False, q: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        cfg = _cfg(kind)
        inv = f"{cfg['inverse']} AS inverse_key, " if cfg['inverse'] else ""
        conds, params = [], []
        if not include_inactive:
            conds.append("is_active = TRUE")
        if q:
            params.append(f"{q}%")
            conds.append(f"({cfg['key']} ILIKE ${len(params)} OR {cfg['label']} ILIKE ${len(params)})")
        where = f"WHERE {' AND '.join(conds)}" if conds else ""
        sql = (
            f"SELECT {cfg['key']} AS key, {cfg['label']} AS label, "
            f"{cfg['desc']} AS description, {inv}is_active, created_time "
            f"FROM {cfg['table']} {where} ORDER BY {cfg['key']}"
        )
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            out = [_row_to_dict(cfg, r) for r in rows]
            if include_usage:
                for d in out:
                    d['usage_count'] = int(await conn.fetchval(cfg['usage'], d['key']) or 0)
        return out

    @with_db_retry()
    async def get_metadata(self, kind: str, key: str) -> Optional[Dict[str, Any]]:
        cfg = _cfg(kind)
        inv = f"{cfg['inverse']} AS inverse_key, " if cfg['inverse'] else ""
        sql = (
            f"SELECT {cfg['key']} AS key, {cfg['label']} AS label, "
            f"{cfg['desc']} AS description, {inv}is_active, created_time "
            f"FROM {cfg['table']} WHERE {cfg['key']} = $1"
        )
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(sql, key)
            if row is None:
                return None
            d = _row_to_dict(cfg, row)
            d['usage_count'] = int(await conn.fetchval(cfg['usage'], key) or 0)
            return d

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    @with_db_retry()
    async def create_metadata(
        self, kind: str, key: str, label: str,
        description: Optional[str] = None, inverse_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        cfg = _cfg(kind)
        cols = [cfg['key'], cfg['label'], cfg['desc']]
        vals: List[Any] = [key, label, description]
        if cfg['inverse']:
            cols.append(cfg['inverse'])
            vals.append(inverse_key)
        ph = ', '.join(f"${i}" for i in range(1, len(vals) + 1))
        sql = f"INSERT INTO {cfg['table']} ({', '.join(cols)}) VALUES ({ph}) RETURNING *"
        # The try wraps the whole transaction: the inverse_key FK is DEFERRABLE
        # INITIALLY DEFERRED, so a violation surfaces at commit (transaction exit),
        # not at execute. A UniqueViolation surfaces immediately at execute. Both
        # are inside this block.
        async with self.pool.acquire() as conn:
            try:
                async with conn.transaction():
                    await conn.execute(sql, *vals)
                    await self._log_change(conn, None, f"{cfg['change']}_created",
                                           {'key': key, 'label': label})
            except asyncpg.UniqueViolationError:
                raise ValueError(f"{kind} already exists: {key}")
            except asyncpg.ForeignKeyViolationError:
                # relationship-types: inverse_key must reference an existing type.
                # For a mutual pair, create one side first (inverse empty), then the
                # other, then set the first's inverse via update.
                raise ValueError(
                    f"inverse_key '{inverse_key}' does not exist. Create that "
                    f"relationship type first (or leave inverse_key empty and set "
                    f"it once both exist).")
        return await self.get_metadata(kind, key)

    @with_db_retry()
    async def update_metadata(
        self, kind: str, key: str, *, label: Optional[str] = None,
        description: Optional[str] = None, is_active: Optional[bool] = None,
        inverse_key: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Edit label/description/is_active (and inverse_key for relationships).
        The key itself is immutable — it is the reference target."""
        cfg = _cfg(kind)
        sets, params = [], []
        if label is not None:
            params.append(label); sets.append(f"{cfg['label']} = ${len(params)}")
        if description is not None:
            params.append(description); sets.append(f"{cfg['desc']} = ${len(params)}")
        if is_active is not None:
            params.append(is_active); sets.append(f"is_active = ${len(params)}")
        if inverse_key is not None and cfg['inverse']:
            params.append(inverse_key); sets.append(f"{cfg['inverse']} = ${len(params)}")
        if not sets:
            return await self.get_metadata(kind, key)
        sets.append("updated_time = CURRENT_TIMESTAMP")
        params.append(key)
        sql = f"UPDATE {cfg['table']} SET {', '.join(sets)} WHERE {cfg['key']} = ${len(params)}"
        # try wraps the transaction — the inverse_key FK is deferred and fires at
        # commit (see create_metadata).
        async with self.pool.acquire() as conn:
            try:
                async with conn.transaction():
                    res = await conn.execute(sql, *params)
                    if res.endswith(" 0"):
                        return None
                    await self._log_change(conn, None, f"{cfg['change']}_updated", {'key': key})
            except asyncpg.ForeignKeyViolationError:
                raise ValueError(f"inverse_key '{inverse_key}' does not exist.")
        return await self.get_metadata(kind, key)

    @with_db_retry()
    async def delete_metadata(self, kind: str, key: str) -> bool:
        """Delete a metadata value. Refuses with MetadataInUseError if any record
        references it."""
        cfg = _cfg(kind)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                n = int(await conn.fetchval(cfg['usage'], key) or 0)
                if n > 0:
                    raise MetadataInUseError(kind, key, n)
                res = await conn.execute(
                    f"DELETE FROM {cfg['table']} WHERE {cfg['key']} = $1", key)
                if res.endswith(" 0"):
                    return False
                await self._log_change(conn, None, f"{cfg['change']}_deleted", {'key': key})
        return True

    # ------------------------------------------------------------------
    # Auto-registration — preserve "new type appears by being used"
    # ------------------------------------------------------------------

    async def register_metadata(self, conn, kind: str, key: str) -> None:
        """Upsert a tag value on first use, within the caller's transaction.
        No-op for non-auto-register kinds. Label defaults to the key; a human can
        rename it later via update_metadata."""
        cfg = _cfg(kind)
        if not cfg.get('auto_register') or not key:
            return
        await conn.execute(
            f"INSERT INTO {cfg['table']} ({cfg['key']}, {cfg['label']}) "
            f"VALUES ($1, $1) ON CONFLICT ({cfg['key']}) DO NOTHING",
            key)
