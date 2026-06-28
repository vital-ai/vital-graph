#!/usr/bin/env python3
"""
Create missing indexes for SPARQL query performance optimization.
These indexes are critical for JOIN performance and COUNT query optimization.
"""

import sys
import subprocess
import argparse
from typing import List

def generate_index_commands(space_id: str) -> List[str]:
    """Generate all the CREATE INDEX commands for the given space."""
    
    table_prefix = f"vitalgraph2__{space_id}__"
    idx_prefix = f"idx_{table_prefix}"
    
    commands = []
    
    # Indexes on rdf_quad_primary table for JOIN columns
    commands.extend([
        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {idx_prefix}rdf_quad_primary_subject_uuid ON {table_prefix}rdf_quad_primary (subject_uuid);",
        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {idx_prefix}rdf_quad_primary_predicate_uuid ON {table_prefix}rdf_quad_primary (predicate_uuid);",
        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {idx_prefix}rdf_quad_primary_object_uuid ON {table_prefix}rdf_quad_primary (object_uuid);",
        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {idx_prefix}rdf_quad_primary_context_uuid ON {table_prefix}rdf_quad_primary (context_uuid);",
    ])
    
    # Indexes on term_primary table for JOIN columns
    commands.extend([
        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {idx_prefix}term_primary_term_uuid ON {table_prefix}term_primary (term_uuid);",
        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {idx_prefix}term_primary_term_text ON {table_prefix}term_primary (term_text);",
        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {idx_prefix}term_primary_term_type ON {table_prefix}term_primary (term_type);",
        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {idx_prefix}term_primary_text_type ON {table_prefix}term_primary (term_text, term_type);",
    ])
    
    # SPARQL-optimized composite index
    commands.append(
        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {idx_prefix}rdf_quad_primary_spoc ON {table_prefix}rdf_quad_primary (subject_uuid, predicate_uuid, object_uuid, context_uuid);"
    )
    
    # Indexes on partitioned parent tables (cannot use CONCURRENTLY)
    commands.extend([
        f"CREATE INDEX IF NOT EXISTS {idx_prefix}rdf_quad_subject_uuid ON {table_prefix}rdf_quad (subject_uuid);",
        f"CREATE INDEX IF NOT EXISTS {idx_prefix}rdf_quad_predicate_uuid ON {table_prefix}rdf_quad (predicate_uuid);",
        f"CREATE INDEX IF NOT EXISTS {idx_prefix}rdf_quad_object_uuid ON {table_prefix}rdf_quad (object_uuid);",
        f"CREATE INDEX IF NOT EXISTS {idx_prefix}rdf_quad_context_uuid ON {table_prefix}rdf_quad (context_uuid);",
        f"CREATE INDEX IF NOT EXISTS {idx_prefix}rdf_quad_uuid ON {table_prefix}rdf_quad (quad_uuid);",
        f"CREATE INDEX IF NOT EXISTS {idx_prefix}rdf_quad_dataset ON {table_prefix}rdf_quad (dataset);",
    ])
    
    # Term table indexes (critical for COUNT query performance) - cannot use CONCURRENTLY
    commands.extend([
        f"CREATE INDEX IF NOT EXISTS {idx_prefix}term_term_text ON {table_prefix}term (term_text);",
        f"CREATE INDEX IF NOT EXISTS {idx_prefix}term_term_type ON {table_prefix}term (term_type);",
        f"CREATE INDEX IF NOT EXISTS {idx_prefix}term_dataset ON {table_prefix}term (dataset);",
        f"CREATE INDEX IF NOT EXISTS {idx_prefix}term_text_type ON {table_prefix}term (term_text, term_type);",
    ])
    
    # Full-text search indexes using trigram extension (if pg_trgm is available) - cannot use CONCURRENTLY
    commands.extend([
        f"CREATE INDEX IF NOT EXISTS {idx_prefix}term_text_gin_trgm ON {table_prefix}term USING gin (term_text gin_trgm_ops);",
        f"CREATE INDEX IF NOT EXISTS {idx_prefix}term_text_gist_trgm ON {table_prefix}term USING gist (term_text gist_trgm_ops);",
    ])
    
    # Additional indexes for CSV import partition tables (if they exist)
    csv_table_suffix = f"csv_{space_id}"
    commands.extend([
        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {idx_prefix}rdf_quad_{csv_table_suffix}_subject_uuid ON {table_prefix}rdf_quad_{csv_table_suffix} (subject_uuid);",
        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {idx_prefix}rdf_quad_{csv_table_suffix}_context_uuid ON {table_prefix}rdf_quad_{csv_table_suffix} (context_uuid);",
        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {idx_prefix}term_{csv_table_suffix}_term_text ON {table_prefix}term_{csv_table_suffix} (term_text);",
        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {idx_prefix}term_{csv_table_suffix}_term_type ON {table_prefix}term_{csv_table_suffix} (term_type);",
    ])
    
    return commands

def run_psql_command(command: str, host: str = "host.docker.internal", port: int = 5432, 
                    user: str = "postgres", database: str = "vitalgraphdb") -> bool:
    """Run a single psql command and return success status."""
    try:
        result = subprocess.run([
            "psql-17", "-h", host, "-p", str(port), "-U", user, "-d", database, "-c", command
        ], capture_output=True, text=True, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {command}")
        print(f"Error: {e.stderr}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Create missing indexes for VitalGraph space")
    parser.add_argument("space_id", help="Space ID (e.g., import_001)")
    parser.add_argument("--host", default="host.docker.internal", help="PostgreSQL host")
    parser.add_argument("--port", type=int, default=5432, help="PostgreSQL port")
    parser.add_argument("--user", default="postgres", help="PostgreSQL user")
    parser.add_argument("--database", default="vitalgraphdb", help="PostgreSQL database")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing")
    
    args = parser.parse_args()
    
    print(f"Creating missing indexes for space: {args.space_id}")
    
    commands = generate_index_commands(args.space_id)
    
    if args.dry_run:
        print("\nCommands that would be executed:")
        for i, cmd in enumerate(commands, 1):
            print(f"{i:2d}. {cmd}")
        return
    
    print(f"Executing {len(commands)} index creation commands...")
    
    success_count = 0
    error_count = 0
    
    for i, command in enumerate(commands, 1):
        print(f"[{i:2d}/{len(commands)}] Creating index...", end=" ", flush=True)
        
        if run_psql_command(command, args.host, args.port, args.user, args.database):
            print("✓")
            success_count += 1
        else:
            print("✗")
            error_count += 1
    
    print(f"\nResults: {success_count} successful, {error_count} errors")
    
    if error_count == 0:
        print("🎉 All indexes created successfully!")
        print("\nThese indexes should dramatically improve COUNT query performance in:")
        print("- GraphObjects listing")
        print("- KGEntities listing") 
        print("- KGFrames listing")
        print("- SPARQL queries with JOINs")
    else:
        print(f"⚠️  {error_count} indexes failed to create. Check the errors above.")
        sys.exit(1)

if __name__ == "__main__":
    main()
