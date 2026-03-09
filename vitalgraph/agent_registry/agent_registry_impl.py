"""
Core Agent Registry implementation.

Async operations using asyncpg, sharing the connection pool
from the backend. Provides full CRUD for agents, endpoints,
and agent types with soft-delete semantics and change logging.
"""

import json
import logging
import secrets
import string
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import asyncpg

logger = logging.getLogger(__name__)

# Agent ID generation
_ALPHABET = string.ascii_lowercase + string.digits
_PREFIX = "agt_"
_SUFFIX_LENGTH = 10


def generate_agent_id(length: int = _SUFFIX_LENGTH) -> str:
    """Generate a unique agent ID like 'agt_a7b3x9k2m1'."""
    suffix = ''.join(secrets.choice(_ALPHABET) for _ in range(length))
    return f"{_PREFIX}{suffix}"


class AgentRegistryImpl:
    """
    Core agent registry operations.

    All methods are async and use a shared asyncpg connection pool.
    """

    def __init__(self, connection_pool: asyncpg.Pool):
        self.pool = connection_pool

    # ------------------------------------------------------------------
    # Schema verification
    # ------------------------------------------------------------------

    async def ensure_tables(self) -> bool:
        """Verify that agent registry tables exist. Does NOT create or modify schema.

        Run agent_registry/migrate_agents.py to create tables.
        """
        try:
            async with self.pool.acquire() as conn:
                exists = await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_name = 'agent')"
                )
                if not exists:
                    raise RuntimeError(
                        "Agent registry tables not found. "
                        "Run 'python agent_registry/migrate_agents.py' to create them."
                    )
            logger.info("Agent registry tables verified")
            return True
        except Exception as e:
            logger.error("Failed to ensure agent registry tables: %s", e)
            return False

    # ------------------------------------------------------------------
    # Change log
    # ------------------------------------------------------------------

    async def _log_change(
        self,
        conn,
        agent_id: Optional[str],
        change_type: str,
        change_detail: Optional[Dict[str, Any]] = None,
        changed_by: Optional[str] = None,
        comment: Optional[str] = None,
    ):
        """Insert a change log entry."""
        await conn.execute(
            "INSERT INTO agent_change_log "
            "(agent_id, change_type, change_detail, changed_by, comment) "
            "VALUES ($1, $2, $3::jsonb, $4, $5)",
            agent_id,
            change_type,
            json.dumps(change_detail) if change_detail else None,
            changed_by,
            comment,
        )

    # ------------------------------------------------------------------
    # Agent Type operations
    # ------------------------------------------------------------------

    async def list_agent_types(self) -> List[Dict[str, Any]]:
        """List all agent types."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT type_id, type_key, type_label, type_description, "
                "created_time, updated_time FROM agent_type ORDER BY type_id"
            )
            return [dict(r) for r in rows]

    async def create_agent_type(
        self,
        type_key: str,
        type_label: str,
        type_description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new agent type."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO agent_type (type_key, type_label, type_description) "
                "VALUES ($1, $2, $3) RETURNING *",
                type_key, type_label, type_description,
            )
            await self._log_change(conn, None, 'agent_type_created', {
                'type_key': type_key, 'type_label': type_label,
            })
            return dict(row)

    async def _get_agent_type_id(self, conn, type_key: str) -> Optional[int]:
        """Resolve type_key to type_id."""
        return await conn.fetchval(
            "SELECT type_id FROM agent_type WHERE type_key = $1", type_key
        )

    # ------------------------------------------------------------------
    # Agent CRUD
    # ------------------------------------------------------------------

    async def create_agent(
        self,
        agent_type_key: str,
        agent_name: str,
        agent_uri: str,
        entity_id: Optional[str] = None,
        description: Optional[str] = None,
        version: Optional[str] = None,
        protocol_format_uri: Optional[str] = None,
        auth_service_uri: Optional[str] = None,
        auth_service_config: Optional[Dict[str, Any]] = None,
        capabilities: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        notes: Optional[str] = None,
        created_by: Optional[str] = None,
        endpoints: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Create a new agent with a generated unique ID.

        Optionally creates initial endpoints in the same transaction.

        Returns:
            Agent dict including agent_id.

        Raises:
            ValueError: If agent_type_key is invalid.
        """
        auth_config_json = json.dumps(auth_service_config) if auth_service_config else '{}'
        capabilities_json = json.dumps(capabilities) if capabilities else '[]'
        metadata_json = json.dumps(metadata) if metadata else '{}'

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                type_id = await self._get_agent_type_id(conn, agent_type_key)
                if type_id is None:
                    raise ValueError(f"Unknown agent type: {agent_type_key}")

                # Generate unique ID with retry on collision
                agent_id = None
                for _ in range(5):
                    candidate = generate_agent_id()
                    exists = await conn.fetchval(
                        "SELECT 1 FROM agent WHERE agent_id = $1", candidate
                    )
                    if not exists:
                        agent_id = candidate
                        break
                if agent_id is None:
                    raise RuntimeError("Failed to generate unique agent ID after 5 attempts")

                row = await conn.fetchrow(
                    "INSERT INTO agent (agent_id, agent_type_id, entity_id, agent_name, "
                    "agent_uri, description, version, protocol_format_uri, "
                    "auth_service_uri, auth_service_config, capabilities, metadata, "
                    "created_by, notes) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, "
                    "$11::jsonb, $12::jsonb, $13, $14) RETURNING *",
                    agent_id, type_id, entity_id, agent_name,
                    agent_uri, description, version, protocol_format_uri,
                    auth_service_uri, auth_config_json, capabilities_json,
                    metadata_json, created_by, notes,
                )
                agent = dict(row)

                await self._log_change(conn, agent_id, 'agent_created', {
                    'agent_type_key': agent_type_key,
                    'agent_name': agent_name,
                    'agent_uri': agent_uri,
                }, changed_by=created_by)

                # Create initial endpoints
                if endpoints:
                    for ep in endpoints:
                        await self._insert_endpoint(conn, agent_id, **ep)

                return agent

    async def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        Get agent by ID, including type info and endpoints.
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT a.*, at.type_key AS agent_type_key, at.type_label AS agent_type_label "
                "FROM agent a JOIN agent_type at ON a.agent_type_id = at.type_id "
                "WHERE a.agent_id = $1",
                agent_id,
            )
            if row is None:
                return None

            agent = dict(row)
            _ensure_json_fields(agent)

            # Fetch endpoints
            ep_rows = await conn.fetch(
                "SELECT * FROM agent_endpoint WHERE agent_id = $1 AND status != 'deleted' "
                "ORDER BY endpoint_id",
                agent_id,
            )
            agent['endpoints'] = [dict(r) for r in ep_rows]

            return agent

    async def get_agent_by_uri(self, agent_uri: str) -> Optional[Dict[str, Any]]:
        """Get agent by agent_uri."""
        async with self.pool.acquire() as conn:
            agent_id = await conn.fetchval(
                "SELECT agent_id FROM agent WHERE agent_uri = $1", agent_uri
            )
            if agent_id is None:
                return None
        return await self.get_agent(agent_id)

    async def update_agent(
        self,
        agent_id: str,
        agent_type_key: Optional[str] = None,
        entity_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        description: Optional[str] = None,
        version: Optional[str] = None,
        status: Optional[str] = None,
        protocol_format_uri: Optional[str] = None,
        auth_service_uri: Optional[str] = None,
        auth_service_config: Optional[Dict[str, Any]] = None,
        capabilities: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        notes: Optional[str] = None,
        updated_by: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Update agent fields. Only provided (non-None) fields are updated.

        Returns:
            Updated agent dict, or None if agent not found.
        """
        fields: Dict[str, Any] = {}

        if agent_name is not None:
            fields['agent_name'] = agent_name
        if description is not None:
            fields['description'] = description
        if version is not None:
            fields['version'] = version
        if status is not None:
            valid = ('active', 'inactive', 'deprecated', 'deleted')
            if status not in valid:
                raise ValueError(f"Invalid agent status: {status}. Must be one of {valid}")
            fields['status'] = status
        if protocol_format_uri is not None:
            fields['protocol_format_uri'] = protocol_format_uri
        if auth_service_uri is not None:
            fields['auth_service_uri'] = auth_service_uri
        if auth_service_config is not None:
            fields['auth_service_config'] = json.dumps(auth_service_config)
        if capabilities is not None:
            fields['capabilities'] = json.dumps(capabilities)
        if metadata is not None:
            fields['metadata'] = json.dumps(metadata)
        if notes is not None:
            fields['notes'] = notes
        if entity_id is not None:
            fields['entity_id'] = entity_id

        if not fields and agent_type_key is None:
            return await self.get_agent(agent_id)

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Resolve agent_type_key if provided
                if agent_type_key is not None:
                    type_id = await self._get_agent_type_id(conn, agent_type_key)
                    if type_id is None:
                        raise ValueError(f"Unknown agent type: {agent_type_key}")
                    fields['agent_type_id'] = type_id

                fields['updated_time'] = datetime.now(timezone.utc)

                set_parts = []
                values = []
                for i, (col, val) in enumerate(fields.items(), 1):
                    cast = '::jsonb' if col in ('auth_service_config', 'capabilities', 'metadata') else ''
                    set_parts.append(f"{col} = ${i}{cast}")
                    values.append(val)

                values.append(agent_id)
                param_idx = len(values)

                result = await conn.execute(
                    f"UPDATE agent SET {', '.join(set_parts)} WHERE agent_id = ${param_idx}",
                    *values,
                )

                if result == 'UPDATE 0':
                    return None

                await self._log_change(conn, agent_id, 'agent_updated', {
                    'fields': list(fields.keys()),
                }, changed_by=updated_by)

        return await self.get_agent(agent_id)

    async def delete_agent(
        self,
        agent_id: str,
        deleted_by: Optional[str] = None,
        comment: Optional[str] = None,
    ) -> bool:
        """
        Soft-delete an agent (set status='deleted').

        Returns:
            True if agent was found and deleted, False otherwise.
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                result = await conn.execute(
                    "UPDATE agent SET status = 'deleted', updated_time = $1 "
                    "WHERE agent_id = $2 AND status != 'deleted'",
                    datetime.now(timezone.utc), agent_id,
                )
                if result == 'UPDATE 0':
                    return False

                await self._log_change(
                    conn, agent_id, 'agent_deleted', None,
                    changed_by=deleted_by, comment=comment,
                )
                return True

    # ------------------------------------------------------------------
    # Search / List
    # ------------------------------------------------------------------

    async def search_agents(
        self,
        query: Optional[str] = None,
        type_key: Optional[str] = None,
        status: Optional[str] = 'active',
        entity_id: Optional[str] = None,
        capability: Optional[str] = None,
        protocol_format_uri: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Search/list agents with filters and pagination.

        Returns:
            Tuple of (agents list, total count).
        """
        conditions = []
        params = []
        param_idx = 0

        if status:
            param_idx += 1
            conditions.append(f"a.status = ${param_idx}")
            params.append(status)

        if type_key:
            param_idx += 1
            conditions.append(f"at.type_key = ${param_idx}")
            params.append(type_key)

        if entity_id:
            param_idx += 1
            conditions.append(f"a.entity_id = ${param_idx}")
            params.append(entity_id)

        if capability:
            param_idx += 1
            conditions.append(f"a.capabilities @> ${param_idx}::jsonb")
            params.append(json.dumps([capability]))

        if protocol_format_uri:
            param_idx += 1
            conditions.append(f"a.protocol_format_uri = ${param_idx}")
            params.append(protocol_format_uri)

        if query:
            param_idx += 1
            query_param = f"%{query}%"
            conditions.append(
                f"(a.agent_name ILIKE ${param_idx} OR "
                f"a.agent_uri ILIKE ${param_idx} OR "
                f"a.description ILIKE ${param_idx})"
            )
            params.append(query_param)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""

        async with self.pool.acquire() as conn:
            # Count
            count_sql = (
                f"SELECT COUNT(*) FROM agent a "
                f"JOIN agent_type at ON a.agent_type_id = at.type_id {where}"
            )
            total = await conn.fetchval(count_sql, *params)

            # Fetch page
            offset = (page - 1) * page_size
            param_idx += 1
            params.append(page_size)
            limit_param = param_idx
            param_idx += 1
            params.append(offset)
            offset_param = param_idx

            data_sql = (
                f"SELECT a.*, at.type_key AS agent_type_key, at.type_label AS agent_type_label "
                f"FROM agent a "
                f"JOIN agent_type at ON a.agent_type_id = at.type_id {where} "
                f"ORDER BY a.agent_name "
                f"LIMIT ${limit_param} OFFSET ${offset_param}"
            )
            rows = await conn.fetch(data_sql, *params)

            agents = []
            for row in rows:
                agent = dict(row)
                _ensure_json_fields(agent)
                agents.append(agent)

            return agents, total

    async def list_agents(
        self,
        type_key: Optional[str] = None,
        status: Optional[str] = 'active',
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Convenience wrapper around search_agents with no text query."""
        return await self.search_agents(
            type_key=type_key, status=status, page=page, page_size=page_size,
        )

    # ------------------------------------------------------------------
    # Endpoint CRUD
    # ------------------------------------------------------------------

    async def _insert_endpoint(
        self,
        conn,
        agent_id: str,
        endpoint_uri: str,
        endpoint_url: str,
        protocol: str = 'websocket',
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Insert an endpoint within an existing transaction."""
        row = await conn.fetchrow(
            "INSERT INTO agent_endpoint (agent_id, endpoint_uri, endpoint_url, protocol, notes) "
            "VALUES ($1, $2, $3, $4, $5) RETURNING *",
            agent_id, endpoint_uri, endpoint_url, protocol, notes,
        )
        return dict(row)

    async def create_endpoint(
        self,
        agent_id: str,
        endpoint_uri: str,
        endpoint_url: str,
        protocol: str = 'websocket',
        notes: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create an endpoint for an agent."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "INSERT INTO agent_endpoint (agent_id, endpoint_uri, endpoint_url, protocol, notes) "
                    "VALUES ($1, $2, $3, $4, $5) RETURNING *",
                    agent_id, endpoint_uri, endpoint_url, protocol, notes,
                )
                await self._log_change(conn, agent_id, 'endpoint_created', {
                    'endpoint_uri': endpoint_uri, 'endpoint_url': endpoint_url,
                    'protocol': protocol,
                }, changed_by=created_by)
                return dict(row)

    async def list_endpoints(self, agent_id: str) -> List[Dict[str, Any]]:
        """List active endpoints for an agent."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM agent_endpoint "
                "WHERE agent_id = $1 AND status != 'deleted' "
                "ORDER BY endpoint_id",
                agent_id,
            )
            return [dict(r) for r in rows]

    async def update_endpoint(
        self,
        endpoint_id: int,
        endpoint_url: Optional[str] = None,
        protocol: Optional[str] = None,
        status: Optional[str] = None,
        notes: Optional[str] = None,
        updated_by: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update an endpoint. Only provided fields are updated."""
        fields: Dict[str, Any] = {}
        if endpoint_url is not None:
            fields['endpoint_url'] = endpoint_url
        if protocol is not None:
            fields['protocol'] = protocol
        if status is not None:
            fields['status'] = status
        if notes is not None:
            fields['notes'] = notes

        if not fields:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM agent_endpoint WHERE endpoint_id = $1", endpoint_id
                )
                return dict(row) if row else None

        fields['updated_time'] = datetime.now(timezone.utc)

        set_parts = []
        values = []
        for i, (col, val) in enumerate(fields.items(), 1):
            set_parts.append(f"{col} = ${i}")
            values.append(val)

        values.append(endpoint_id)
        param_idx = len(values)

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                result = await conn.execute(
                    f"UPDATE agent_endpoint SET {', '.join(set_parts)} "
                    f"WHERE endpoint_id = ${param_idx}",
                    *values,
                )
                if result == 'UPDATE 0':
                    return None

                # Get agent_id for change log
                agent_id = await conn.fetchval(
                    "SELECT agent_id FROM agent_endpoint WHERE endpoint_id = $1",
                    endpoint_id,
                )
                await self._log_change(conn, agent_id, 'endpoint_updated', {
                    'endpoint_id': endpoint_id, 'fields': list(fields.keys()),
                }, changed_by=updated_by)

                row = await conn.fetchrow(
                    "SELECT * FROM agent_endpoint WHERE endpoint_id = $1", endpoint_id
                )
                return dict(row) if row else None

    async def delete_endpoint(
        self,
        endpoint_id: int,
        deleted_by: Optional[str] = None,
    ) -> bool:
        """Soft-delete an endpoint."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Get agent_id before delete
                agent_id = await conn.fetchval(
                    "SELECT agent_id FROM agent_endpoint WHERE endpoint_id = $1",
                    endpoint_id,
                )
                if agent_id is None:
                    return False

                result = await conn.execute(
                    "UPDATE agent_endpoint SET status = 'deleted', updated_time = $1 "
                    "WHERE endpoint_id = $2 AND status != 'deleted'",
                    datetime.now(timezone.utc), endpoint_id,
                )
                if result == 'UPDATE 0':
                    return False

                await self._log_change(conn, agent_id, 'endpoint_deleted', {
                    'endpoint_id': endpoint_id,
                }, changed_by=deleted_by)
                return True

    # ------------------------------------------------------------------
    # Change log query
    # ------------------------------------------------------------------

    async def get_change_log(
        self,
        agent_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get change log entries for an agent."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM agent_change_log "
                "WHERE agent_id = $1 ORDER BY created_time DESC LIMIT $2",
                agent_id, limit,
            )
            return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_json_fields(agent: Dict[str, Any]):
    """Ensure JSONB fields are dicts/lists, not strings."""
    for key in ('auth_service_config', 'metadata'):
        val = agent.get(key)
        if isinstance(val, str):
            agent[key] = json.loads(val)
        elif val is None:
            agent[key] = {}

    val = agent.get('capabilities')
    if isinstance(val, str):
        agent['capabilities'] = json.loads(val)
    elif val is None:
        agent['capabilities'] = []
