#!/usr/bin/env python3
"""
PostgreSQL Quad Dump Script

This script connects directly to the production PostgreSQL database and dumps
all quads for a given space to an NQuads file for debugging purposes.

It reads the production PostgreSQL connection info from the config file and
exports all quads from the space's term and rdf_quad tables.

Usage:
    python dump_postgresql_quads.py <space_id> [output_file]
    
Example:
    python dump_postgresql_quads.py space_realistic_org_test output.nq
"""

import sys
import asyncio
import asyncpg
import logging
from pathlib import Path
from typing import List, Tuple, Optional
import yaml

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)


class PostgreSQLQuadDumper:
    """Dump quads from PostgreSQL to NQuads file."""
    
    def __init__(self, config_path: str):
        """
        Initialize the dumper with production config.
        
        Args:
            config_path: Path to the production config YAML file
        """
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.connection_pool = None
    
    def _load_config(self) -> dict:
        """Load configuration from YAML file."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")
        
        with open(self.config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        logger.info(f"✅ Loaded configuration from {self.config_path}")
        return config
    
    def _get_postgresql_config(self) -> dict:
        """Extract PostgreSQL configuration from the config file."""
        # Check if this is a fuseki_postgresql backend
        backend_type = self.config.get('backend', {}).get('type', 'postgresql')
        
        if backend_type == 'fuseki_postgresql':
            # Get PostgreSQL config from fuseki_postgresql section
            pg_config = self.config.get('fuseki_postgresql', {}).get('database', {})
        else:
            # Standard PostgreSQL backend
            pg_config = self.config.get('backend', {})
        
        return {
            'host': pg_config.get('host', 'localhost'),
            'port': pg_config.get('port', 5432),
            'database': pg_config.get('database', 'vitalgraph'),
            'user': pg_config.get('username', 'vitalgraph_user'),
            'password': pg_config.get('password', ''),
        }
    
    async def connect(self) -> bool:
        """Connect to PostgreSQL database."""
        pg_config = self._get_postgresql_config()
        
        logger.info("=" * 80)
        logger.info("🔌 Connecting to PostgreSQL")
        logger.info("=" * 80)
        logger.info(f"Host: {pg_config['host']}")
        logger.info(f"Port: {pg_config['port']}")
        logger.info(f"Database: {pg_config['database']}")
        logger.info(f"User: {pg_config['user']}")
        
        try:
            self.connection_pool = await asyncpg.create_pool(
                host=pg_config['host'],
                port=pg_config['port'],
                database=pg_config['database'],
                user=pg_config['user'],
                password=pg_config['password'],
                min_size=1,
                max_size=5
            )
            
            logger.info("✅ Connected to PostgreSQL\n")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to connect to PostgreSQL: {e}")
            return False
    
    async def close(self):
        """Close PostgreSQL connection."""
        if self.connection_pool:
            await self.connection_pool.close()
            logger.info("✅ PostgreSQL connection closed")
    
    async def get_space_tables(self, space_id: str) -> Tuple[str, str]:
        """
        Get the term and quad table names for a space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            Tuple of (term_table, quad_table)
        """
        prefix = f"{space_id}_"
        term_table = f"{prefix}term"
        quad_table = f"{prefix}rdf_quad"
        
        return term_table, quad_table
    
    async def verify_tables_exist(self, space_id: str) -> bool:
        """
        Verify that the space tables exist.
        
        Args:
            space_id: Space identifier
            
        Returns:
            True if tables exist, False otherwise
        """
        term_table, quad_table = await self.get_space_tables(space_id)
        
        logger.info("=" * 80)
        logger.info("🔍 Verifying Space Tables")
        logger.info("=" * 80)
        logger.info(f"Space ID: {space_id}")
        logger.info(f"Term table: {term_table}")
        logger.info(f"Quad table: {quad_table}")
        
        async with self.connection_pool.acquire() as conn:
            # Check term table
            term_exists = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = $1
                )
                """,
                term_table
            )
            
            # Check quad table
            quad_exists = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = $1
                )
                """,
                quad_table
            )
            
            if term_exists and quad_exists:
                logger.info("✅ Both tables exist\n")
                return True
            else:
                if not term_exists:
                    logger.error(f"❌ Term table '{term_table}' does not exist")
                if not quad_exists:
                    logger.error(f"❌ Quad table '{quad_table}' does not exist")
                logger.error("")
                return False
    
    async def get_quad_count(self, space_id: str) -> int:
        """
        Get the total number of quads for a space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            Number of quads
        """
        _, quad_table = await self.get_space_tables(space_id)
        
        async with self.connection_pool.acquire() as conn:
            count = await conn.fetchval(f"SELECT COUNT(*) FROM {quad_table}")
            return count
    
    async def dump_quads_to_nquads(self, space_id: str, output_file: str) -> bool:
        """
        Dump all quads for a space to an NQuads file.
        
        Args:
            space_id: Space identifier
            output_file: Path to output NQuads file
            
        Returns:
            True if successful, False otherwise
        """
        term_table, quad_table = await self.get_space_tables(space_id)
        
        # Get quad count
        quad_count = await self.get_quad_count(space_id)
        
        logger.info("=" * 80)
        logger.info("📦 Dumping Quads to NQuads File")
        logger.info("=" * 80)
        logger.info(f"Space ID: {space_id}")
        logger.info(f"Total quads: {quad_count}")
        logger.info(f"Output file: {output_file}")
        logger.info("")
        
        if quad_count == 0:
            logger.warning("⚠️  No quads found for this space")
            return False
        
        try:
            # Query to join quads with terms to get the actual text values
            query = f"""
            SELECT 
                s_term.term_text as subject,
                s_term.term_type as subject_type,
                p_term.term_text as predicate,
                o_term.term_text as object,
                o_term.term_type as object_type,
                c_term.term_text as context
            FROM {quad_table} q
            JOIN {term_table} s_term ON q.subject_uuid = s_term.term_uuid
            JOIN {term_table} p_term ON q.predicate_uuid = p_term.term_uuid
            JOIN {term_table} o_term ON q.object_uuid = o_term.term_uuid
            JOIN {term_table} c_term ON q.context_uuid = c_term.term_uuid
            ORDER BY q.created_time
            """
            
            async with self.connection_pool.acquire() as conn:
                rows = await conn.fetch(query)
                
                logger.info(f"📝 Writing {len(rows)} quads to file...")
                
                with open(output_file, 'w', encoding='utf-8') as f:
                    for i, row in enumerate(rows, 1):
                        # Format as NQuads: <subject> <predicate> <object> <graph> .
                        subject = self._format_term(row['subject'], row['subject_type'])
                        predicate = f"<{row['predicate']}>"
                        obj = self._format_term(row['object'], row['object_type'])
                        context = f"<{row['context']}>"
                        
                        nquad = f"{subject} {predicate} {obj} {context} .\n"
                        f.write(nquad)
                        
                        # Progress indicator
                        if i % 100 == 0:
                            logger.info(f"   Written {i}/{len(rows)} quads...")
                
                logger.info(f"✅ Successfully wrote {len(rows)} quads to {output_file}\n")
                return True
                
        except Exception as e:
            logger.error(f"❌ Error dumping quads: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _format_term(self, term_text: str, term_type: str) -> str:
        """
        Format a term for NQuads output based on its type.
        
        Args:
            term_text: The term text
            term_type: The term type (U=URI, L=Literal, B=Blank)
            
        Returns:
            Formatted term string
        """
        if term_type == 'U':
            # URI
            return f"<{term_text}>"
        elif term_type == 'B':
            # Blank node
            return term_text if term_text.startswith('_:') else f"_:{term_text}"
        else:
            # Literal (L) or default
            # Check if it already has quotes
            if term_text.startswith('"') and term_text.endswith('"'):
                return term_text
            else:
                # Escape quotes and backslashes in the literal
                escaped = term_text.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r')
                return f'"{escaped}"'
    
    async def show_quad_statistics(self, space_id: str):
        """
        Show statistics about the quads in a space.
        
        Args:
            space_id: Space identifier
        """
        term_table, quad_table = await self.get_space_tables(space_id)
        
        logger.info("=" * 80)
        logger.info("📊 Quad Statistics")
        logger.info("=" * 80)
        
        async with self.connection_pool.acquire() as conn:
            # Total quads
            total_quads = await conn.fetchval(f"SELECT COUNT(*) FROM {quad_table}")
            logger.info(f"Total quads: {total_quads}")
            
            # Unique subjects
            unique_subjects = await conn.fetchval(
                f"SELECT COUNT(DISTINCT subject_uuid) FROM {quad_table}"
            )
            logger.info(f"Unique subjects: {unique_subjects}")
            
            # Unique predicates
            unique_predicates = await conn.fetchval(
                f"SELECT COUNT(DISTINCT predicate_uuid) FROM {quad_table}"
            )
            logger.info(f"Unique predicates: {unique_predicates}")
            
            # Unique contexts/graphs
            unique_contexts = await conn.fetchval(
                f"SELECT COUNT(DISTINCT context_uuid) FROM {quad_table}"
            )
            logger.info(f"Unique graphs: {unique_contexts}")
            
            # Total terms
            total_terms = await conn.fetchval(f"SELECT COUNT(*) FROM {term_table}")
            logger.info(f"Total terms: {total_terms}")
            
            # Quads by graph
            logger.info("\nQuads by graph:")
            graph_counts = await conn.fetch(
                f"""
                SELECT c_term.term_text as graph, COUNT(*) as count
                FROM {quad_table} q
                JOIN {term_table} c_term ON q.context_uuid = c_term.term_uuid
                GROUP BY c_term.term_text
                ORDER BY count DESC
                """
            )
            
            for row in graph_counts:
                graph_short = row['graph'].split('/')[-1] if '/' in row['graph'] else row['graph']
                logger.info(f"   {graph_short}: {row['count']} quads")
            
            logger.info("")


async def main():
    """Main entry point for the script."""
    if len(sys.argv) < 2:
        logger.error("Usage: python dump_postgresql_quads.py <space_id> [output_file]")
        logger.error("")
        logger.error("Example:")
        logger.error("  python dump_postgresql_quads.py space_realistic_org_test output.nq")
        sys.exit(1)
    
    space_id = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else f"{space_id}_quads.nq"
    
    # Find config file
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    config_path = project_root / "vitalgraphdb_config" / "vitalgraphdb-config-production.yaml"
    
    if not config_path.exists():
        logger.error(f"❌ Config file not found: {config_path}")
        logger.error("   Please ensure the production config file exists")
        sys.exit(1)
    
    logger.info("")
    logger.info("🚀 PostgreSQL Quad Dump Tool")
    logger.info("")
    
    dumper = PostgreSQLQuadDumper(str(config_path))
    
    try:
        # Connect to PostgreSQL
        if not await dumper.connect():
            sys.exit(1)
        
        # Verify tables exist
        if not await dumper.verify_tables_exist(space_id):
            logger.error(f"❌ Space '{space_id}' tables do not exist in PostgreSQL")
            sys.exit(1)
        
        # Show statistics
        await dumper.show_quad_statistics(space_id)
        
        # Dump quads to file
        if await dumper.dump_quads_to_nquads(space_id, output_file):
            logger.info("=" * 80)
            logger.info("🎉 Quad dump completed successfully!")
            logger.info("=" * 80)
            logger.info("")
            logger.info(f"✅ Quads exported to: {output_file}")
            logger.info("")
            logger.info("You can now:")
            logger.info(f"  • View the file: cat {output_file}")
            logger.info(f"  • Load into another triplestore")
            logger.info(f"  • Use for debugging and analysis")
            logger.info("")
            sys.exit(0)
        else:
            sys.exit(1)
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        await dumper.close()


if __name__ == "__main__":
    asyncio.run(main())
