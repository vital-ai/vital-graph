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

from vitalgraph.utils.db_retry import with_db_retry

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
        self._vector_populator = None  # Optional, set via set_vector_populator()

    def set_vector_populator(self, populator):
        """Attach vector/FTS populator for incremental sync on CRUD operations."""
        self._vector_populator = populator

    async def _sync_vectors(self, agent_id: str):
        """Trigger incremental vector/FTS sync if populator is attached."""
        if self._vector_populator:
            try:
                await self._vector_populator.sync_agent(agent_id)
            except Exception as e:
                logger.warning("Vector sync failed for agent %s: %s", agent_id, e)

    async def _delete_vectors(self, agent_id: str):
        """Remove agent from vector/FTS tables if populator is attached."""
        if self._vector_populator:
            try:
                await self._vector_populator.delete_agent(agent_id)
            except Exception as e:
                logger.warning("Vector delete failed for agent %s: %s", agent_id, e)

    # ------------------------------------------------------------------
    # Schema verification
    # ------------------------------------------------------------------

    @with_db_retry()
    async def ensure_tables(self) -> bool:
        """Verify that agent registry tables exist. Does NOT create or modify schema.

        Run apps/agent_registry/migrate_agents.py to create tables.
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
                        "Run 'python apps/agent_registry/migrate_agents.py' to create them."
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

    @with_db_retry()
    async def list_agent_types(self) -> List[Dict[str, Any]]:
        """List all agent types."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT type_id, type_key, type_label, type_description, "
                "created_time, updated_time FROM agent_type ORDER BY type_id"
            )
            return [dict(r) for r in rows]

    @with_db_retry()
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

    @with_db_retry()
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
        protocol_config: Optional[Dict[str, Any]] = None,
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
        protocol_config_json = json.dumps(protocol_config) if protocol_config else '{}'

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
                    "protocol_config, created_by, notes) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, "
                    "$11::jsonb, $12::jsonb, $13::jsonb, $14, $15) RETURNING *",
                    agent_id, type_id, entity_id, agent_name,
                    agent_uri, description, version, protocol_format_uri,
                    auth_service_uri, auth_config_json, capabilities_json,
                    metadata_json, protocol_config_json, created_by, notes,
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

                await self._sync_vectors(agent_id)
                return agent

    @with_db_retry()
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

    @with_db_retry()
    async def get_agent_by_uri(self, agent_uri: str) -> Optional[Dict[str, Any]]:
        """Get agent by agent_uri."""
        async with self.pool.acquire() as conn:
            agent_id = await conn.fetchval(
                "SELECT agent_id FROM agent WHERE agent_uri = $1", agent_uri
            )
            if agent_id is None:
                return None
        return await self.get_agent(agent_id)

    @with_db_retry()
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
        protocol_config: Optional[Dict[str, Any]] = None,
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
        if protocol_config is not None:
            fields['protocol_config'] = json.dumps(protocol_config)
        if notes is not None:
            fields['notes'] = notes
        if entity_id is not None:
            fields['entity_id'] = entity_id

        if not fields and agent_type_key is None:
            return await self.get_agent(agent_id)

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Capture before-snapshot of changed fields
                before_row = await conn.fetchrow(
                    "SELECT * FROM agent WHERE agent_id = $1", agent_id,
                )
                if before_row is None:
                    return None

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
                    cast = '::jsonb' if col in ('auth_service_config', 'capabilities', 'metadata', 'protocol_config') else ''
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

                # Build before/after snapshot for changed fields
                snapshot = _build_snapshot(before_row, fields)

                await self._log_change(conn, agent_id, 'agent_updated', snapshot,
                                       changed_by=updated_by)

        await self._sync_vectors(agent_id)
        return await self.get_agent(agent_id)

    @with_db_retry()
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
                await self._delete_vectors(agent_id)
                return True

    # ------------------------------------------------------------------
    # Search / List
    # ------------------------------------------------------------------

    @with_db_retry()
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

    @with_db_retry()
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
        transport_config: Optional[Dict[str, Any]] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Insert an endpoint within an existing transaction."""
        tc_json = json.dumps(transport_config) if transport_config else '{}'
        row = await conn.fetchrow(
            "INSERT INTO agent_endpoint (agent_id, endpoint_uri, endpoint_url, protocol, "
            "transport_config, notes) "
            "VALUES ($1, $2, $3, $4, $5::jsonb, $6) RETURNING *",
            agent_id, endpoint_uri, endpoint_url, protocol, tc_json, notes,
        )
        return dict(row)

    @with_db_retry()
    async def create_endpoint(
        self,
        agent_id: str,
        endpoint_uri: str,
        endpoint_url: str,
        protocol: str = 'websocket',
        transport_config: Optional[Dict[str, Any]] = None,
        notes: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create an endpoint for an agent."""
        tc_json = json.dumps(transport_config) if transport_config else '{}'
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "INSERT INTO agent_endpoint (agent_id, endpoint_uri, endpoint_url, protocol, "
                    "transport_config, notes) "
                    "VALUES ($1, $2, $3, $4, $5::jsonb, $6) RETURNING *",
                    agent_id, endpoint_uri, endpoint_url, protocol, tc_json, notes,
                )
                await self._log_change(conn, agent_id, 'endpoint_created', {
                    'endpoint_uri': endpoint_uri, 'endpoint_url': endpoint_url,
                    'protocol': protocol,
                }, changed_by=created_by)
                return dict(row)

    @with_db_retry()
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

    @with_db_retry()
    async def update_endpoint(
        self,
        endpoint_id: int,
        endpoint_url: Optional[str] = None,
        protocol: Optional[str] = None,
        transport_config: Optional[Dict[str, Any]] = None,
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
        if transport_config is not None:
            fields['transport_config'] = json.dumps(transport_config)
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
            cast = '::jsonb' if col == 'transport_config' else ''
            set_parts.append(f"{col} = ${i}{cast}")
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

    @with_db_retry()
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
    # Agent Function CRUD
    # ------------------------------------------------------------------

    @with_db_retry()
    async def create_function(
        self,
        agent_id: str,
        function_uri: str,
        function_name: str,
        description: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        output_schema: Optional[Dict[str, Any]] = None,
        notes: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a function for an agent."""
        params_json = json.dumps(parameters) if parameters else '{}'
        output_schema_json = json.dumps(output_schema) if output_schema else '{}'
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "INSERT INTO agent_function "
                    "(agent_id, function_uri, function_name, description, parameters, "
                    "output_schema, notes) "
                    "VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7) RETURNING *",
                    agent_id, function_uri, function_name, description, params_json,
                    output_schema_json, notes,
                )
                await self._log_change(conn, agent_id, 'function_created', {
                    'function_uri': function_uri, 'function_name': function_name,
                }, changed_by=created_by)
                await self._sync_vectors(agent_id)
                result = dict(row)
                _ensure_function_json_fields(result)
                return result

    @with_db_retry()
    async def list_functions(self, agent_id: str) -> List[Dict[str, Any]]:
        """List active functions for an agent."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM agent_function "
                "WHERE agent_id = $1 AND status != 'deleted' "
                "ORDER BY function_id",
                agent_id,
            )
            results = [dict(r) for r in rows]
            for r in results:
                _ensure_function_json_fields(r)
            return results

    @with_db_retry()
    async def get_function(self, function_id: int) -> Optional[Dict[str, Any]]:
        """Get a function by ID."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM agent_function WHERE function_id = $1", function_id
            )
            if row is None:
                return None
            result = dict(row)
            _ensure_function_json_fields(result)
            return result

    @with_db_retry()
    async def update_function(
        self,
        function_id: int,
        function_name: Optional[str] = None,
        description: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        output_schema: Optional[Dict[str, Any]] = None,
        status: Optional[str] = None,
        notes: Optional[str] = None,
        updated_by: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update a function. Only provided fields are updated."""
        fields: Dict[str, Any] = {}
        if function_name is not None:
            fields['function_name'] = function_name
        if description is not None:
            fields['description'] = description
        if parameters is not None:
            fields['parameters'] = json.dumps(parameters)
        if output_schema is not None:
            fields['output_schema'] = json.dumps(output_schema)
        if status is not None:
            valid = ('active', 'deprecated', 'deleted')
            if status not in valid:
                raise ValueError(f"Invalid function status: {status}. Must be one of {valid}")
            fields['status'] = status
        if notes is not None:
            fields['notes'] = notes

        if not fields:
            return await self.get_function(function_id)

        fields['updated_time'] = datetime.now(timezone.utc)

        set_parts = []
        values = []
        for i, (col, val) in enumerate(fields.items(), 1):
            cast = '::jsonb' if col in ('parameters', 'output_schema') else ''
            set_parts.append(f"{col} = ${i}{cast}")
            values.append(val)

        values.append(function_id)
        param_idx = len(values)

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Capture before-snapshot
                before_row = await conn.fetchrow(
                    "SELECT * FROM agent_function WHERE function_id = $1", function_id
                )
                if before_row is None:
                    return None

                result = await conn.execute(
                    f"UPDATE agent_function SET {', '.join(set_parts)} "
                    f"WHERE function_id = ${param_idx}",
                    *values,
                )
                if result == 'UPDATE 0':
                    return None

                agent_id = before_row['agent_id']
                snapshot = _build_snapshot(before_row, fields)
                snapshot['function_id'] = function_id

                await self._log_change(conn, agent_id, 'function_updated', snapshot,
                                       changed_by=updated_by)

                await self._sync_vectors(agent_id)

                row = await conn.fetchrow(
                    "SELECT * FROM agent_function WHERE function_id = $1", function_id
                )
                if row is None:
                    return None
                r = dict(row)
                _ensure_function_json_fields(r)
                return r

    @with_db_retry()
    async def delete_function(
        self,
        function_id: int,
        deleted_by: Optional[str] = None,
    ) -> bool:
        """Soft-delete a function."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                agent_id = await conn.fetchval(
                    "SELECT agent_id FROM agent_function WHERE function_id = $1",
                    function_id,
                )
                if agent_id is None:
                    return False

                result = await conn.execute(
                    "UPDATE agent_function SET status = 'deleted', updated_time = $1 "
                    "WHERE function_id = $2 AND status != 'deleted'",
                    datetime.now(timezone.utc), function_id,
                )
                if result == 'UPDATE 0':
                    return False

                await self._log_change(conn, agent_id, 'function_deleted', {
                    'function_id': function_id,
                }, changed_by=deleted_by)
                await self._sync_vectors(agent_id)
                return True

    @with_db_retry()
    async def discover_by_function(
        self,
        function_uri: str,
        agent_status: str = 'active',
    ) -> List[Dict[str, Any]]:
        """Find agents that provide a specific function URI.

        Returns list of dicts with agent + function info.
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT af.*, a.agent_id, a.agent_name, a.agent_uri, "
                "a.status AS agent_status, at.type_key AS agent_type_key "
                "FROM agent_function af "
                "JOIN agent a ON af.agent_id = a.agent_id "
                "JOIN agent_type at ON a.agent_type_id = at.type_id "
                "WHERE af.function_uri = $1 AND af.status = 'active' "
                "AND a.status = $2 "
                "ORDER BY a.agent_name",
                function_uri, agent_status,
            )
            results = [dict(r) for r in rows]
            for r in results:
                _ensure_function_json_fields(r)
            return results

    @with_db_retry()
    async def discover_agents(
        self,
        capability: Optional[str] = None,
        type_key: Optional[str] = None,
        protocol_format_uri: Optional[str] = None,
        protocol_config_key: Optional[str] = None,
        protocol_config_contains: Optional[Dict[str, Any]] = None,
        status: str = 'active',
    ) -> List[Dict[str, Any]]:
        """Discover agents for routing — multi-filter search.

        Returns agents with their endpoints and functions, filtered by any
        combination of capability, type, protocol, and protocol_config.

        Filters:
          - capability: agent must have this capability tag
          - type_key: agent must be of this type
          - protocol_format_uri: agent must use this protocol
          - protocol_config_key: agent's protocol_config must contain this top-level key
          - protocol_config_contains: agent's protocol_config must contain this JSON fragment
            (uses PostgreSQL @> containment, e.g. {"mcp": {"capabilities": ["tools"]}})
          - status: agent status filter (default 'active')

        This is the general-purpose agent discovery endpoint intended for
        agent routing decisions.
        """
        conditions = ["a.status = $1"]
        params: list = [status]
        idx = 1

        if type_key is not None:
            idx += 1
            conditions.append(f"at.type_key = ${idx}")
            params.append(type_key)

        if capability is not None:
            idx += 1
            conditions.append(f"a.capabilities @> ${idx}::jsonb")
            params.append(json.dumps([capability]))

        if protocol_format_uri is not None:
            idx += 1
            conditions.append(f"a.protocol_format_uri = ${idx}")
            params.append(protocol_format_uri)

        if protocol_config_key is not None:
            idx += 1
            conditions.append(f"a.protocol_config ? ${idx}")
            params.append(protocol_config_key)

        if protocol_config_contains is not None:
            idx += 1
            conditions.append(f"a.protocol_config @> ${idx}::jsonb")
            params.append(json.dumps(protocol_config_contains))

        where = "WHERE " + " AND ".join(conditions)

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT a.*, at.type_key AS agent_type_key, "
                f"at.type_label AS agent_type_label "
                f"FROM agent a "
                f"JOIN agent_type at ON a.agent_type_id = at.type_id "
                f"{where} ORDER BY a.agent_name",
                *params,
            )

            agents = []
            for row in rows:
                agent = dict(row)
                _ensure_json_fields(agent)

                # Attach endpoints
                ep_rows = await conn.fetch(
                    "SELECT * FROM agent_endpoint "
                    "WHERE agent_id = $1 AND status != 'deleted' "
                    "ORDER BY endpoint_id",
                    agent['agent_id'],
                )
                agent['endpoints'] = [dict(r) for r in ep_rows]

                # Attach functions
                fn_rows = await conn.fetch(
                    "SELECT * FROM agent_function "
                    "WHERE agent_id = $1 AND status != 'deleted' "
                    "ORDER BY function_id",
                    agent['agent_id'],
                )
                fns = [dict(r) for r in fn_rows]
                for fn in fns:
                    _ensure_function_json_fields(fn)
                agent['functions'] = fns

                agents.append(agent)

            return agents

    # ------------------------------------------------------------------
    # Vector / FTS search
    # ------------------------------------------------------------------

    @with_db_retry()
    async def vector_search(
        self,
        query_text: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Semantic agent search using vector embeddings.

        Requires vector populator to be attached for vectorization.
        Returns agents ordered by cosine similarity.
        """
        if not self._vector_populator:
            raise RuntimeError("Vector populator not available")

        from vitalgraph.agent_registry.agent_registry_vector_schema import AGENT_VECTOR_TABLE

        provider = self._vector_populator._provider
        embeddings = await provider.vectorize_texts([query_text])
        query_embedding = embeddings[0]

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT v.agent_id, v.search_text, "
                f"1 - (v.embedding <=> $1::vector) AS similarity "
                f"FROM {AGENT_VECTOR_TABLE} v "
                f"JOIN agent a ON v.agent_id = a.agent_id "
                f"WHERE a.status = 'active' "
                f"ORDER BY v.embedding <=> $1::vector "
                f"LIMIT $2",
                str(query_embedding), limit,
            )

            results = []
            for row in rows:
                agent = await self.get_agent(row['agent_id'])
                if agent:
                    agent['similarity'] = float(row['similarity'])
                    results.append(agent)
            return results

    @with_db_retry()
    async def fts_search(
        self,
        query_text: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Full-text agent search using PostgreSQL tsvector.

        Returns agents matching the text query via FTS.
        """
        from vitalgraph.agent_registry.agent_registry_vector_schema import FTS_AGENT_TABLE

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT f.agent_id, f.search_text, "
                f"ts_rank(f.tsv, websearch_to_tsquery('english', $1)) AS rank "
                f"FROM {FTS_AGENT_TABLE} f "
                f"JOIN agent a ON f.agent_id = a.agent_id "
                f"WHERE a.status = 'active' "
                f"AND f.tsv @@ websearch_to_tsquery('english', $1) "
                f"ORDER BY rank DESC "
                f"LIMIT $2",
                query_text, limit,
            )

            results = []
            for row in rows:
                agent = await self.get_agent(row['agent_id'])
                if agent:
                    agent['fts_rank'] = float(row['rank'])
                    results.append(agent)
            return results

    # ------------------------------------------------------------------
    # Change log query
    # ------------------------------------------------------------------

    @with_db_retry()
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

    # ------------------------------------------------------------------
    # Rollback
    # ------------------------------------------------------------------

    @with_db_retry()
    async def rollback_agent(
        self,
        agent_id: str,
        log_id: int,
        rolled_back_by: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Rollback an agent to the state captured in a changelog entry.

        The changelog entry (``log_id``) must be an ``agent_updated`` entry
        with a ``before`` snapshot.  The ``before`` values are re-applied to
        the agent.

        Returns:
            Updated agent dict, or None if agent/log not found.

        Raises:
            ValueError: If the log entry has no rollback data.
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                log_row = await conn.fetchrow(
                    "SELECT * FROM agent_change_log WHERE log_id = $1", log_id,
                )
                if log_row is None:
                    raise ValueError(f"Change log entry not found: {log_id}")

                if log_row['agent_id'] != agent_id:
                    raise ValueError(
                        f"Log entry {log_id} does not belong to agent {agent_id}"
                    )

                detail = log_row['change_detail']
                if isinstance(detail, str):
                    detail = json.loads(detail)

                if not detail or 'before' not in detail:
                    raise ValueError(
                        f"Log entry {log_id} has no before-snapshot for rollback"
                    )

                before = detail['before']
                if not before:
                    raise ValueError(f"Log entry {log_id} before-snapshot is empty")

                # Capture current state before rollback
                current_row = await conn.fetchrow(
                    "SELECT * FROM agent WHERE agent_id = $1", agent_id,
                )
                if current_row is None:
                    return None

                # Build SET clause from before-snapshot
                fields: Dict[str, Any] = {}
                for col, val in before.items():
                    if col in ('updated_time',):
                        continue
                    if col in ('auth_service_config', 'capabilities', 'metadata', 'protocol_config'):
                        fields[col] = json.dumps(val) if val is not None else '{}'
                    else:
                        fields[col] = val

                fields['updated_time'] = datetime.now(timezone.utc)

                set_parts = []
                values = []
                for i, (col, val) in enumerate(fields.items(), 1):
                    cast = '::jsonb' if col in ('auth_service_config', 'capabilities', 'metadata', 'protocol_config') else ''
                    set_parts.append(f"{col} = ${i}{cast}")
                    values.append(val)

                values.append(agent_id)
                param_idx = len(values)

                await conn.execute(
                    f"UPDATE agent SET {', '.join(set_parts)} WHERE agent_id = ${param_idx}",
                    *values,
                )

                # Log the rollback with its own before/after snapshot
                rollback_snapshot = _build_snapshot(current_row, fields)
                rollback_snapshot['rollback_from_log_id'] = log_id

                await self._log_change(
                    conn, agent_id, 'agent_rollback', rollback_snapshot,
                    changed_by=rolled_back_by,
                    comment=f"Rollback to state from log_id={log_id}",
                )

        return await self.get_agent(agent_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_json_fields(agent: Dict[str, Any]):
    """Ensure JSONB fields are dicts/lists, not strings."""
    for key in ('auth_service_config', 'metadata', 'protocol_config'):
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


def _ensure_function_json_fields(fn: Dict[str, Any]):
    """Ensure JSONB fields on agent_function rows are dicts, not strings."""
    for key in ('parameters', 'output_schema'):
        val = fn.get(key)
        if isinstance(val, str):
            fn[key] = json.loads(val)
        elif val is None:
            fn[key] = {}


def _build_snapshot(
    before_row,
    fields: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a before/after snapshot for changed fields.

    ``fields`` contains the *new* values (JSONB columns already serialized
    to JSON strings).  ``before_row`` is an ``asyncpg.Record``.

    Returns a dict suitable for storing in ``change_detail``::

        {
            "fields": ["agent_name", "metadata"],
            "before": {"agent_name": "old", "metadata": {...}},
            "after":  {"agent_name": "new", "metadata": {...}}
        }
    """
    skip = {'updated_time'}
    changed_cols = [c for c in fields if c not in skip]

    before: Dict[str, Any] = {}
    after: Dict[str, Any] = {}
    for col in changed_cols:
        # before value — from the DB row
        bval = before_row[col] if col in before_row.keys() else None
        if isinstance(bval, datetime):
            bval = bval.isoformat()
        before[col] = bval

        # after value — from the fields dict (may be JSON-string for JSONB cols)
        aval = fields[col]
        try:
            aval = json.loads(aval) if isinstance(aval, str) and aval.startswith(('{', '[', '"')) else aval
        except (json.JSONDecodeError, ValueError):
            pass
        if isinstance(aval, datetime):
            aval = aval.isoformat()
        after[col] = aval

    return {'fields': changed_cols, 'before': before, 'after': after}
