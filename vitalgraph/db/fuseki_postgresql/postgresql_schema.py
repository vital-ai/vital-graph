"""
PostgreSQL schema for FUSEKI_POSTGRESQL hybrid backend.
Direct SQL operations without SQLAlchemy for maximum performance.

Schema matches existing SQLAlchemy table definitions exactly but defined as direct SQL.
"""

from typing import Dict, List


class FusekiPostgreSQLSchema:
    """
    PostgreSQL schema for FUSEKI_POSTGRESQL hybrid backend.
    Direct SQL operations without SQLAlchemy for maximum performance.
    
    Schema matches existing SQLAlchemy table definitions exactly but defined as direct SQL.
    """
    
    # Admin tables (matching existing SQLAlchemy schema exactly)
    ADMIN_TABLES = {
        # Install table - matches SQLAlchemy Install model
        'install': '''
            CREATE TABLE install (
                id SERIAL PRIMARY KEY,
                install_datetime TIMESTAMP,
                update_datetime TIMESTAMP,
                active BOOLEAN
            )
        ''',
        
        # Space table - matches SQLAlchemy Space model
        'space': '''
            CREATE TABLE space (
                space_id VARCHAR(255) PRIMARY KEY,
                space_name VARCHAR(255),
                space_description TEXT,
                tenant VARCHAR(255),
                update_time TIMESTAMP
            )
        ''',
        
        # Graph table - matches SQLAlchemy Graph model  
        'graph': '''
            CREATE TABLE graph (
                graph_id SERIAL PRIMARY KEY,
                space_id VARCHAR(255) NOT NULL,
                graph_uri VARCHAR(500),
                graph_name VARCHAR(255),
                created_time TIMESTAMP,
                FOREIGN KEY (space_id) REFERENCES space(space_id) ON DELETE CASCADE
            )
        ''',
        
        # User table - matches SQLAlchemy User model
        'user': '''
            CREATE TABLE "user" (
                user_id SERIAL PRIMARY KEY,
                username VARCHAR(255) UNIQUE NOT NULL,
                password VARCHAR(255),
                email VARCHAR(255),
                tenant VARCHAR(255),
                update_time TIMESTAMP
            )
        '''
    }
    
    def get_space_tables(self, space_id: str) -> Dict[str, str]:
        """
        Get table definitions for per-space primary data tables.
        
        These tables store the authoritative RDF data with Fuseki providing index/cache layer.
        """
        prefix = f"{space_id}_"
        return {
            # Term table - matches existing PostgreSQL backend term table structure
            'term': f'''
                CREATE TABLE {prefix}term (
                    term_uuid UUID NOT NULL,
                    term_text TEXT NOT NULL,
                    term_type CHAR(1) NOT NULL CHECK (term_type IN ('U', 'L', 'B', 'G')),
                    lang VARCHAR(20),
                    datatype_id BIGINT,
                    created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    dataset VARCHAR(50) NOT NULL DEFAULT 'primary',
                    PRIMARY KEY (term_uuid, dataset)
                )
            ''',
            
            # RDF Quad table - matches existing PostgreSQL backend rdf_quad table structure
            'rdf_quad': f'''
                CREATE TABLE {prefix}rdf_quad (
                    subject_uuid UUID NOT NULL,
                    predicate_uuid UUID NOT NULL,
                    object_uuid UUID NOT NULL,
                    context_uuid UUID NOT NULL,
                    quad_uuid UUID NOT NULL DEFAULT gen_random_uuid(),
                    created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    dataset VARCHAR(50) NOT NULL DEFAULT 'primary',
                    FOREIGN KEY (subject_uuid, dataset) REFERENCES {prefix}term(term_uuid, dataset) ON DELETE CASCADE,
                    FOREIGN KEY (predicate_uuid, dataset) REFERENCES {prefix}term(term_uuid, dataset) ON DELETE CASCADE,
                    FOREIGN KEY (object_uuid, dataset) REFERENCES {prefix}term(term_uuid, dataset) ON DELETE CASCADE,
                    FOREIGN KEY (context_uuid, dataset) REFERENCES {prefix}term(term_uuid, dataset) ON DELETE CASCADE,
                    PRIMARY KEY (subject_uuid, predicate_uuid, object_uuid, context_uuid, quad_uuid, dataset)
                )
            '''
        }
    
    def get_admin_indexes(self) -> Dict[str, List[str]]:
        """Get index definitions for admin tables only (space, graph, user tables)."""
        return {
            'space_indexes': [
                'CREATE INDEX IF NOT EXISTS idx_space_tenant ON space(tenant)',
                'CREATE INDEX IF NOT EXISTS idx_space_update_time ON space(update_time)'
            ],
            'graph_indexes': [
                'CREATE INDEX IF NOT EXISTS idx_graph_space_id ON graph(space_id)',
                'CREATE INDEX IF NOT EXISTS idx_graph_uri ON graph(graph_uri)'
            ],
            'user_indexes': [
                'CREATE INDEX IF NOT EXISTS idx_user_tenant ON "user"(tenant)',
                'CREATE INDEX IF NOT EXISTS idx_user_username ON "user"(username)'
            ]
        }
    
    # NOTE: No indexes needed for per-space term and quad tables
    # These tables store the authoritative RDF data, with Fuseki providing index/cache layer
    # Fuseki datasets provide fast graph queries while PostgreSQL ensures data persistence
    
    def create_admin_tables_sql(self) -> List[str]:
        """Get SQL statements to create all admin tables."""
        statements = []
        for table_name, create_sql in self.ADMIN_TABLES.items():
            statements.append(create_sql.strip())
        return statements
    
    def create_admin_indexes_sql(self) -> List[str]:
        """Get SQL statements to create all admin table indexes."""
        statements = []
        for index_group in self.get_admin_indexes().values():
            statements.extend(index_group)
        return statements
    
    def create_space_tables_sql(self, space_id: str) -> List[str]:
        """Get SQL statements to create primary data tables for a specific space."""
        statements = []
        space_tables = self.get_space_tables(space_id)
        for table_name, create_sql in space_tables.items():
            statements.append(create_sql.strip())
        return statements
    
    def drop_space_tables_sql(self, space_id: str) -> List[str]:
        """Get SQL statements to drop primary data tables for a specific space."""
        prefix = f"{space_id}_"
        return [
            f'DROP TABLE IF EXISTS {prefix}rdf_quad CASCADE',
            f'DROP TABLE IF EXISTS {prefix}term CASCADE'
        ]
