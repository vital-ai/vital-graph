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
                latitude DOUBLE PRECISION,
                longitude DOUBLE PRECISION,
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
                notes TEXT
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

        'category': '''
            CREATE TABLE IF NOT EXISTS category (
                category_id SERIAL PRIMARY KEY,
                category_key VARCHAR(50) UNIQUE NOT NULL,
                category_label VARCHAR(255) NOT NULL,
                category_description TEXT,
                created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
        ''',

        'entity_category_map': '''
            CREATE TABLE IF NOT EXISTS entity_category_map (
                entity_category_id SERIAL PRIMARY KEY,
                entity_id VARCHAR(50) NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
                category_id INTEGER NOT NULL REFERENCES category(category_id),
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                created_by VARCHAR(255),
                notes TEXT,
                CONSTRAINT uq_entity_category UNIQUE (entity_id, category_id)
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

        'entity_location_type': '''
            CREATE TABLE IF NOT EXISTS entity_location_type (
                location_type_id SERIAL PRIMARY KEY,
                type_key VARCHAR(50) UNIQUE NOT NULL,
                type_label VARCHAR(255) NOT NULL,
                type_description TEXT,
                created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
        ''',

        'entity_location': '''
            CREATE TABLE IF NOT EXISTS entity_location (
                location_id SERIAL PRIMARY KEY,
                entity_id VARCHAR(50) NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
                location_type_id INTEGER NOT NULL REFERENCES entity_location_type(location_type_id),
                location_name VARCHAR(255),
                description TEXT,
                address_line_1 VARCHAR(500),
                address_line_2 VARCHAR(500),
                locality VARCHAR(255),
                admin_area_2 VARCHAR(255),
                admin_area_1 VARCHAR(255),
                country VARCHAR(100),
                country_code VARCHAR(2),
                postal_code VARCHAR(50),
                formatted_address VARCHAR(1000),
                latitude DOUBLE PRECISION,
                longitude DOUBLE PRECISION,
                timezone VARCHAR(100),
                google_place_id VARCHAR(255),
                external_location_id VARCHAR(50),
                effective_from DATE,
                effective_to DATE,
                is_primary BOOLEAN DEFAULT FALSE,
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                created_by VARCHAR(255),
                notes TEXT
            )
        ''',

        'entity_location_category_map': '''
            CREATE TABLE IF NOT EXISTS entity_location_category_map (
                location_category_map_id SERIAL PRIMARY KEY,
                location_id INTEGER NOT NULL REFERENCES entity_location(location_id) ON DELETE CASCADE,
                category_id INTEGER NOT NULL REFERENCES category(category_id),
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                created_by VARCHAR(255),
                notes TEXT,
                CONSTRAINT uq_location_category UNIQUE (location_id, category_id)
            )
        ''',

        'relationship_type': '''
            CREATE TABLE IF NOT EXISTS relationship_type (
                relationship_type_id SERIAL PRIMARY KEY,
                type_key VARCHAR(50) UNIQUE NOT NULL,
                type_label VARCHAR(255) NOT NULL,
                type_description TEXT,
                inverse_key VARCHAR(50),
                created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
        ''',

        'entity_relationship': '''
            CREATE TABLE IF NOT EXISTS entity_relationship (
                relationship_id SERIAL PRIMARY KEY,
                entity_source VARCHAR(50) NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
                entity_destination VARCHAR(50) NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
                relationship_type_id INTEGER NOT NULL REFERENCES relationship_type(relationship_type_id),
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                start_datetime TIMESTAMPTZ,
                end_datetime TIMESTAMPTZ,
                description TEXT,
                created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                created_by VARCHAR(255),
                notes TEXT,
                CONSTRAINT uq_entity_relationship UNIQUE (entity_source, entity_destination, relationship_type_id)
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

        'CREATE INDEX IF NOT EXISTS idx_category_key ON category(category_key)',

        'CREATE INDEX IF NOT EXISTS idx_catmap_entity ON entity_category_map(entity_id)',
        'CREATE INDEX IF NOT EXISTS idx_catmap_category ON entity_category_map(category_id)',
        'CREATE INDEX IF NOT EXISTS idx_catmap_status ON entity_category_map(status)',

        'CREATE INDEX IF NOT EXISTS idx_changelog_entity ON entity_change_log(entity_id)',
        'CREATE INDEX IF NOT EXISTS idx_changelog_type ON entity_change_log(change_type)',
        'CREATE INDEX IF NOT EXISTS idx_changelog_time ON entity_change_log(created_time)',
        'CREATE INDEX IF NOT EXISTS idx_changelog_changed_by ON entity_change_log(changed_by)',

        # Location indexes
        'CREATE INDEX IF NOT EXISTS idx_location_entity ON entity_location(entity_id)',
        'CREATE INDEX IF NOT EXISTS idx_location_type ON entity_location(location_type_id)',
        'CREATE INDEX IF NOT EXISTS idx_location_country ON entity_location(country)',
        'CREATE INDEX IF NOT EXISTS idx_location_admin1 ON entity_location(admin_area_1)',
        'CREATE INDEX IF NOT EXISTS idx_location_locality ON entity_location(locality)',
        'CREATE INDEX IF NOT EXISTS idx_location_postal ON entity_location(postal_code)',
        'CREATE INDEX IF NOT EXISTS idx_location_status ON entity_location(status)',
        'CREATE INDEX IF NOT EXISTS idx_location_primary ON entity_location(entity_id, is_primary) WHERE is_primary = TRUE',
        'CREATE INDEX IF NOT EXISTS idx_location_latlon ON entity_location(latitude, longitude) WHERE latitude IS NOT NULL',
        'CREATE INDEX IF NOT EXISTS idx_location_country_code ON entity_location(country_code)',
        'CREATE INDEX IF NOT EXISTS idx_location_place_id ON entity_location(google_place_id) WHERE google_place_id IS NOT NULL',
        'CREATE INDEX IF NOT EXISTS idx_location_external_id ON entity_location(external_location_id) WHERE external_location_id IS NOT NULL',
        'CREATE INDEX IF NOT EXISTS idx_location_effective ON entity_location(effective_from, effective_to)',
        'CREATE INDEX IF NOT EXISTS idx_loc_type_key ON entity_location_type(type_key)',
        'CREATE INDEX IF NOT EXISTS idx_loc_catmap_location ON entity_location_category_map(location_id)',
        'CREATE INDEX IF NOT EXISTS idx_loc_catmap_category ON entity_location_category_map(category_id)',
        'CREATE INDEX IF NOT EXISTS idx_loc_catmap_status ON entity_location_category_map(status)',

        # Relationship indexes
        'CREATE INDEX IF NOT EXISTS idx_rel_type_key ON relationship_type(type_key)',
        'CREATE INDEX IF NOT EXISTS idx_rel_source ON entity_relationship(entity_source)',
        'CREATE INDEX IF NOT EXISTS idx_rel_destination ON entity_relationship(entity_destination)',
        'CREATE INDEX IF NOT EXISTS idx_rel_type ON entity_relationship(relationship_type_id)',
        'CREATE INDEX IF NOT EXISTS idx_rel_status ON entity_relationship(status)',
        'CREATE INDEX IF NOT EXISTS idx_rel_dates ON entity_relationship(start_datetime, end_datetime)',
    ]

    SEED_ENTITY_TYPES = [
        ('person', 'Person', 'An individual person'),
        ('business', 'Business', 'A business or company'),
        ('organization', 'Organization', 'A non-commercial organization'),
        ('government', 'Government', 'A government body or agency'),
    ]

    SEED_ENTITY_CATEGORIES = [
        ('customer', 'Customer', 'A customer or client'),
        ('partner', 'Partner', 'A business partner or affiliate'),
        ('vendor', 'Vendor', 'A vendor or supplier'),
        ('competitor', 'Competitor', 'A competitor'),
        ('prospect', 'Prospect', 'A prospective customer or lead'),
        ('investor', 'Investor', 'An investor or shareholder'),
        ('regulator', 'Regulator', 'A regulatory or oversight body'),
    ]

    SEED_LOCATION_TYPES = [
        ('headquarters', 'Headquarters', 'Primary headquarters'),
        ('branch', 'Branch Office', 'A branch or satellite office'),
        ('warehouse', 'Warehouse', 'A warehouse or distribution center'),
        ('mailing', 'Mailing Address', 'A mailing or correspondence address'),
        ('residence', 'Residence', 'A residential address'),
        ('registered', 'Registered Office', 'Officially registered office address'),
    ]

    SEED_RELATIONSHIP_TYPES = [
        ('parent_of', 'Parent Of', 'Parent company or organization', 'subsidiary_of'),
        ('subsidiary_of', 'Subsidiary Of', 'Subsidiary or child organization', 'parent_of'),
        ('employer_of', 'Employer Of', 'Employs a person', 'employee_of'),
        ('employee_of', 'Employee Of', 'Employed by an organization', 'employer_of'),
        ('investor_in', 'Investor In', 'Invests in an entity', 'funded_by'),
        ('funded_by', 'Funded By', 'Receives funding from an entity', 'investor_in'),
        ('partner_of', 'Partner Of', 'Business partner (symmetric)', 'partner_of'),
        ('advisor_to', 'Advisor To', 'Advises an entity', 'advised_by'),
        ('advised_by', 'Advised By', 'Receives advice from an entity', 'advisor_to'),
        ('supplier_to', 'Supplier To', 'Supplies goods/services to an entity', 'customer_of'),
        ('customer_of', 'Customer Of', 'Purchases goods/services from an entity', 'supplier_to'),
        ('board_member_of', 'Board Member Of', 'Serves on the board of an entity', 'has_board_member'),
        ('has_board_member', 'Has Board Member', 'Has a person on its board', 'board_member_of'),
    ]

    MIGRATIONS = [
        # Add latitude/longitude columns (idempotent)
        "ALTER TABLE entity ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION",
        "ALTER TABLE entity ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION",
        # Remove unique constraint on identifiers (same ID can map to multiple entities)
        "ALTER TABLE entity_identifier DROP CONSTRAINT IF EXISTS uq_entity_ns_value",
        # Clean up trace_id and partial index if they were previously applied
        "ALTER TABLE entity_identifier DROP COLUMN IF EXISTS trace_id",
        "DROP INDEX IF EXISTS uq_entity_ns_value_active",
        # Phase 0: entity table enhancements
        "ALTER TABLE entity ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'",
        "ALTER TABLE entity ADD COLUMN IF NOT EXISTS verified BOOLEAN DEFAULT FALSE",
        "ALTER TABLE entity ADD COLUMN IF NOT EXISTS verified_by VARCHAR(255)",
        "ALTER TABLE entity ADD COLUMN IF NOT EXISTS verified_time TIMESTAMPTZ",
        # Rename entity_category -> category (idempotent: rename only if old name exists)
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'entity_category') "
        "AND NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'category') "
        "THEN EXECUTE 'ALTER TABLE entity_category RENAME TO category'; END IF; END $$",
        # Rename the old category_key index to match new table name
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_category_key' AND tablename = 'entity_category') "
        "THEN EXECUTE 'ALTER INDEX idx_category_key RENAME TO idx_category_key_old'; END IF; END $$",
        # Add external_location_id for business-assigned location references
        "ALTER TABLE entity_location ADD COLUMN IF NOT EXISTS external_location_id VARCHAR(50)",
    ]

    VIEWS = [
        """CREATE OR REPLACE VIEW entity_location_view AS
            SELECT *, (effective_to IS NULL OR effective_to >= CURRENT_DATE) AS is_active
            FROM entity_location""",
        """CREATE OR REPLACE VIEW entity_relationship_view AS
            SELECT *,
                (status = 'active'
                 AND (start_datetime IS NULL OR start_datetime <= CURRENT_TIMESTAMP)
                 AND (end_datetime IS NULL OR end_datetime >= CURRENT_TIMESTAMP)
                ) AS is_current
            FROM entity_relationship""",
    ]

    def create_tables_sql(self) -> List[str]:
        """Get SQL statements to create all entity registry tables in order."""
        return [sql.strip() for sql in self.TABLES.values()]

    def migrations_sql(self) -> List[str]:
        """Get SQL statements for schema migrations (safe to re-run)."""
        return list(self.MIGRATIONS)

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

    def seed_entity_categories_sql(self) -> str:
        """Get SQL statement to insert seed categories (idempotent)."""
        values = ', '.join(
            f"('{key}', '{label}', '{desc}')"
            for key, label, desc in self.SEED_ENTITY_CATEGORIES
        )
        return f"""
            INSERT INTO category (category_key, category_label, category_description)
            VALUES {values}
            ON CONFLICT (category_key) DO NOTHING
        """

    def seed_location_types_sql(self) -> str:
        """Get SQL statement to insert seed location types (idempotent)."""
        values = ', '.join(
            f"('{key}', '{label}', '{desc}')"
            for key, label, desc in self.SEED_LOCATION_TYPES
        )
        return f"""
            INSERT INTO entity_location_type (type_key, type_label, type_description)
            VALUES {values}
            ON CONFLICT (type_key) DO NOTHING
        """

    def seed_relationship_types_sql(self) -> str:
        """Get SQL statement to insert seed relationship types (idempotent)."""
        values = ', '.join(
            f"('{key}', '{label}', '{desc}', {('chr(39) + inv + chr(39)') if inv else 'NULL'})"
            .replace("chr(39) + inv + chr(39)", f"'{inv}'")
            for key, label, desc, inv in self.SEED_RELATIONSHIP_TYPES
        )
        return f"""
            INSERT INTO relationship_type (type_key, type_label, type_description, inverse_key)
            VALUES {values}
            ON CONFLICT (type_key) DO NOTHING
        """

    def create_views_sql(self) -> List[str]:
        """Get SQL statements to create all views."""
        return list(self.VIEWS)
