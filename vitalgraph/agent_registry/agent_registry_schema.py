"""
PostgreSQL schema for the Agent Registry.

Global tables (not per-space) for tracking AI agents with types,
endpoints, functions, and change history.

Mirror of apps/agent_registry/migrate_agents.py DDL — kept here
so VG_AUTO_INIT can create tables without importing from apps/.
"""

from typing import List, Tuple


class AgentRegistrySchema:
    """Schema definitions for the Agent Registry tables."""

    TABLES: List[Tuple[str, str]] = [
        ('agent_type', '''
            CREATE TABLE IF NOT EXISTS agent_type (
                type_id SERIAL PRIMARY KEY,
                type_key VARCHAR(500) UNIQUE NOT NULL,
                type_label VARCHAR(255) NOT NULL,
                type_description TEXT,
                created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
        '''),
        ('agent', '''
            CREATE TABLE IF NOT EXISTS agent (
                agent_id VARCHAR(50) PRIMARY KEY,
                agent_type_id INTEGER NOT NULL REFERENCES agent_type(type_id),
                entity_id VARCHAR(50),
                agent_name VARCHAR(500) NOT NULL,
                agent_uri VARCHAR(500) NOT NULL,
                description TEXT,
                version VARCHAR(50),
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                protocol_format_uri VARCHAR(500),
                auth_service_uri VARCHAR(500),
                auth_service_config JSONB DEFAULT '{}',
                capabilities JSONB DEFAULT '[]',
                metadata JSONB DEFAULT '{}',
                protocol_config JSONB DEFAULT '{}',
                created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                created_by VARCHAR(255),
                notes TEXT
            )
        '''),
        ('agent_endpoint', '''
            CREATE TABLE IF NOT EXISTS agent_endpoint (
                endpoint_id SERIAL PRIMARY KEY,
                agent_id VARCHAR(50) NOT NULL REFERENCES agent(agent_id) ON DELETE CASCADE,
                endpoint_uri VARCHAR(500) NOT NULL,
                endpoint_url VARCHAR(1000) NOT NULL,
                protocol VARCHAR(20) NOT NULL DEFAULT 'websocket',
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                transport_config JSONB DEFAULT '{}',
                created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                notes TEXT
            )
        '''),
        ('agent_function', '''
            CREATE TABLE IF NOT EXISTS agent_function (
                function_id SERIAL PRIMARY KEY,
                agent_id VARCHAR(50) NOT NULL REFERENCES agent(agent_id) ON DELETE CASCADE,
                function_uri VARCHAR(500) NOT NULL,
                function_name VARCHAR(255) NOT NULL,
                description TEXT,
                parameters JSONB DEFAULT '{}',
                output_schema JSONB DEFAULT '{}',
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                notes TEXT
            )
        '''),
        ('agent_change_log', '''
            CREATE TABLE IF NOT EXISTS agent_change_log (
                log_id BIGSERIAL PRIMARY KEY,
                agent_id VARCHAR(50) REFERENCES agent(agent_id) ON DELETE SET NULL,
                change_type VARCHAR(50) NOT NULL,
                change_detail JSONB,
                changed_by VARCHAR(255),
                comment TEXT,
                created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
        '''),
    ]

    INDEXES: List[str] = [
        'CREATE INDEX IF NOT EXISTS idx_agent_type_id ON agent(agent_type_id)',
        'CREATE INDEX IF NOT EXISTS idx_agent_entity ON agent(entity_id)',
        'CREATE INDEX IF NOT EXISTS idx_agent_name ON agent(agent_name)',
        'CREATE INDEX IF NOT EXISTS idx_agent_uri ON agent(agent_uri)',
        'CREATE INDEX IF NOT EXISTS idx_agent_status ON agent(status)',
        'CREATE INDEX IF NOT EXISTS idx_agent_protocol ON agent(protocol_format_uri)',
        'CREATE INDEX IF NOT EXISTS idx_agent_auth_service ON agent(auth_service_uri)',
        'CREATE INDEX IF NOT EXISTS idx_agent_created ON agent(created_time)',
        'CREATE INDEX IF NOT EXISTS idx_agent_capabilities ON agent USING GIN(capabilities)',
        'CREATE INDEX IF NOT EXISTS idx_agent_metadata ON agent USING GIN(metadata)',
        'CREATE INDEX IF NOT EXISTS idx_agent_protocol_config ON agent USING GIN(protocol_config)',
        'CREATE INDEX IF NOT EXISTS idx_agent_ep_agent ON agent_endpoint(agent_id)',
        'CREATE INDEX IF NOT EXISTS idx_agent_ep_uri ON agent_endpoint(agent_id, endpoint_uri)',
        'CREATE INDEX IF NOT EXISTS idx_agent_ep_protocol ON agent_endpoint(protocol)',
        'CREATE INDEX IF NOT EXISTS idx_agent_ep_status ON agent_endpoint(status)',
        'CREATE INDEX IF NOT EXISTS idx_agent_ep_transport_config ON agent_endpoint USING GIN(transport_config)',
        'CREATE INDEX IF NOT EXISTS idx_agent_fn_agent ON agent_function(agent_id)',
        'CREATE INDEX IF NOT EXISTS idx_agent_fn_key ON agent_function(agent_id, function_uri)',
        'CREATE INDEX IF NOT EXISTS idx_agent_fn_uri ON agent_function(function_uri)',
        'CREATE INDEX IF NOT EXISTS idx_agent_fn_status ON agent_function(status)',
        'CREATE INDEX IF NOT EXISTS idx_agent_fn_params ON agent_function USING GIN(parameters)',
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_uri_active ON agent(agent_uri) WHERE status != 'deleted'",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_ep_active ON agent_endpoint(agent_id, endpoint_uri) WHERE status != 'deleted'",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_fn_active ON agent_function(agent_id, function_uri) WHERE status != 'deleted'",
        'CREATE INDEX IF NOT EXISTS idx_agent_log_agent ON agent_change_log(agent_id)',
        'CREATE INDEX IF NOT EXISTS idx_agent_log_type ON agent_change_log(change_type)',
        'CREATE INDEX IF NOT EXISTS idx_agent_log_time ON agent_change_log(created_time)',
    ]

    SEED_AGENT_TYPES: List[Tuple[str, str, str]] = [
        ('urn:vital-ai:agent-type:chat', 'Chat', 'Conversational chat agent'),
    ]

    VIEWS: List[Tuple[str, str]] = [
        ('agent_active_view', '''
        CREATE OR REPLACE VIEW agent_active_view AS
            SELECT a.*, at.type_key, at.type_label
            FROM agent a
            JOIN agent_type at ON a.agent_type_id = at.type_id
            WHERE a.status = 'active'
        '''),
        ('agent_function_view', '''
        CREATE OR REPLACE VIEW agent_function_view AS
            SELECT af.*, a.agent_name, a.agent_uri, a.status AS agent_status
            FROM agent_function af
            JOIN agent a ON af.agent_id = a.agent_id
            WHERE af.status = 'active' AND a.status = 'active'
        '''),
    ]

    def create_tables_sql(self) -> List[str]:
        """Get SQL statements to create all agent registry tables in order."""
        return [ddl.strip() for _name, ddl in self.TABLES]

    def create_indexes_sql(self) -> List[str]:
        """Get SQL statements to create all indexes."""
        return list(self.INDEXES)

    def create_views_sql(self) -> List[str]:
        """Get SQL statements to create all views."""
        return [sql.strip() for _name, sql in self.VIEWS]

    def seed_agent_types_sql(self) -> str:
        """Get SQL statement to insert seed agent types (idempotent)."""
        values = ', '.join(
            f"('{key}', '{label}', '{desc}')"
            for key, label, desc in self.SEED_AGENT_TYPES
        )
        return (
            "INSERT INTO agent_type (type_key, type_label, type_description) "
            f"VALUES {values} "
            "ON CONFLICT (type_key) DO NOTHING"
        )
