"""
Entity Registry Search — pgvector/PostGIS/FTS implementation.

Replaces EntityWeaviateIndex search methods with PostgreSQL-native equivalents.
Provides vector similarity, hybrid (BM25 + vector), geo radius, and combined searches.
"""

import logging
from typing import Any, Dict, List, Optional

import asyncpg

from vitalgraph.entity_registry.entity_registry_vector_schema import (
    ENTITY_VECTOR_TABLE, LOCATION_VECTOR_TABLE, GEO_TABLE,
    FTS_ENTITY_TABLE, FTS_LOCATION_TABLE,
)
from vitalgraph.vectorization.registry import get_provider

logger = logging.getLogger(__name__)


class EntityRegistrySearch:
    """PostgreSQL-native search for the entity registry.

    Drop-in replacement for EntityWeaviateIndex search methods.
    """

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self._provider = get_provider("vitalsigns", cache_key="entity_registry_search")

    # ==================================================================
    # Topic search (vector similarity)
    # ==================================================================

    async def search_topic(
        self,
        query: str,
        type_key: Optional[str] = None,
        category_key: Optional[str] = None,
        country: Optional[str] = None,
        region: Optional[str] = None,
        locality: Optional[str] = None,
        limit: int = 20,
        min_certainty: float = 0.7,
        identifier_value: Optional[str] = None,
        identifier_namespace: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Semantic vector search on entities.

        Returns list of entity dicts with score (cosine similarity).
        """
        # Vectorize query
        query_vec = await self._provider.vectorize_text(query)
        query_vec_str = f"[{','.join(str(v) for v in query_vec)}]"

        # Min distance threshold: cosine distance = 1 - similarity
        max_distance = 1.0 - min_certainty

        # Build filter clauses
        filters = []
        params: list = [query_vec_str, max_distance, limit]
        param_idx = 4

        if type_key:
            filters.append(f"e.type_key = ${param_idx}")
            params.append(type_key)
            param_idx += 1
        if category_key:
            filters.append(f"""
                EXISTS (SELECT 1 FROM entity_category_map ecm
                        JOIN category c ON c.category_id = ecm.category_id
                        WHERE ecm.entity_id = e.entity_id AND c.category_key = ${param_idx})
            """)
            params.append(category_key)
            param_idx += 1
        if country:
            filters.append(f"e.country = ${param_idx}")
            params.append(country)
            param_idx += 1
        if region:
            filters.append(f"e.region = ${param_idx}")
            params.append(region)
            param_idx += 1
        if locality:
            filters.append(f"e.locality = ${param_idx}")
            params.append(locality)
            param_idx += 1
        if identifier_value:
            id_filter = f"""
                EXISTS (SELECT 1 FROM entity_identifier ei
                        WHERE ei.entity_id = e.entity_id
                        AND ei.identifier_value = ${param_idx}
            """
            params.append(identifier_value)
            param_idx += 1
            if identifier_namespace:
                id_filter += f" AND ei.identifier_namespace = ${param_idx}"
                params.append(identifier_namespace)
                param_idx += 1
            id_filter += ")"
            filters.append(id_filter)

        where_clause = " AND ".join(filters) if filters else "TRUE"

        sql = f"""
            SELECT e.entity_id, e.primary_name, e.description,
                   e.country, e.region, e.locality,
                   et.type_key, et.type_label,
                   v.search_text,
                   1.0 - (v.embedding <=> $1::vector) AS score
            FROM {ENTITY_VECTOR_TABLE} v
            JOIN entity e ON e.entity_id = v.entity_id
            JOIN entity_type et ON et.type_id = e.entity_type_id
            WHERE (v.embedding <=> $1::vector) <= $2
              AND e.status = 'active'
              AND {where_clause}
            ORDER BY v.embedding <=> $1::vector
            LIMIT $3
        """

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

        return [dict(row) for row in rows]

    # ==================================================================
    # Hybrid search (BM25 + vector weighted fusion)
    # ==================================================================

    async def search_hybrid(
        self,
        query: str,
        alpha: float = 0.5,
        type_key: Optional[str] = None,
        category_key: Optional[str] = None,
        country: Optional[str] = None,
        region: Optional[str] = None,
        locality: Optional[str] = None,
        limit: int = 20,
        min_certainty: float = 0.5,
        identifier_value: Optional[str] = None,
        identifier_namespace: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Hybrid search: weighted combination of vector similarity and BM25.

        alpha: Weight for vector score (0=pure BM25, 1=pure vector).
        """
        query_vec = await self._provider.vectorize_text(query)
        query_vec_str = f"[{','.join(str(v) for v in query_vec)}]"

        # Build filter clauses on entity table
        filters = []
        params: list = [query_vec_str, query, limit]
        param_idx = 4

        if type_key:
            filters.append(f"e.type_key = ${param_idx}")
            params.append(type_key)
            param_idx += 1
        if category_key:
            filters.append(f"""
                EXISTS (SELECT 1 FROM entity_category_map ecm
                        JOIN category c ON c.category_id = ecm.category_id
                        WHERE ecm.entity_id = e.entity_id AND c.category_key = ${param_idx})
            """)
            params.append(category_key)
            param_idx += 1
        if country:
            filters.append(f"e.country = ${param_idx}")
            params.append(country)
            param_idx += 1
        if region:
            filters.append(f"e.region = ${param_idx}")
            params.append(region)
            param_idx += 1
        if locality:
            filters.append(f"e.locality = ${param_idx}")
            params.append(locality)
            param_idx += 1
        if identifier_value:
            id_filter = f"""
                EXISTS (SELECT 1 FROM entity_identifier ei
                        WHERE ei.entity_id = e.entity_id
                        AND ei.identifier_value = ${param_idx}
            """
            params.append(identifier_value)
            param_idx += 1
            if identifier_namespace:
                id_filter += f" AND ei.identifier_namespace = ${param_idx}"
                params.append(identifier_namespace)
                param_idx += 1
            id_filter += ")"
            filters.append(id_filter)

        where_clause = " AND ".join(filters) if filters else "TRUE"

        sql = f"""
            WITH vec_scores AS (
                SELECT v.entity_id,
                       1.0 - (v.embedding <=> $1::vector) AS vec_score
                FROM {ENTITY_VECTOR_TABLE} v
            ),
            fts_scores AS (
                SELECT f.entity_id,
                       ts_rank(f.tsv, plainto_tsquery('english', $2)) AS fts_score
                FROM {FTS_ENTITY_TABLE} f
                WHERE f.tsv @@ plainto_tsquery('english', $2)
            ),
            combined AS (
                SELECT COALESCE(vs.entity_id, fs.entity_id) AS entity_id,
                       {alpha} * COALESCE(vs.vec_score, 0) +
                       {1.0 - alpha} * COALESCE(fs.fts_score, 0) AS hybrid_score
                FROM vec_scores vs
                FULL OUTER JOIN fts_scores fs ON vs.entity_id = fs.entity_id
                WHERE COALESCE(vs.vec_score, 0) > 0 OR COALESCE(fs.fts_score, 0) > 0
            )
            SELECT e.entity_id, e.primary_name, e.description,
                   e.country, e.region, e.locality,
                   et.type_key, et.type_label,
                   c.hybrid_score AS score
            FROM combined c
            JOIN entity e ON e.entity_id = c.entity_id
            JOIN entity_type et ON et.type_id = e.entity_type_id
            WHERE e.status = 'active'
              AND {where_clause}
            ORDER BY c.hybrid_score DESC
            LIMIT $3
        """

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

        return [dict(row) for row in rows]

    # ==================================================================
    # Geo search — locations near a point
    # ==================================================================

    async def search_locations_near(
        self,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        radius_km: Optional[float] = None,
        q: Optional[str] = None,
        address: Optional[str] = None,
        location_type_key: Optional[str] = None,
        country_code: Optional[str] = None,
        locality: Optional[str] = None,
        admin_area_1: Optional[str] = None,
        postal_code: Optional[str] = None,
        location_name: Optional[str] = None,
        entity_id: Optional[str] = None,
        is_primary: Optional[bool] = None,
        external_location_id: Optional[str] = None,
        type_key: Optional[str] = None,
        min_certainty: float = 0.5,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Find locations within radius_km of a point.

        Supports:
          - geo radius (latitude/longitude/radius_km)
          - semantic search (q) via vector similarity
          - address keyword search (address) via FTS
          - property filters (location_type_key, country_code, locality, etc.)

        Returns location dicts with distance_km when geo is provided.
        """
        has_geo = latitude is not None and longitude is not None and radius_km is not None

        params: list = []
        param_idx = 1

        # Geo params (positions $1, $2, $3 if present)
        if has_geo:
            radius_meters = radius_km * 1000.0  # type: ignore[operator]
            params.extend([longitude, latitude, radius_meters])
            param_idx = 4
            geo_lon_param = "$1"
            geo_lat_param = "$2"
            geo_radius_param = "$3"

        # Limit param
        limit_param_idx = param_idx
        params.append(limit)
        param_idx += 1

        # Build filter clauses
        filters = []
        if location_type_key:
            filters.append(f"elt.type_key = ${param_idx}")
            params.append(location_type_key)
            param_idx += 1
        if type_key:
            filters.append(f"et.type_key = ${param_idx}")
            params.append(type_key)
            param_idx += 1
        if country_code:
            filters.append(f"el.country = ${param_idx}")
            params.append(country_code)
            param_idx += 1
        if locality:
            filters.append(f"el.locality = ${param_idx}")
            params.append(locality)
            param_idx += 1
        if admin_area_1:
            filters.append(f"el.admin_area_1 = ${param_idx}")
            params.append(admin_area_1)
            param_idx += 1
        if postal_code:
            filters.append(f"el.postal_code = ${param_idx}")
            params.append(postal_code)
            param_idx += 1
        if location_name:
            filters.append(f"el.location_name ILIKE ${param_idx}")
            params.append(f"%{location_name}%")
            param_idx += 1
        if entity_id:
            filters.append(f"el.entity_id = ${param_idx}")
            params.append(entity_id)
            param_idx += 1
        if is_primary is not None:
            filters.append(f"el.is_primary = ${param_idx}")
            params.append(is_primary)
            param_idx += 1
        if external_location_id:
            filters.append(f"el.external_location_id = ${param_idx}")
            params.append(external_location_id)
            param_idx += 1

        where_clause = " AND ".join(filters) if filters else "TRUE"

        # Optional semantic filter via vector similarity
        vec_join = ""
        vec_order = ""
        if q:
            query_vec = await self._provider.vectorize_text(q)
            query_vec_str = f"[{','.join(str(v) for v in query_vec)}]"
            params.append(query_vec_str)
            vec_join = f"""
                JOIN {LOCATION_VECTOR_TABLE} lv ON lv.location_id = el.location_id
            """
            vec_order = f", lv.embedding <=> ${param_idx}::vector"
            param_idx += 1

        # Optional address keyword search via FTS
        fts_join = ""
        fts_order = ""
        if address:
            params.append(address)
            fts_join = f"""
                JOIN {FTS_LOCATION_TABLE} fl ON fl.location_id = el.location_id
            """
            filters_fts = f"fl.tsv @@ plainto_tsquery('english', ${param_idx})"
            param_idx += 1
        else:
            filters_fts = None

        # Build geo-dependent clauses
        if has_geo:
            geo_join = f"""
                JOIN {GEO_TABLE} g ON g.source_id = CAST(el.location_id AS TEXT)
                    AND g.source_type = 'location'
            """
            geo_where = f"""
                ST_DWithin(
                    g.location,
                    ST_SetSRID(ST_MakePoint({geo_lon_param}, {geo_lat_param}), 4326)::geography,
                    {geo_radius_param}
                )
            """
            distance_col = f"""
                ST_Distance(
                    g.location,
                    ST_SetSRID(ST_MakePoint({geo_lon_param}, {geo_lat_param}), 4326)::geography
                ) / 1000.0 AS distance_km,
            """
            geo_order = f"ST_Distance(g.location, ST_SetSRID(ST_MakePoint({geo_lon_param}, {geo_lat_param}), 4326)::geography)"
        else:
            geo_join = ""
            geo_where = "TRUE"
            distance_col = "0.0 AS distance_km,"
            geo_order = "el.location_id"

        # Combine FTS filter into where_clause
        all_where_parts = [geo_where, "el.status = 'active'", "e.status = 'active'", where_clause]
        if filters_fts:
            all_where_parts.append(filters_fts)
        full_where = " AND ".join(all_where_parts)

        sql = f"""
            SELECT el.location_id, el.entity_id, el.location_name,
                   el.formatted_address, el.address_line_1, el.address_line_2,
                   el.locality, el.admin_area_1, el.country AS country_code,
                   el.postal_code, el.latitude, el.longitude,
                   el.is_primary, el.external_location_id,
                   {distance_col}
                   elt.type_key AS location_type_key
            FROM entity_location el
            JOIN entity_location_type elt ON elt.location_type_id = el.location_type_id
            JOIN entity e ON e.entity_id = el.entity_id
            JOIN entity_type et ON et.type_id = e.entity_type_id
            {geo_join}
            {vec_join}
            {fts_join}
            WHERE {full_where}
            ORDER BY {geo_order} {vec_order} {fts_order}
            LIMIT ${limit_param_idx}
        """

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

        return [dict(row) for row in rows]

    # ==================================================================
    # Entities near a point (via their locations)
    # ==================================================================

    async def search_entities_near(
        self,
        latitude: float,
        longitude: float,
        radius_km: float,
        type_key: Optional[str] = None,
        limit: int = 20,
        identifier_value: Optional[str] = None,
        identifier_namespace: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Find entities that have at least one location within radius_km.

        Returns entity dicts with closest location info.
        """
        radius_meters = radius_km * 1000.0
        params: list = [longitude, latitude, radius_meters, limit]
        param_idx = 5

        filters = []
        if type_key:
            filters.append(f"et.type_key = ${param_idx}")
            params.append(type_key)
            param_idx += 1
        if identifier_value:
            id_filter = f"""
                EXISTS (SELECT 1 FROM entity_identifier ei
                        WHERE ei.entity_id = e.entity_id
                        AND ei.identifier_value = ${param_idx}
            """
            params.append(identifier_value)
            param_idx += 1
            if identifier_namespace:
                id_filter += f" AND ei.identifier_namespace = ${param_idx}"
                params.append(identifier_namespace)
                param_idx += 1
            id_filter += ")"
            filters.append(id_filter)

        where_clause = " AND ".join(filters) if filters else "TRUE"

        sql = f"""
            WITH nearby_geo AS (
                SELECT g.entity_id, g.source_type, g.source_id,
                       g.latitude, g.longitude,
                       ST_Distance(
                           g.location,
                           ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography
                       ) / 1000.0 AS distance_km
                FROM {GEO_TABLE} g
                WHERE ST_DWithin(
                    g.location,
                    ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography,
                    $3
                )
            ),
            closest AS (
                SELECT DISTINCT ON (entity_id)
                       entity_id, source_type, source_id, latitude, longitude, distance_km
                FROM nearby_geo
                ORDER BY entity_id, distance_km
            )
            SELECT e.entity_id, e.primary_name, e.description,
                   e.country, e.region, e.locality,
                   et.type_key, et.type_label,
                   cl.distance_km, cl.latitude AS closest_lat, cl.longitude AS closest_lon,
                   cl.source_type, cl.source_id
            FROM closest cl
            JOIN entity e ON e.entity_id = cl.entity_id
            JOIN entity_type et ON et.type_id = e.entity_type_id
            WHERE e.status = 'active'
              AND {where_clause}
            ORDER BY cl.distance_km
            LIMIT $4
        """

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

        return [dict(row) for row in rows]

    # ==================================================================
    # Combined: topic + geo (vector similarity within geo radius)
    # ==================================================================

    async def search_topic_near(
        self,
        query: str,
        latitude: float,
        longitude: float,
        radius_km: float,
        type_key: Optional[str] = None,
        category_key: Optional[str] = None,
        limit: int = 20,
        min_certainty: float = 0.5,
        identifier_value: Optional[str] = None,
        identifier_namespace: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Combined semantic + geo search.

        Finds entities that are semantically similar to query AND have a location
        within radius_km. Returns results sorted by vector similarity.
        """
        query_vec = await self._provider.vectorize_text(query)
        query_vec_str = f"[{','.join(str(v) for v in query_vec)}]"
        radius_meters = radius_km * 1000.0
        max_distance = 1.0 - min_certainty

        params: list = [query_vec_str, longitude, latitude, radius_meters, max_distance, limit]
        param_idx = 7

        filters = []
        if type_key:
            filters.append(f"e.type_key = ${param_idx}")
            params.append(type_key)
            param_idx += 1
        if category_key:
            filters.append(f"""
                EXISTS (SELECT 1 FROM entity_category_map ecm
                        JOIN category c ON c.category_id = ecm.category_id
                        WHERE ecm.entity_id = e.entity_id AND c.category_key = ${param_idx})
            """)
            params.append(category_key)
            param_idx += 1
        if identifier_value:
            id_filter = f"""
                EXISTS (SELECT 1 FROM entity_identifier ei
                        WHERE ei.entity_id = e.entity_id
                        AND ei.identifier_value = ${param_idx}
            """
            params.append(identifier_value)
            param_idx += 1
            if identifier_namespace:
                id_filter += f" AND ei.identifier_namespace = ${param_idx}"
                params.append(identifier_namespace)
                param_idx += 1
            id_filter += ")"
            filters.append(id_filter)

        where_clause = " AND ".join(filters) if filters else "TRUE"

        sql = f"""
            WITH geo_entities AS (
                SELECT DISTINCT entity_id
                FROM {GEO_TABLE}
                WHERE ST_DWithin(
                    location,
                    ST_SetSRID(ST_MakePoint($2, $3), 4326)::geography,
                    $4
                )
            )
            SELECT e.entity_id, e.primary_name, e.description,
                   e.country, e.region, e.locality,
                   et.type_key, et.type_label,
                   v.search_text,
                   1.0 - (v.embedding <=> $1::vector) AS score
            FROM {ENTITY_VECTOR_TABLE} v
            JOIN entity e ON e.entity_id = v.entity_id
            JOIN entity_type et ON et.type_id = e.entity_type_id
            JOIN geo_entities ge ON ge.entity_id = e.entity_id
            WHERE (v.embedding <=> $1::vector) <= $5
              AND e.status = 'active'
              AND {where_clause}
            ORDER BY v.embedding <=> $1::vector
            LIMIT $6
        """

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

            # Enrich with location data for each entity
            results = []
            for row in rows:
                result = dict(row)
                # Fetch closest locations within radius
                locs = await conn.fetch(f"""
                    SELECT el.location_id, el.location_name, el.formatted_address,
                           el.latitude, el.longitude,
                           ST_Distance(
                               g.location,
                               ST_SetSRID(ST_MakePoint($2, $3), 4326)::geography
                           ) / 1000.0 AS distance_km
                    FROM {GEO_TABLE} g
                    JOIN entity_location el ON el.location_id = CAST(g.source_id AS INTEGER)
                        AND g.source_type = 'location'
                    WHERE g.entity_id = $1
                      AND ST_DWithin(g.location, ST_SetSRID(ST_MakePoint($2, $3), 4326)::geography, $4)
                    ORDER BY distance_km
                    LIMIT 5
                """, result['entity_id'], longitude, latitude, radius_meters)
                result['locations'] = [dict(loc) for loc in locs]
                results.append(result)

        return results

    # ==================================================================
    # Identifier search (exact match, no vector)
    # ==================================================================

    async def search_by_identifier(
        self,
        identifier_value: str,
        identifier_namespace: Optional[str] = None,
        type_key: Optional[str] = None,
        category_key: Optional[str] = None,
        country: Optional[str] = None,
        region: Optional[str] = None,
        locality: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Search entities by external identifier value."""
        params: list = [identifier_value, limit]
        param_idx = 3

        filters = ["ei.identifier_value = $1"]
        if identifier_namespace:
            filters.append(f"ei.identifier_namespace = ${param_idx}")
            params.append(identifier_namespace)
            param_idx += 1
        if type_key:
            filters.append(f"et.type_key = ${param_idx}")
            params.append(type_key)
            param_idx += 1
        if category_key:
            filters.append(f"""
                EXISTS (SELECT 1 FROM entity_category_map ecm
                        JOIN category c ON c.category_id = ecm.category_id
                        WHERE ecm.entity_id = e.entity_id AND c.category_key = ${param_idx})
            """)
            params.append(category_key)
            param_idx += 1
        if country:
            filters.append(f"e.country = ${param_idx}")
            params.append(country)
            param_idx += 1
        if region:
            filters.append(f"e.region = ${param_idx}")
            params.append(region)
            param_idx += 1
        if locality:
            filters.append(f"e.locality = ${param_idx}")
            params.append(locality)
            param_idx += 1

        where_clause = " AND ".join(filters)

        sql = f"""
            SELECT DISTINCT e.entity_id, e.primary_name, e.description,
                   e.country, e.region, e.locality,
                   et.type_key, et.type_label
            FROM entity_identifier ei
            JOIN entity e ON e.entity_id = ei.entity_id
            JOIN entity_type et ON et.type_id = e.entity_type_id
            WHERE {where_clause}
              AND e.status = 'active'
            ORDER BY e.primary_name
            LIMIT $2
        """

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

        return [dict(row) for row in rows]
