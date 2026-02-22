"""
PostgreSQL schema for the Entity Registry.

Global tables (not per-space) for tracking real-world entities
with unique identifiers, aliases, external identifiers, and same-as mappings.
"""

from typing import Dict, List


class EntityRegistrySchema:
    """
    Schema definitions for the Entity Registry tables.
    All tables are global (not per-space).
    """

    TABLES = {
        'entity_type': '''
            CREATE TABLE IF NOT EXISTS entity_type (
                type_id SERIAL PRIMARY KEY,
                type_key VARCHAR(50) UNIQUE NOT NULL,
                type_label VARCHAR(255) NOT NULL,
                type_description TEXT,
                created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
        ''',

        'entity': '''
            CREATE TABLE IF NOT EXISTS entity (
                entity_id VARCHAR(50) PRIMARY KEY,
                entity_type_id INTEGER NOT NULL REFERENCES entity_type(type_id),
                primary_name VARCHAR(500) NOT NULL,
                description TEXT,
                country VARCHAR(100),
                region VARCHAR(255),
                locality VARCHAR(255),
                website VARCHAR(500),
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                created_by VARCHAR(255),
                notes TEXT
            )
        ''',

        'entity_identifier': '''
            CREATE TABLE IF NOT EXISTS entity_identifier (
                identifier_id SERIAL PRIMARY KEY,
                entity_id VARCHAR(50) NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
                identifier_namespace VARCHAR(255) NOT NULL,
                identifier_value VARCHAR(500) NOT NULL,
                is_primary BOOLEAN DEFAULT FALSE,
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                created_by VARCHAR(255),
                notes TEXT,
                CONSTRAINT uq_entity_ns_value UNIQUE (entity_id, identifier_namespace, identifier_value)
            )
        ''',

        'entity_alias': '''
            CREATE TABLE IF NOT EXISTS entity_alias (
                alias_id SERIAL PRIMARY KEY,
                entity_id VARCHAR(50) NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
                alias_name VARCHAR(500) NOT NULL,
                alias_type VARCHAR(50) NOT NULL DEFAULT 'aka',
                is_primary BOOLEAN DEFAULT FALSE,
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                created_by VARCHAR(255),
                notes TEXT
            )
        ''',

        'entity_same_as': '''
            CREATE TABLE IF NOT EXISTS entity_same_as (
                same_as_id SERIAL PRIMARY KEY,
                source_entity_id VARCHAR(50) NOT NULL REFERENCES entity(entity_id),
                target_entity_id VARCHAR(50) NOT NULL REFERENCES entity(entity_id),
                relationship_type VARCHAR(50) NOT NULL DEFAULT 'same_as',
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                confidence FLOAT,
                reason TEXT,
                created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                retracted_time TIMESTAMPTZ,
                created_by VARCHAR(255),
                retracted_by VARCHAR(255),
                notes TEXT,
                CONSTRAINT no_self_reference CHECK (source_entity_id != target_entity_id)
            )
        ''',

        'entity_change_log': '''
            CREATE TABLE IF NOT EXISTS entity_change_log (
                log_id BIGSERIAL PRIMARY KEY,
                entity_id VARCHAR(50) REFERENCES entity(entity_id) ON DELETE SET NULL,
                change_type VARCHAR(50) NOT NULL,
                change_detail JSONB,
                changed_by VARCHAR(255),
                comment TEXT,
                created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
        ''',
    }

    INDEXES = [
        'CREATE INDEX IF NOT EXISTS idx_entity_type ON entity(entity_type_id)',
        'CREATE INDEX IF NOT EXISTS idx_entity_name ON entity(primary_name)',
        'CREATE INDEX IF NOT EXISTS idx_entity_status ON entity(status)',
        'CREATE INDEX IF NOT EXISTS idx_entity_country ON entity(country)',
        'CREATE INDEX IF NOT EXISTS idx_entity_created ON entity(created_time)',

        'CREATE INDEX IF NOT EXISTS idx_identifier_entity ON entity_identifier(entity_id)',
        'CREATE INDEX IF NOT EXISTS idx_identifier_namespace ON entity_identifier(identifier_namespace)',
        'CREATE INDEX IF NOT EXISTS idx_identifier_value ON entity_identifier(identifier_value)',
        'CREATE INDEX IF NOT EXISTS idx_identifier_ns_value ON entity_identifier(identifier_namespace, identifier_value)',

        'CREATE INDEX IF NOT EXISTS idx_alias_entity ON entity_alias(entity_id)',
        'CREATE INDEX IF NOT EXISTS idx_alias_name ON entity_alias(alias_name)',
        'CREATE INDEX IF NOT EXISTS idx_alias_type ON entity_alias(alias_type)',

        'CREATE INDEX IF NOT EXISTS idx_same_as_source ON entity_same_as(source_entity_id)',
        'CREATE INDEX IF NOT EXISTS idx_same_as_target ON entity_same_as(target_entity_id)',
        'CREATE INDEX IF NOT EXISTS idx_same_as_status ON entity_same_as(status)',

        'CREATE INDEX IF NOT EXISTS idx_changelog_entity ON entity_change_log(entity_id)',
        'CREATE INDEX IF NOT EXISTS idx_changelog_type ON entity_change_log(change_type)',
        'CREATE INDEX IF NOT EXISTS idx_changelog_time ON entity_change_log(created_time)',
        'CREATE INDEX IF NOT EXISTS idx_changelog_changed_by ON entity_change_log(changed_by)',
    ]

    SEED_ENTITY_TYPES = [
        ('person', 'Person', 'An individual person'),
        ('business', 'Business', 'A business or company'),
        ('organization', 'Organization', 'A non-commercial organization'),
        ('government', 'Government', 'A government body or agency'),
    ]

    def create_tables_sql(self) -> List[str]:
        """Get SQL statements to create all entity registry tables in order."""
        return [sql.strip() for sql in self.TABLES.values()]

    def create_indexes_sql(self) -> List[str]:
        """Get SQL statements to create all indexes."""
        return list(self.INDEXES)

    def seed_entity_types_sql(self) -> str:
        """Get SQL statement to insert seed entity types (idempotent)."""
        values = ', '.join(
            f"('{key}', '{label}', '{desc}')"
            for key, label, desc in self.SEED_ENTITY_TYPES
        )
        return f"""
            INSERT INTO entity_type (type_key, type_label, type_description)
            VALUES {values}
            ON CONFLICT (type_key) DO NOTHING
        """
