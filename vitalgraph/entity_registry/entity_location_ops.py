"""
Location operations mixin for the Entity Registry.

Includes location types, location CRUD, and location category operations.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class LocationMixin:
    """Location type, location CRUD, and location category methods."""

    # ------------------------------------------------------------------
    # Location Type operations
    # ------------------------------------------------------------------

    async def list_location_types(self) -> List[Dict[str, Any]]:
        """List all location types."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT location_type_id, type_key, type_label, type_description, "
                "created_time, updated_time FROM entity_location_type ORDER BY location_type_id"
            )
            return [dict(r) for r in rows]

    async def create_location_type(self, type_key: str, type_label: str,
                                   type_description: Optional[str] = None) -> Dict[str, Any]:
        """Create a new location type."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO entity_location_type (type_key, type_label, type_description) "
                "VALUES ($1, $2, $3) RETURNING *",
                type_key, type_label, type_description
            )
            await self._log_change(conn, None, 'location_type_created', {
                'type_key': type_key, 'type_label': type_label
            })
            return dict(row)

    async def _get_location_type_id(self, conn, type_key: str) -> Optional[int]:
        """Resolve location type_key to location_type_id."""
        return await conn.fetchval(
            "SELECT location_type_id FROM entity_location_type WHERE type_key = $1", type_key
        )

    # ------------------------------------------------------------------
    # Location CRUD
    # ------------------------------------------------------------------

    _LOCATION_FIELDS = [
        'location_name', 'description', 'address_line_1', 'address_line_2',
        'locality', 'admin_area_2', 'admin_area_1', 'country', 'country_code',
        'postal_code', 'formatted_address', 'latitude', 'longitude',
        'timezone', 'google_place_id', 'external_location_id',
        'effective_from', 'effective_to', 'is_primary', 'notes',
    ]

    async def _insert_location(
        self, conn, entity_id: str, location_type_key: str,
        created_by: Optional[str] = None, **kwargs,
    ) -> Dict[str, Any]:
        """Insert a location within an existing connection/transaction."""
        type_id = await self._get_location_type_id(conn, location_type_key)
        if type_id is None:
            raise ValueError(f"Unknown location type: {location_type_key}")

        is_primary = kwargs.get('is_primary', False)

        # Enforce single primary per entity
        if is_primary:
            await conn.execute(
                "UPDATE entity_location SET is_primary = FALSE "
                "WHERE entity_id = $1 AND is_primary = TRUE",
                entity_id
            )

        cols = ['entity_id', 'location_type_id', 'created_by']
        vals = [entity_id, type_id, created_by]
        for field in self._LOCATION_FIELDS:
            if field in kwargs and kwargs[field] is not None:
                cols.append(field)
                vals.append(kwargs[field])

        placeholders = ', '.join(f'${i}' for i in range(1, len(vals) + 1))
        col_str = ', '.join(cols)

        row = await conn.fetchrow(
            f"INSERT INTO entity_location ({col_str}) VALUES ({placeholders}) RETURNING *",
            *vals
        )
        location = dict(row)

        await self._log_change(conn, entity_id, 'location_created', {
            'location_id': location['location_id'],
            'location_name': kwargs.get('location_name'),
            'type_key': location_type_key,
        }, changed_by=created_by)

        return location

    async def create_location(
        self, entity_id: str, location_type_key: str,
        created_by: Optional[str] = None, **kwargs,
    ) -> Dict[str, Any]:
        """Add a location to an entity."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                exists = await conn.fetchval(
                    "SELECT 1 FROM entity WHERE entity_id = $1", entity_id
                )
                if not exists:
                    raise ValueError(f"Entity not found: {entity_id}")

                location = await self._insert_location(
                    conn, entity_id, location_type_key,
                    created_by=created_by, **kwargs,
                )
                result = await self._get_location_response(conn, location['location_id'])

        # Weaviate sync (outside transaction)
        if result:
            await self._weaviate_upsert_location(result)
        return result

    async def get_location(self, location_id: int) -> Optional[Dict[str, Any]]:
        """Get a single location by ID with type info and categories."""
        async with self.pool.acquire() as conn:
            return await self._get_location_response(conn, location_id)

    async def _get_location_response(self, conn, location_id: int) -> Optional[Dict[str, Any]]:
        """Build a full location response dict from the view."""
        row = await conn.fetchrow(
            "SELECT lv.*, lt.type_key AS location_type_key, lt.type_label AS location_type_label "
            "FROM entity_location_view lv "
            "JOIN entity_location_type lt ON lv.location_type_id = lt.location_type_id "
            "WHERE lv.location_id = $1",
            location_id
        )
        if row is None:
            return None
        location = dict(row)

        # Fetch categories
        cat_rows = await conn.fetch(
            "SELECT c.category_key, c.category_label "
            "FROM entity_location_category_map lcm "
            "JOIN category c ON lcm.category_id = c.category_id "
            "WHERE lcm.location_id = $1 AND lcm.status = 'active' "
            "ORDER BY c.category_key",
            location_id
        )
        location['categories'] = [dict(r) for r in cat_rows]
        return location

    async def update_location(self, location_id: int, updated_by: Optional[str] = None,
                              **kwargs) -> Optional[Dict[str, Any]]:
        """Update location fields. Only provided (non-None) kwargs are updated."""
        fields = {}
        for field in self._LOCATION_FIELDS:
            if field in kwargs and kwargs[field] is not None:
                fields[field] = kwargs[field]

        if not fields:
            return await self.get_location(location_id)

        fields['updated_time'] = datetime.now(timezone.utc)

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Get entity_id for logging and is_primary enforcement
                loc_row = await conn.fetchrow(
                    "SELECT entity_id FROM entity_location WHERE location_id = $1", location_id
                )
                if loc_row is None:
                    return None

                entity_id = loc_row['entity_id']

                # Enforce single primary
                if fields.get('is_primary'):
                    await conn.execute(
                        "UPDATE entity_location SET is_primary = FALSE "
                        "WHERE entity_id = $1 AND is_primary = TRUE AND location_id != $2",
                        entity_id, location_id
                    )

                set_parts = []
                values = []
                for i, (col, val) in enumerate(fields.items(), 1):
                    set_parts.append(f"{col} = ${i}")
                    values.append(val)

                values.append(location_id)
                param_idx = len(values)

                result = await conn.execute(
                    f"UPDATE entity_location SET {', '.join(set_parts)} WHERE location_id = ${param_idx}",
                    *values
                )
                if result == 'UPDATE 0':
                    return None

                await self._log_change(conn, entity_id, 'location_updated', {
                    'location_id': location_id,
                    'changed_fields': list(fields.keys()),
                }, changed_by=updated_by)

                result = await self._get_location_response(conn, location_id)

        # Weaviate sync (outside transaction)
        if result:
            await self._weaviate_upsert_location(result)
        return result

    async def remove_location(self, location_id: int,
                              removed_by: Optional[str] = None) -> bool:
        """Soft-remove a location (set status='removed')."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "UPDATE entity_location SET status = 'removed', updated_time = $1 "
                    "WHERE location_id = $2 AND status != 'removed' "
                    "RETURNING entity_id, location_name",
                    datetime.now(timezone.utc), location_id
                )
                if row is None:
                    return False

                await self._log_change(conn, row['entity_id'], 'location_removed', {
                    'location_id': location_id,
                    'location_name': row['location_name'],
                }, changed_by=removed_by)

        # Weaviate sync (outside transaction)
        await self._weaviate_delete_location(location_id, row['entity_id'])
        return True

    async def list_locations(self, entity_id: str,
                             include_expired: bool = False) -> List[Dict[str, Any]]:
        """List locations for an entity, using the view for is_active."""
        async with self.pool.acquire() as conn:
            if include_expired:
                sql = (
                    "SELECT lv.*, lt.type_key AS location_type_key, lt.type_label AS location_type_label "
                    "FROM entity_location_view lv "
                    "JOIN entity_location_type lt ON lv.location_type_id = lt.location_type_id "
                    "WHERE lv.entity_id = $1 AND lv.status = 'active' "
                    "ORDER BY lv.is_primary DESC, lv.location_id"
                )
            else:
                sql = (
                    "SELECT lv.*, lt.type_key AS location_type_key, lt.type_label AS location_type_label "
                    "FROM entity_location_view lv "
                    "JOIN entity_location_type lt ON lv.location_type_id = lt.location_type_id "
                    "WHERE lv.entity_id = $1 AND lv.status = 'active' AND lv.is_active = TRUE "
                    "ORDER BY lv.is_primary DESC, lv.location_id"
                )
            rows = await conn.fetch(sql, entity_id)
            results = []
            for row in rows:
                loc = dict(row)
                cat_rows = await conn.fetch(
                    "SELECT c.category_key, c.category_label "
                    "FROM entity_location_category_map lcm "
                    "JOIN category c ON lcm.category_id = c.category_id "
                    "WHERE lcm.location_id = $1 AND lcm.status = 'active' "
                    "ORDER BY c.category_key",
                    loc['location_id']
                )
                loc['categories'] = [dict(r) for r in cat_rows]
                results.append(loc)
            return results

    # ------------------------------------------------------------------
    # Location Category operations
    # ------------------------------------------------------------------

    async def add_location_category(
        self, location_id: int, category_key: str,
        created_by: Optional[str] = None, notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Assign a category to a location."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                loc_row = await conn.fetchrow(
                    "SELECT entity_id FROM entity_location WHERE location_id = $1", location_id
                )
                if loc_row is None:
                    raise ValueError(f"Location not found: {location_id}")

                cat_id = await conn.fetchval(
                    "SELECT category_id FROM category WHERE category_key = $1",
                    category_key
                )
                if cat_id is None:
                    raise ValueError(f"Category not found: {category_key}")

                row = await conn.fetchrow(
                    "INSERT INTO entity_location_category_map "
                    "(location_id, category_id, created_by, notes) "
                    "VALUES ($1, $2, $3, $4) "
                    "ON CONFLICT (location_id, category_id) DO UPDATE SET status = 'active' "
                    "RETURNING *",
                    location_id, cat_id, created_by, notes
                )
                await self._log_change(conn, loc_row['entity_id'], 'location_category_added', {
                    'location_id': location_id, 'category_key': category_key,
                }, changed_by=created_by)
                result = dict(row)
                result['category_key'] = category_key
                return result

    async def remove_location_category(
        self, location_id: int, category_key: str,
        removed_by: Optional[str] = None,
    ) -> bool:
        """Remove a category from a location."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                loc_row = await conn.fetchrow(
                    "SELECT entity_id FROM entity_location WHERE location_id = $1", location_id
                )
                if loc_row is None:
                    raise ValueError(f"Location not found: {location_id}")

                cat_id = await conn.fetchval(
                    "SELECT category_id FROM category WHERE category_key = $1",
                    category_key
                )
                if cat_id is None:
                    raise ValueError(f"Category not found: {category_key}")

                result = await conn.execute(
                    "UPDATE entity_location_category_map SET status = 'removed' "
                    "WHERE location_id = $1 AND category_id = $2 AND status = 'active'",
                    location_id, cat_id
                )
                if result == 'UPDATE 0':
                    return False

                await self._log_change(conn, loc_row['entity_id'], 'location_category_removed', {
                    'location_id': location_id, 'category_key': category_key,
                }, changed_by=removed_by)
                return True

    async def search_locations_by_external_id(
        self, external_location_id: str,
        entity_id: Optional[str] = None,
        include_expired: bool = False,
    ) -> List[Dict[str, Any]]:
        """Look up locations by external_location_id via PostgreSQL.

        Args:
            external_location_id: Business-assigned location reference to search for.
            entity_id: Optional filter to a specific entity.
            include_expired: If True, include locations outside their effective dates.

        Returns:
            List of location dicts with type info and categories.
        """
        async with self.pool.acquire() as conn:
            conditions = [
                "lv.status = 'active'",
                "lv.external_location_id = $1",
            ]
            params: list = [external_location_id]

            if entity_id:
                params.append(entity_id)
                conditions.append(f"lv.entity_id = ${len(params)}")

            if not include_expired:
                conditions.append("lv.is_active = TRUE")

            where = " AND ".join(conditions)

            sql = (
                "SELECT lv.*, lt.type_key AS location_type_key, "
                "lt.type_label AS location_type_label "
                "FROM entity_location_view lv "
                "JOIN entity_location_type lt ON lv.location_type_id = lt.location_type_id "
                f"WHERE {where} "
                "ORDER BY lv.is_primary DESC, lv.location_id"
            )
            rows = await conn.fetch(sql, *params)
            results = []
            for row in rows:
                loc = dict(row)
                cat_rows = await conn.fetch(
                    "SELECT c.category_key, c.category_label "
                    "FROM entity_location_category_map lcm "
                    "JOIN category c ON lcm.category_id = c.category_id "
                    "WHERE lcm.location_id = $1 AND lcm.status = 'active' "
                    "ORDER BY c.category_key",
                    loc['location_id']
                )
                loc['categories'] = [dict(r) for r in cat_rows]
                results.append(loc)
            return results

    async def list_location_categories(self, location_id: int) -> List[Dict[str, Any]]:
        """List all active categories for a location."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT lcm.location_category_map_id, lcm.location_id, lcm.status, "
                "lcm.created_time, lcm.created_by, lcm.notes, "
                "c.category_key, c.category_label, c.category_description "
                "FROM entity_location_category_map lcm "
                "JOIN category c ON lcm.category_id = c.category_id "
                "WHERE lcm.location_id = $1 AND lcm.status = 'active' "
                "ORDER BY c.category_key",
                location_id
            )
            return [dict(r) for r in rows]
