import os
import asyncio
import asyncpg
from dotenv import load_dotenv

# if you have a .env with PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE
# load_dotenv()

PG_HOST = "127.0.0.1"
PG_PORT = 5432
PG_USER = "postgres"
PG_PASSWORD = ""
PG_DATABASE = "vitalgraphdb"

TABLES = [
    "ontology_source",
    "tuple",
    "space",
    "graph",
    "cluster_node",
    "cluster_edge",
    "node",
    "edge",
    "hyper_node",
    "hyper_edge",
    "binary_data",
    "document",
    "binary_directory",
    "binary_directory_edge",
    "document_folder",
    "document_folder_edge",
]

CREATE_STATEMENTS = {
    "ontology_source": """
        CREATE TABLE ontology_source (
            id SERIAL PRIMARY KEY,
            tenant VARCHAR(255),
            space VARCHAR(255),
            source_id VARCHAR(255),
            ontology_uri VARCHAR(255),
            ontology_version VARCHAR(255),
            ontology_update_datetime TIMESTAMP,
            ontology_signature VARCHAR(255),
            update_time TIMESTAMP
        );
    """,
    "tuple": """
        CREATE TABLE "tuple" (
            id SERIAL PRIMARY KEY,
            tenant VARCHAR(255),
            space VARCHAR(255),
            materialized BOOLEAN,
            materialized_source_id VARCHAR(255),
            materialized_datetime TIMESTAMP,
            graph VARCHAR(255),
            subject VARCHAR(1024),
            predicate VARCHAR(1024),
            multi_value BOOLEAN,
            value_type VARCHAR(50),
            value TEXT,
            value_string VARCHAR(16383),
            value_text TEXT,
            value_uri VARCHAR(1024),
            value_url VARCHAR(1024),
            value_integer INTEGER,
            value_float DOUBLE PRECISION,
            value_date DATE,
            value_datetime TIMESTAMP,
            value_boolean BOOLEAN,
            value_geojson JSONB,
            update_time TIMESTAMP
        );
    """,
    "space": """
        CREATE TABLE space (
            id SERIAL PRIMARY KEY,
            tenant VARCHAR(255),
            space VARCHAR(255),
            space_name VARCHAR(255),
            space_description VARCHAR(255),
            update_time TIMESTAMP
        );
    """,
    "graph": """
        CREATE TABLE graph (
            id SERIAL PRIMARY KEY,
            tenant VARCHAR(255),
            space VARCHAR(255),
            graph VARCHAR(255),
            graph_name VARCHAR(255),
            graph_description VARCHAR(255),
            update_time TIMESTAMP
        );
    """,
    "cluster_node": """
        CREATE TABLE cluster_node (
            id SERIAL PRIMARY KEY,
            tenant VARCHAR(255),
            space VARCHAR(255),
            graph VARCHAR(255),
            uri VARCHAR(255),
            cluster_id VARCHAR(1024),
            update_time TIMESTAMP
        );
    """,
    "cluster_edge": """
        CREATE TABLE cluster_edge (
            id SERIAL PRIMARY KEY,
            tenant VARCHAR(255),
            space VARCHAR(255),
            graph VARCHAR(255),
            uri VARCHAR(255),
            source_uri VARCHAR(255),
            destination_uri VARCHAR(255),
            update_time TIMESTAMP
        );
    """,
    "node": """
        CREATE TABLE node (
            id SERIAL PRIMARY KEY,
            tenant VARCHAR(255),
            space VARCHAR(255),
            graph VARCHAR(255),
            channel VARCHAR(255),
            parent_cluster_id VARCHAR(1024),
            cluster_id VARCHAR(1024),
            cid_0 BOOLEAN, cid_1 BOOLEAN, cid_2 BOOLEAN, cid_3 BOOLEAN,
            cid_4 BOOLEAN, cid_5 BOOLEAN, cid_6 BOOLEAN, cid_7 BOOLEAN,
            uri VARCHAR(255),
            type_uri VARCHAR(255),
            type_uri_list JSONB,
            update_time TIMESTAMP
        );
    """,
    "edge": """
        CREATE TABLE edge (
            id SERIAL PRIMARY KEY,
            tenant VARCHAR(255),
            space VARCHAR(255),
            graph VARCHAR(255),
            channel VARCHAR(255),
            parent_cluster_id VARCHAR(1024),
            cluster_id VARCHAR(1024),
            cid_0 BOOLEAN, cid_1 BOOLEAN, cid_2 BOOLEAN, cid_3 BOOLEAN,
            cid_4 BOOLEAN, cid_5 BOOLEAN, cid_6 BOOLEAN, cid_7 BOOLEAN,
            uri VARCHAR(255),
            source_uri VARCHAR(255),
            destination_uri VARCHAR(255),
            type_uri VARCHAR(255),
            type_uri_list JSONB,
            update_time TIMESTAMP
        );
    """,
    "hyper_node": """
        CREATE TABLE hyper_node (
            id SERIAL PRIMARY KEY,
            tenant VARCHAR(255),
            space VARCHAR(255),
            graph VARCHAR(255),
            channel VARCHAR(255),
            parent_cluster_id VARCHAR(1024),
            cluster_id VARCHAR(1024),
            cid_0 BOOLEAN, cid_1 BOOLEAN, cid_2 BOOLEAN, cid_3 BOOLEAN,
            cid_4 BOOLEAN, cid_5 BOOLEAN, cid_6 BOOLEAN, cid_7 BOOLEAN,
            uri VARCHAR(255),
            type_uri VARCHAR(255),
            type_uri_list JSONB,
            update_time TIMESTAMP
        );
    """,
    "hyper_edge": """
        CREATE TABLE hyper_edge (
            id SERIAL PRIMARY KEY,
            tenant VARCHAR(255),
            space VARCHAR(255),
            graph VARCHAR(255),
            channel VARCHAR(255),
            parent_cluster_id VARCHAR(1024),
            cluster_id VARCHAR(1024),
            cid_0 BOOLEAN, cid_1 BOOLEAN, cid_2 BOOLEAN, cid_3 BOOLEAN,
            cid_4 BOOLEAN, cid_5 BOOLEAN, cid_6 BOOLEAN, cid_7 BOOLEAN,
            uri VARCHAR(255),
            source_uri VARCHAR(255),
            destination_uri VARCHAR(255),
            type_uri VARCHAR(255),
            type_uri_list JSONB,
            update_time TIMESTAMP
        );
    """,
    "binary_data": """
        CREATE TABLE binary_data (
            id SERIAL PRIMARY KEY,
            tenant VARCHAR(255),
            space VARCHAR(255),
            graph VARCHAR(255),
            uri VARCHAR(255),
            update_time TIMESTAMP
        );
    """,
    "document": """
        CREATE TABLE document (
            id SERIAL PRIMARY KEY,
            tenant VARCHAR(255),
            space VARCHAR(255),
            graph VARCHAR(255),
            uri VARCHAR(255),
            update_time TIMESTAMP
        );
    """,
    "binary_directory": """
        CREATE TABLE binary_directory (
            id SERIAL PRIMARY KEY,
            tenant VARCHAR(255),
            space VARCHAR(255),
            graph VARCHAR(255),
            uri VARCHAR(255),
            update_time TIMESTAMP
        );
    """,
    "binary_directory_edge": """
        CREATE TABLE binary_directory_edge (
            id SERIAL PRIMARY KEY,
            tenant VARCHAR(255),
            space VARCHAR(255),
            graph VARCHAR(255),
            uri VARCHAR(255),
            source_uri VARCHAR(255),
            destination_uri VARCHAR(255),
            update_time TIMESTAMP
        );
    """,
    "document_folder": """
        CREATE TABLE document_folder (
            id SERIAL PRIMARY KEY,
            tenant VARCHAR(255),
            space VARCHAR(255),
            graph VARCHAR(255),
            uri VARCHAR(255),
            update_time TIMESTAMP
        );
    """,
    "document_folder_edge": """
        CREATE TABLE document_folder_edge (
            id SERIAL PRIMARY KEY,
            tenant VARCHAR(255),
            space VARCHAR(255),
            graph VARCHAR(255),
            uri VARCHAR(255),
            source_uri VARCHAR(255),
            destination_uri VARCHAR(255),
            update_time TIMESTAMP
        );
    """,
}

async def main():
    conn = await asyncpg.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PASSWORD,
        database=PG_DATABASE,
    )

    # Drop tables if they exist
    for table in TABLES:
        await conn.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE;')
        print(f"Dropped {table} if it existed.")

    # Create tables
    for name, ddl in CREATE_STATEMENTS.items():
        await conn.execute(ddl)
        print(f"Created {name}.")

    await conn.close()
    print("All done.")

if __name__ == "__main__":
    asyncio.run(main())
