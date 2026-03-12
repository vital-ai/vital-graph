"""
PostgreSQL Space Database Import Module

Handles efficient bulk import of RDF data using PostgreSQL COPY and UNLOGGED tables.
Implements Phase 2 of the efficient import process design.
"""

import logging
import os
import csv
import tempfile
import time
import uuid
import asyncio
from typing import Dict, List, Optional, Any, Tuple
from psycopg import sql


# Get logger for this module
logger = logging.getLogger(__name__)


class PostgreSQLSpaceDBImport:
    """
    Handles efficient bulk import of RDF data into PostgreSQL using UNLOGGED temp tables
    and PostgreSQL COPY for maximum performance.
    """
    
    def __init__(self, space_impl):
        """Initialize with reference to PostgreSQL space implementation."""
        self.space_impl = space_impl
        self.core = space_impl.core
        self.global_prefix = space_impl.global_prefix
        
    async def bulk_import_ntriples(
        self, 
        file_path: str, 
        graph_uri: str,
        batch_size: int = 50000,
        progress_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        Bulk import N-Triples file into UNLOGGED temp table using PostgreSQL COPY.
        
        This implements Phase 2 of the efficient import process:
        1. Parse N-Triples file using pyoxigraph
        2. Convert to CSV format
        3. Create UNLOGGED temp table
        4. Use PostgreSQL COPY for bulk loading
        
        Args:
            file_path: Path to N-Triples file
            graph_uri: Target graph URI for imported data
            batch_size: Number of triples to process in each batch
            progress_callback: Optional callback for progress updates
            
        Returns:
            Dict with import statistics and temp table name
        """
        start_time = time.time()
        import_id = str(uuid.uuid4())
        temp_table_name = f"temp_import_{import_id.replace('-', '_')}"
        
        logger.info(f"Starting bulk import of {file_path} into temp table {temp_table_name}")
        
        stats = {
            'import_id': import_id,
            'temp_table_name': temp_table_name,
            'file_path': file_path,
            'graph_uri': graph_uri,
            'total_triples': 0,
            'processed_triples': 0,
            'parsing_time': 0,
            'copy_time': 0,
            'total_time': 0
        }
        
        try:
            # Phase 2.1: Create UNLOGGED temp table
            await self._create_temp_import_table(temp_table_name)
            
            # Phase 2.2: Parse N-Triples and convert to CSV
            parsing_start = time.time()
            csv_file_path = await self._convert_ntriples_to_csv(
                file_path, graph_uri, batch_size, progress_callback, stats
            )
            stats['parsing_time'] = time.time() - parsing_start
            
            # Phase 2.3: Bulk load CSV into temp table using COPY
            copy_start = time.time()
            await self._bulk_copy_csv_to_table(csv_file_path, temp_table_name, stats)
            stats['copy_time'] = time.time() - copy_start
            
            # Clean up CSV file
            if os.path.exists(csv_file_path):
                os.unlink(csv_file_path)
                
            stats['total_time'] = time.time() - start_time
            
            logger.info(f"Bulk import completed: {stats['total_triples']} triples in {stats['total_time']:.2f}s")
            return stats
            
        except Exception as e:
            logger.error(f"Bulk import failed: {e}")
            # Clean up temp table on error
            try:
                await self._cleanup_temp_table(temp_table_name)
            except Exception as cleanup_error:
                logger.warning(f"Failed to drop temp table {temp_table_name}: {cleanup_error}")
            raise

    async def setup_partition_import_session(self, space_id: str, graph_uri: str, batch_size: int = 100000, import_id: str = None) -> dict:
        """
        Setup partition import session with temp tables that have identical schema to main tables.
        
        Creates UNLOGGED temp tables with the same schema as main tables but without partitioning
        (since UNLOGGED tables cannot be partitioned). These tables can later be converted to 
        LOGGED and attached as partitions for zero-copy import.
        
        Args:
            import_id: Optional import ID, will generate UUID if not provided
            space_id: Optional space ID for table naming
            
        Returns:
            Dict containing import session information with table names and metadata
        """
        if import_id is None:
            # Generate shorter import ID to avoid space ID length limits
            import_id = str(uuid.uuid4())[:8]
            
        dataset_value = f"import-{import_id}"
        
        # Get main table names and schema
        if space_id:
            table_names = self.space_impl._get_table_names(space_id)
            schema = self.space_impl._get_schema(space_id)
        else:
            # Use default schema without space_id
            from .postgresql_space_schema import PostgreSQLSpaceSchema
            schema = PostgreSQLSpaceSchema(self.global_prefix, "temp")
            table_names = schema.get_table_names()
        
        # Generate temp table names
        temp_table_suffix = import_id.replace('-', '_')
        temp_term_table = f"temp_term_import_{temp_table_suffix}"
        temp_quad_table = f"temp_quad_import_{temp_table_suffix}"
        
        # Get main table names for constraint naming
        main_term_table = table_names.get('term') if space_id else None
        main_quad_table = table_names.get('rdf_quad') if space_id else None
        
        logger.info(f"Setting up partition import session {import_id}")
        logger.info(f"Dataset value: {dataset_value}")
        logger.info(f"Temp tables: {temp_term_table}, {temp_quad_table}")
        
        async with self.space_impl.get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Create temp quad table with raw string data + UUIDs (matching CSV format)
                cursor.execute(f"""
                    CREATE UNLOGGED TABLE {temp_quad_table} (
                        subject_text TEXT NOT NULL,
                        predicate_text TEXT NOT NULL,
                        object_text TEXT NOT NULL,
                        object_datatype TEXT NOT NULL DEFAULT '',
                        object_language VARCHAR(20) NOT NULL DEFAULT '',
                        is_literal BOOLEAN NOT NULL,
                        graph_text TEXT NOT NULL,
                        import_batch_id TEXT NOT NULL DEFAULT 'batch_1',
                        subject_uuid UUID NOT NULL,
                        predicate_uuid UUID NOT NULL,
                        object_uuid UUID NOT NULL,
                        context_uuid UUID NOT NULL,
                        processing_status TEXT NOT NULL DEFAULT 'processed',
                        dataset VARCHAR(50) NOT NULL DEFAULT '{dataset_value}',
                        quad_uuid UUID NOT NULL DEFAULT gen_random_uuid(),
                        created_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Add dataset CHECK constraint with NOT VALID to eliminate ATTACH PARTITION validation scan
                cursor.execute(f"""
                    ALTER TABLE {temp_quad_table} 
                    ADD CONSTRAINT {temp_quad_table}_dataset_check 
                    CHECK (dataset = '{dataset_value}') NOT VALID
                """)
                
                logger.info(f"Created temp table: {temp_quad_table}")
                
                # Also create temp term table for partition import compatibility
                cursor.execute(f"""
                    CREATE UNLOGGED TABLE {temp_term_table} (
                        term_uuid UUID NOT NULL,
                        term_text TEXT NOT NULL,
                        term_type CHAR(1) NOT NULL,
                        lang VARCHAR(20) NOT NULL DEFAULT '',
                        datatype_id BIGINT NOT NULL DEFAULT 0,
                        created_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        dataset VARCHAR(50) NOT NULL DEFAULT '{dataset_value}',
                        PRIMARY KEY (term_uuid, dataset)
                    )
                """)
                
                logger.info(f"Created temp table: {temp_term_table}")
                
                # Add dataset CHECK constraint with NOT VALID to eliminate ATTACH PARTITION validation scan
                cursor.execute(f"""
                    ALTER TABLE {temp_term_table} 
                    ADD CONSTRAINT {temp_term_table}_dataset_check 
                    CHECK (dataset = '{dataset_value}') NOT VALID
                """)
                
                # Create basic indexes for performance during data loading
                cursor.execute(f"""
                    CREATE INDEX idx_{temp_table_suffix}_dataset ON {temp_quad_table} (dataset)
                """)
                cursor.execute(f"""
                    CREATE INDEX idx_{temp_table_suffix}_term_dataset ON {temp_term_table} (dataset)
                """)
                
                # Add CHECK constraints to match main table constraints for partition attachment
                # Use the same naming pattern as main tables for successful partition attachment
                if main_term_table:
                    main_term_constraint = f"{main_term_table}_term_type_check"
                    cursor.execute(f"""
                        ALTER TABLE {temp_term_table} 
                        ADD CONSTRAINT {main_term_constraint} 
                        CHECK (term_type IN ('U', 'L', 'B', 'G'))
                    """)
                
                if main_quad_table:
                    main_quad_constraint = f"{main_quad_table}_object_type_check"
                    cursor.execute(f"""
                        ALTER TABLE {temp_quad_table} 
                        ADD CONSTRAINT {main_quad_constraint} 
                        CHECK (is_literal IN (true, false))
                    """)
        
        # Determine if main tables are partitioned (always True for logged tables)
        main_tables_partitioned = True if space_id else False
        
        import_session = {
            'import_id': import_id,
            'dataset_value': dataset_value,
            'temp_term_table': temp_term_table,
            'temp_quad_table': temp_quad_table,
            'main_term_table': main_term_table,
            'main_quad_table': main_quad_table,
            'main_tables_partitioned': main_tables_partitioned,
            'space_id': space_id,
            'created_time': time.time()
        }
        
        logger.info(f"Partition import session setup completed: {import_id}")
        return import_session

    async def load_ntriples_into_partition_session(self, import_session: dict, file_path: str, graph_uri: str, batch_size: int = 50000, progress_callback: Optional[callable] = None) -> Dict[str, Any]:
        """
        Phase 2-3: Load N-Triples data into partition import session temp tables.
        
        Follows the same process as bulk_import_ntriples but loads into partition session temp tables:
        1. Parse N-Triples and create CSV with raw string data (Phase 2)
        2. Load CSV into temp table using COPY (Phase 2)
        3. Process terms and assign UUIDs (Phase 3)
        
        Args:
            import_session: Import session from setup_partition_import_session()
            file_path: Path to N-Triples file
            graph_uri: Target graph URI for imported data
            batch_size: Number of triples to process in each batch
            progress_callback: Optional callback for progress updates
            
        Returns:
            Dict with import statistics
        """
        start_time = time.time()
        temp_table_name = import_session['temp_quad_table']  # Use quad table as main temp table
        dataset_value = import_session['dataset_value']
        
        logger.info(f"Loading N-Triples {file_path} into partition session {import_session['import_id']}")
        
        stats = {
            'import_id': import_session['import_id'],
            'temp_table_name': temp_table_name,
            'file_path': file_path,
            'graph_uri': graph_uri,
            'total_triples': 0,
            'processed_triples': 0,
            'parsing_time': 0,
            'copy_time': 0,
            'term_processing_time': 0,
            'total_time': 0
        }
        
        try:
            # Phase 2.1: Already have temp table from session setup
            
            # Phase 2: Parse N-Triples to CSV with deterministic UUIDs
            csv_file_path = await self._convert_ntriples_to_csv_for_partition_import(
                file_path, graph_uri, batch_size, progress_callback, stats, dataset_value
            )
            
            # Phase 2.3: Bulk load CSV into temp table using COPY
            copy_start = time.time()
            await self._load_csv_into_partition_quad_table(csv_file_path, temp_table_name, stats)
            stats['copy_time'] = time.time() - copy_start
            
            # Phase 3: Extract and deduplicate terms
            term_start = time.time()
            await self._extract_and_deduplicate_terms_for_partition(temp_table_name, import_session['temp_term_table'], dataset_value, stats)
            stats['term_processing_time'] = time.time() - term_start
            
            # Clean up CSV file
            if os.path.exists(csv_file_path):
                os.unlink(csv_file_path)
                
            stats['total_time'] = time.time() - start_time
            
            logger.info(f"Partition data loading completed: {stats['total_triples']} triples in {stats['total_time']:.2f}s")
            return stats
            
        except Exception as e:
            logger.error(f"Partition data loading failed: {e}")
            # Clean up CSV file on error
            if 'csv_file_path' in locals() and os.path.exists(csv_file_path):
                os.unlink(csv_file_path)
            raise

    async def _convert_ntriples_to_csv_for_partition_import(self, ntriples_file: str, graph_uri: str, batch_size: int, progress_callback: Optional[callable], stats: Dict[str, Any], dataset_value: str) -> str:
        """
        Parse N-Triples file and convert to CSV format for partition loading.
        Follows the same pattern as bulk import CSV generation.
        """
        from pyoxigraph import parse
        from .postgresql_space_terms import PostgreSQLSpaceTerms
        from functools import lru_cache
        import tempfile
        import csv
        import os
        
        logger.info("Using oxigraph for partition N-Triples parsing with cached UUID generation")
        
        # Create LRU cache for UUID generation
        @lru_cache(maxsize=100000)
        def cached_generate_uuid(term_text: str, term_type: str, lang: str = None) -> str:
            return str(PostgreSQLSpaceTerms.generate_term_uuid(term_text, term_type, lang=lang))
        
        # Create temporary CSV file
        csv_fd, csv_file_path = tempfile.mkstemp(suffix='.csv', prefix='vitalgraph_partition_import_')
        
        try:
            with os.fdopen(csv_fd, 'w', newline='', encoding='utf-8') as csv_file:
                csv_writer = csv.writer(csv_file, quoting=csv.QUOTE_NONNUMERIC)
                
                logger.info(f"Streaming oxigraph parse of N-Triples file: {ntriples_file}")
                
                batch_count = 0
                start_time = time.time()
                logger.info(f"Opening N-Triples file: {ntriples_file}")
                
                with open(ntriples_file, 'rb') as nt_file:
                    logger.info("Starting oxigraph parsing...")
                    for triple in parse(nt_file, "application/n-triples"):
                        if batch_count == 0:
                            logger.info("First triple parsed successfully")
                        elif batch_count % 100000 == 0:
                            logger.info(f"Parsed {batch_count} triples so far...")
                        
                        # Extract subject, predicate, object
                        subject_uri = str(triple.subject)
                        predicate_uri = str(triple.predicate)
                        
                        # Handle different object types using oxigraph's type system
                        obj = triple.object
                        if str(type(obj).__name__) == 'Literal':
                            object_value = str(obj)
                            # Extract datatype and language if present
                            if hasattr(obj, 'datatype') and obj.datatype:
                                object_datatype = str(obj.datatype)
                                object_language = ''  # Use empty string instead of None
                            elif hasattr(obj, 'language') and obj.language:
                                object_datatype = ''  # Use empty string instead of None
                                object_language = str(obj.language)
                            else:
                                object_datatype = ''  # Use empty string instead of None
                                object_language = ''  # Use empty string instead of None
                            is_literal = True
                        else:
                            # URI or blank node
                            object_value = str(obj)
                            object_datatype = ''  # Use empty string instead of None
                            object_language = ''  # Use empty string instead of None
                            is_literal = False
                        
                        # Generate deterministic UUIDs for all terms using cache
                        subject_uuid = cached_generate_uuid(subject_uri, 'U')
                        predicate_uuid = cached_generate_uuid(predicate_uri, 'U')
                        object_uuid = cached_generate_uuid(
                            object_value, 
                            'L' if is_literal else 'U',
                            lang=object_language
                        )
                        context_uuid = cached_generate_uuid(graph_uri, 'U')
                        
                        # Create CSV row with UUIDs and processed status (same as bulk import)
                        import_batch_id = f"batch_{batch_count // batch_size}"
                        triple_data = (
                            subject_uri, predicate_uri, object_value, 
                            object_datatype if object_datatype is not None else '', 
                            object_language if object_language is not None else '', 
                            is_literal, graph_uri, import_batch_id,
                            subject_uuid, predicate_uuid, object_uuid, context_uuid,
                            'processed',  # processing_status
                            dataset_value
                        )
                        
                        csv_writer.writerow(triple_data)
                        stats['total_triples'] += 1
                        batch_count += 1
                        
                        # Progress callback
                        if progress_callback and batch_count % 100000 == 0:
                            elapsed = time.time() - start_time
                            rate = batch_count / elapsed if elapsed > 0 else 0
                            progress_callback(batch_count, rate)
                            logger.info(f"Converted {stats['total_triples']} triples to CSV: {csv_file_path}")
                
                # Explicitly flush and sync the file before closing
                csv_file.flush()
                os.fsync(csv_file.fileno())
            
            logger.info(f"Converted {stats['total_triples']} triples to CSV: {csv_file_path}")
            return csv_file_path
                
        except Exception as e:
            # Clean up CSV file on error
            if os.path.exists(csv_file_path):
                os.unlink(csv_file_path)
            logger.error(f"N-Triples parsing failed: {e}")
            raise

    async def _load_csv_into_partition_quad_table(self, csv_file_path: str, temp_quad_table: str, stats: Dict[str, Any]):
        """Load CSV data into temp quad table using PostgreSQL COPY."""
        logger.info(f"Loading CSV into temp quad table: {temp_quad_table}")
        
        # Debug: Check CSV file size and first few lines
        import os
        file_size = os.path.getsize(csv_file_path)
        logger.info(f"CSV file size: {file_size:,} bytes")
        
        with open(csv_file_path, 'r', encoding='utf-8') as f:
            first_line = f.readline().strip()
            logger.info(f"First CSV line: {first_line[:200]}...")
        
        async with self.space_impl.get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Disable synchronous_commit for better performance
                cursor.execute("SET LOCAL synchronous_commit = OFF")
                
                # CSV data order: subject_uri, predicate_uri, object_value, object_datatype, object_language, is_literal, graph_uri, import_batch_id, subject_uuid, predicate_uuid, object_uuid, context_uuid, processing_status, dataset_value
                # COPY columns must match CSV order exactly - map CSV columns to temp table columns
                copy_sql = f"""
                    COPY {temp_quad_table} (
                        subject_text, predicate_text, object_text, 
                        object_datatype, object_language, is_literal, 
                        graph_text, import_batch_id,
                        subject_uuid, predicate_uuid, object_uuid, context_uuid,
                        processing_status, dataset
                    ) FROM STDIN WITH (FORMAT CSV, DELIMITER ',', QUOTE '"', ESCAPE '"', NULL '')
                """
                
                start_time = time.time()
                try:
                    # Perform COPY operation using fastest method - cursor.copy() with chunked streaming
                    with cursor.copy(copy_sql) as copy:
                        with open(csv_file_path, 'rb') as csv_file:  # Binary mode for fastest I/O
                            while True:
                                data = csv_file.read(65536)  # 64KB chunks for optimal performance
                                if not data:
                                    break
                                copy.write(data)
                    
                    load_time = time.time() - start_time
                    logger.info(f"COPY command executed successfully in {load_time:.2f}s")
                except Exception as copy_error:
                    logger.error(f"COPY command failed: {copy_error}")
                    raise
                
                # Get row count
                cursor.execute(f"SELECT COUNT(*) FROM {temp_quad_table}")
                row_count = cursor.fetchone()[0]
                
                stats['csv_load_time'] = load_time
                stats['loaded_rows'] = row_count
                
                logger.info(f"Loaded {row_count:,} rows into {temp_quad_table} in {load_time:.2f}s")

    async def _extract_and_deduplicate_terms_for_partition(self, temp_quad_table: str, temp_term_table: str, dataset_value: str, stats: Dict[str, Any]):
        """Extract distinct terms from temp quad table into temp term table using fast UNION ALL approach."""
        logger.info("Extracting terms for partition import using fast UNION ALL method")
        
        async with self.space_impl.get_db_connection() as conn:
            with conn.cursor() as cursor:
                start_time = time.time()
                
                # Use the same fast pattern as regular import - single UNION ALL query
                logger.info("Extracting all distinct terms with single UNION ALL query...")
                cursor.execute(f"""
                    INSERT INTO {temp_term_table} (term_uuid, term_text, term_type, dataset)
                    SELECT DISTINCT term_uuid, term_text, term_type, '{dataset_value}' as dataset FROM (
                        SELECT subject_uuid as term_uuid, subject_text as term_text, 'U' as term_type FROM {temp_quad_table}
                        UNION ALL
                        SELECT predicate_uuid as term_uuid, predicate_text as term_text, 'U' as term_type FROM {temp_quad_table}
                        UNION ALL
                        SELECT object_uuid as term_uuid, object_text as term_text, 
                               CASE WHEN is_literal THEN 'L' ELSE 'U' END as term_type FROM {temp_quad_table}
                        UNION ALL
                        SELECT context_uuid as term_uuid, graph_text as term_text, 'U' as term_type FROM {temp_quad_table}
                    ) t
                    WHERE term_uuid IS NOT NULL
                    ON CONFLICT (term_uuid, dataset) DO NOTHING
                """)
                
                total_inserted = cursor.rowcount
                dedupe_time = time.time() - start_time
                
                stats['term_dedupe_time'] = dedupe_time
                stats['new_terms_inserted'] = total_inserted
                
                logger.info(f"Inserted {total_inserted:,} new terms in {dedupe_time:.2f}s")

    async def attach_partitions_zero_copy(self, import_session: dict) -> Dict[str, Any]:
        """
        Phase 4: Zero-copy partition attachment for imported data.
        
        This method converts temp tables to partitions and attaches them to main tables
        for extremely fast data integration without copying.
        
        Falls back to regular INSERT if main tables are not partitioned.
        """
        logger.info(f"Attaching partitions for import session {import_session['import_id']}")
        
        temp_term_table = import_session['temp_term_table']
        temp_quad_table = import_session['temp_quad_table']
        main_term_table = import_session['main_term_table']
        main_quad_table = import_session['main_quad_table']
        dataset_value = import_session['dataset_value']
        
        stats = {
            'status': 'attached',
            'temp_term_table': temp_term_table,
            'temp_quad_table': temp_quad_table,
            'main_term_table': main_term_table,
            'main_quad_table': main_quad_table,
            'dataset_value': dataset_value
        }
        
        async with self.space_impl.get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Check if main tables are partitioned
                cursor.execute(f"""
                    SELECT partrelid FROM pg_partitioned_table 
                    WHERE partrelid = '{main_term_table}'::regclass
                """)
                term_partitioned = cursor.fetchone() is not None
                
                cursor.execute(f"""
                    SELECT partrelid FROM pg_partitioned_table 
                    WHERE partrelid = '{main_quad_table}'::regclass
                """)
                quad_partitioned = cursor.fetchone() is not None
                
                if not term_partitioned or not quad_partitioned:
                    logger.error(f"Main tables are not partitioned. Zero-copy partition attachment requires partitioned tables.")
                    logger.error(f"Term table partitioned: {term_partitioned}, Quad table partitioned: {quad_partitioned}")
                    raise ValueError("Zero-copy partition attachment requires partitioned main tables")
                
                # Continue with zero-copy partition attachment
                # Step 1: Drop extra columns from temp quad table to match main table schema
                logger.info(f"Dropping extra columns from {temp_quad_table} to match main table schema")
                cursor.execute(f"ALTER TABLE {temp_quad_table} DROP COLUMN subject_text")
                cursor.execute(f"ALTER TABLE {temp_quad_table} DROP COLUMN predicate_text")
                cursor.execute(f"ALTER TABLE {temp_quad_table} DROP COLUMN object_text")
                cursor.execute(f"ALTER TABLE {temp_quad_table} DROP COLUMN object_datatype")
                cursor.execute(f"ALTER TABLE {temp_quad_table} DROP COLUMN object_language")
                cursor.execute(f"ALTER TABLE {temp_quad_table} DROP COLUMN is_literal")
                cursor.execute(f"ALTER TABLE {temp_quad_table} DROP COLUMN graph_text")
                cursor.execute(f"ALTER TABLE {temp_quad_table} DROP COLUMN import_batch_id")
                cursor.execute(f"ALTER TABLE {temp_quad_table} DROP COLUMN processing_status")
                
                # Step 2: Convert UNLOGGED tables to LOGGED for partition attachment
                logger.info(f"Converting {temp_term_table} from UNLOGGED to LOGGED")
                cursor.execute(f"ALTER TABLE {temp_term_table} SET LOGGED")
                
                logger.info(f"Converting {temp_quad_table} from UNLOGGED to LOGGED")
                cursor.execute(f"ALTER TABLE {temp_quad_table} SET LOGGED")
                
                # Step 3: Verify dataset CHECK constraints are in place
                # This PostgreSQL 17 optimization should eliminate the validation scan during ATTACH PARTITION
                logger.info(f"Verifying CHECK constraints for dataset '{dataset_value}'")
                
                # Check what constraints exist on temp tables
                cursor.execute(f"""
                    SELECT conname, pg_get_constraintdef(oid) as definition
                    FROM pg_constraint 
                    WHERE conrelid = '{temp_term_table}'::regclass 
                    AND contype = 'c'
                """)
                term_constraints = cursor.fetchall()
                logger.info(f"Term table constraints: {term_constraints}")
                
                cursor.execute(f"""
                    SELECT conname, pg_get_constraintdef(oid) as definition
                    FROM pg_constraint 
                    WHERE conrelid = '{temp_quad_table}'::regclass 
                    AND contype = 'c'
                """)
                quad_constraints = cursor.fetchall()
                logger.info(f"Quad table constraints: {quad_constraints}")
                
                # Step 4: Attach temp tables as partitions
                logger.info(f"Attaching {temp_term_table} as partition to {main_term_table}")
                cursor.execute(f"""
                    ALTER TABLE {main_term_table} 
                    ATTACH PARTITION {temp_term_table} 
                    FOR VALUES IN ('{dataset_value}')
                """)
                
                logger.info(f"Attaching {temp_quad_table} as partition to {main_quad_table}")
                cursor.execute(f"""
                    ALTER TABLE {main_quad_table} 
                    ATTACH PARTITION {temp_quad_table} 
                    FOR VALUES IN ('{dataset_value}')
                """)
                
                # Step 5: Run ANALYZE on new partitions for optimal query planning
                logger.info(f"Running ANALYZE on new partitions for optimal query planning...")
                analyze_start = time.time()
                
                cursor.execute(f"ANALYZE {temp_term_table};")
                logger.info(f"  Analyzed partition: {temp_term_table}")
                
                cursor.execute(f"ANALYZE {temp_quad_table};")
                logger.info(f"  Analyzed partition: {temp_quad_table}")
                
                analyze_time = time.time() - analyze_start
                stats['analyze_time'] = analyze_time
                logger.info(f"Partition analysis completed in {analyze_time:.2f}s")
        
        # Step 6: Run VACUUM ANALYZE outside transaction for better statistics
        vacuum_stats = await self._vacuum_analyze_partitions(temp_term_table, temp_quad_table)
        stats.update(vacuum_stats)
        
        # Step 7: Run ANALYZE on parent partitioned tables for optimal SPARQL query planning
        parent_stats = await self._analyze_parent_partitioned_tables(space_id)
        stats.update(parent_stats)
        
        logger.info(f"Zero-copy partition attachment completed for import session {import_session['import_id']}")
        return stats

    async def _vacuum_analyze_partitions(self, temp_term_table: str, temp_quad_table: str) -> Dict[str, Any]:
        """
        Run VACUUM ANALYZE on partitions outside of transaction block for optimal statistics.
        
        This is critical for large datasets to ensure indexes perform optimally.
        """
        import time
        
        vacuum_start = time.time()
        stats = {}
        
        try:
            # Use a separate connection with autocommit for VACUUM operations
            async with self.space_impl.get_db_connection() as conn:
                # Enable autocommit mode for VACUUM operations
                conn.autocommit = True
                
                with conn.cursor() as cursor:
                    logger.info(f"Running VACUUM ANALYZE on partitions for optimal index performance...")
                    
                    # VACUUM ANALYZE term partition
                    term_vacuum_start = time.time()
                    cursor.execute(f"VACUUM ANALYZE {temp_term_table};")
                    term_vacuum_time = time.time() - term_vacuum_start
                    logger.info(f"  VACUUM ANALYZE completed for {temp_term_table} in {term_vacuum_time:.2f}s")
                    
                    # VACUUM ANALYZE quad partition  
                    quad_vacuum_start = time.time()
                    cursor.execute(f"VACUUM ANALYZE {temp_quad_table};")
                    quad_vacuum_time = time.time() - quad_vacuum_start
                    logger.info(f"  VACUUM ANALYZE completed for {temp_quad_table} in {quad_vacuum_time:.2f}s")
                    
                    total_vacuum_time = time.time() - vacuum_start
                    stats.update({
                        'vacuum_analyze_time': total_vacuum_time,
                        'term_vacuum_time': term_vacuum_time,
                        'quad_vacuum_time': quad_vacuum_time
                    })
                    
                    logger.info(f"VACUUM ANALYZE completed for all partitions in {total_vacuum_time:.2f}s")
                    
        except Exception as e:
            logger.warning(f"VACUUM ANALYZE failed, but partitions are still functional: {e}")
            stats['vacuum_analyze_error'] = str(e)
        
        return stats

    async def _analyze_parent_partitioned_tables(self, space_id: str) -> Dict[str, Any]:
        """
        Run ANALYZE on parent partitioned tables for optimal SPARQL query planning.
        
        This is critical after partition attachment to ensure PostgreSQL has proper
        statistics for the entire partitioned table structure.
        """
        import time
        
        analyze_start = time.time()
        stats = {}
        
        try:
            # Get table names for the space
            table_names = self.space_impl._get_table_names(space_id)
            parent_term_table = table_names['term']
            parent_quad_table = table_names['rdf_quad']
            
            # Use a separate connection for ANALYZE operations
            async with self.space_impl.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    logger.info(f"Running ANALYZE on parent partitioned tables for optimal SPARQL performance...")
                    
                    # ANALYZE parent term table
                    term_analyze_start = time.time()
                    cursor.execute(f"ANALYZE {parent_term_table};")
                    term_analyze_time = time.time() - term_analyze_start
                    logger.info(f"  ANALYZE completed for parent table {parent_term_table} in {term_analyze_time:.2f}s")
                    
                    # ANALYZE parent quad table  
                    quad_analyze_start = time.time()
                    cursor.execute(f"ANALYZE {parent_quad_table};")
                    quad_analyze_time = time.time() - quad_analyze_start
                    logger.info(f"  ANALYZE completed for parent table {parent_quad_table} in {quad_analyze_time:.2f}s")
                    
                    total_analyze_time = time.time() - analyze_start
                    stats.update({
                        'parent_analyze_time': total_analyze_time,
                        'parent_term_analyze_time': term_analyze_time,
                        'parent_quad_analyze_time': quad_analyze_time
                    })
                    
                    logger.info(f"Parent table ANALYZE completed in {total_analyze_time:.2f}s - SPARQL queries now optimized")
                    
        except Exception as e:
            logger.warning(f"Parent table ANALYZE failed, but import is still successful: {e}")
            stats['parent_analyze_error'] = str(e)
        
        return stats

    async def _vacuum_analyze_main_tables(self, term_table: str, quad_table: str) -> Dict[str, Any]:
        """
        Run VACUUM ANALYZE on main tables outside of transaction block for optimal statistics.
        
        This is critical for large datasets to ensure indexes perform optimally after traditional import.
        """
        import time
        
        vacuum_start = time.time()
        stats = {}
        
        try:
            # Use a separate connection with autocommit for VACUUM operations
            async with self.space_impl.get_db_connection() as conn:
                # Enable autocommit mode for VACUUM operations
                conn.autocommit = True
                
                with conn.cursor() as cursor:
                    logger.info(f"Running VACUUM ANALYZE on main tables for optimal index performance...")
                    
                    # VACUUM ANALYZE term table
                    term_vacuum_start = time.time()
                    cursor.execute(f"VACUUM ANALYZE {term_table};")
                    term_vacuum_time = time.time() - term_vacuum_start
                    logger.info(f"  VACUUM ANALYZE completed for {term_table} in {term_vacuum_time:.2f}s")
                    
                    # VACUUM ANALYZE quad table  
                    quad_vacuum_start = time.time()
                    cursor.execute(f"VACUUM ANALYZE {quad_table};")
                    quad_vacuum_time = time.time() - quad_vacuum_start
                    logger.info(f"  VACUUM ANALYZE completed for {quad_table} in {quad_vacuum_time:.2f}s")
                    
                    total_vacuum_time = time.time() - vacuum_start
                    stats.update({
                        'vacuum_analyze_time': total_vacuum_time,
                        'term_vacuum_time': term_vacuum_time,
                        'quad_vacuum_time': quad_vacuum_time
                    })
                    
                    logger.info(f"VACUUM ANALYZE completed for main tables in {total_vacuum_time:.2f}s")
                    
        except Exception as e:
            logger.warning(f"VACUUM ANALYZE failed on main tables, but import is still successful: {e}")
            stats['vacuum_analyze_error'] = str(e)
        
        return stats

    async def transfer_partition_data_to_main_tables(self, import_session: dict, space_id: str, graph_uri: str) -> Dict[str, Any]:
        """
        Transfer data from partition session temp tables to main tables using traditional INSERT method.
        
        This method provides the same index optimization as transfer_to_main_tables_phase4 but works
        with partition session temp tables that have the correct schema for partitioned main tables.
        
        Args:
            import_session: Import session from setup_partition_import_session()
            space_id: Target space ID
            graph_uri: Target graph URI
            
        Returns:
            Dict with transfer statistics and performance metrics
        """
        start_time = time.time()
        temp_term_table = import_session['temp_term_table']
        temp_quad_table = import_session['temp_quad_table']
        dataset_value = import_session['dataset_value']
        
        logger.info(f"Starting traditional transfer from partition session to main tables for space '{space_id}'")
        
        # Get table names for the space
        table_names = self.space_impl._get_table_names(space_id)
        quad_table = table_names['rdf_quad']
        term_table = table_names['term']
        
        phase4_stats = {
            'phase': 'traditional_transfer_from_partition_session',
            'start_time': start_time,
            'terms_transferred': 0,
            'quads_transferred': 0,
            'term_transfer_time': 0,
            'quad_transfer_time': 0,
            'index_drop_time': 0,
            'index_recreate_time': 0,
            'analyze_time': 0,
            'total_time': 0
        }
        
        try:
            async with self.space_impl.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Verify temp tables have data
                    cursor.execute(f"SELECT COUNT(*) FROM {temp_term_table}")
                    term_count = cursor.fetchone()[0]
                    cursor.execute(f"SELECT COUNT(*) FROM {temp_quad_table}")
                    quad_count = cursor.fetchone()[0]
                    
                    logger.info(f"Found {term_count:,} terms and {quad_count:,} quads ready for transfer")
                    
                    # Step 0: Drop ALL indexes for maximum bulk transfer performance
                    logger.info("Step 0: Dropping ALL indexes for maximum bulk transfer performance...")
                    index_drop_start = time.time()
                    
                    # Get schema for index management
                    from .postgresql_space_schema import PostgreSQLSpaceSchema
                    schema = PostgreSQLSpaceSchema(self.space_impl.global_prefix, space_id)
                    
                    # Drop all indexes using schema's drop method
                    drop_index_sql_list = schema.get_drop_indexes_sql()
                    dropped_indexes = []
                    
                    for drop_sql in drop_index_sql_list:
                        try:
                            cursor.execute(drop_sql)
                            # Extract index name from SQL for logging
                            index_name = drop_sql.split("EXISTS ")[1].split(";")[0] if "EXISTS " in drop_sql else "unknown"
                            dropped_indexes.append(index_name)
                            logger.info(f"  Dropped index: {index_name}")
                        except Exception as e:
                            logger.warning(f"  Could not drop index with SQL '{drop_sql}': {e}")
                    
                    # Skip autovacuum disable for partitioned tables
                    logger.info("  Skipping autovacuum disable on partitioned tables (not supported)")
                    
                    phase4_stats['index_drop_time'] = time.time() - index_drop_start
                    phase4_stats['dropped_indexes_count'] = len(dropped_indexes)
                    logger.info(f"Index drop completed: {len(dropped_indexes)} indexes dropped in {phase4_stats['index_drop_time']:.2f}s")
                    
                    # Step 1: Transfer terms to main term table
                    logger.info("Step 1: Transferring terms to main term table...")
                    term_start = time.time()
                    
                    # Direct INSERT from temp term table to main term table
                    cursor.execute(f"""
                        INSERT INTO {term_table} (term_uuid, term_text, term_type, lang, datatype_id, created_time, dataset)
                        SELECT term_uuid, term_text, term_type, lang, datatype_id, created_time, 'primary'
                        FROM {temp_term_table}
                        ON CONFLICT (term_uuid, dataset) DO NOTHING
                    """)
                    terms_transferred = cursor.rowcount
                    
                    phase4_stats['terms_transferred'] = terms_transferred
                    phase4_stats['term_transfer_time'] = time.time() - term_start
                    
                    logger.info(f"INSERT transferred {terms_transferred:,} terms in {phase4_stats['term_transfer_time']:.2f}s")
                    
                    # Step 2: Transfer quads to main quad table
                    logger.info("Step 2: Transferring quads to main quad table...")
                    quad_start = time.time()
                    
                    # Direct INSERT from temp quad table to main quad table
                    cursor.execute(f"""
                        INSERT INTO {quad_table} (subject_uuid, predicate_uuid, object_uuid, context_uuid, quad_uuid, created_time, dataset)
                        SELECT subject_uuid, predicate_uuid, object_uuid, context_uuid, quad_uuid, created_time, 'primary'
                        FROM {temp_quad_table}
                    """)
                    quads_transferred = cursor.rowcount
                    
                    phase4_stats['quads_transferred'] = quads_transferred
                    phase4_stats['quad_transfer_time'] = time.time() - quad_start
                    
                    logger.info(f"INSERT transferred {quads_transferred:,} quads in {phase4_stats['quad_transfer_time']:.2f}s")
                    
                    # Step 3: Recreate ALL indexes
                    logger.info("Step 3: Recreating ALL indexes for optimal query performance...")
                    index_recreate_start = time.time()
                    
                    # Recreate all indexes using schema's recreate method (non-concurrent within transaction)
                    recreate_index_sql_list = schema.get_recreate_indexes_sql(concurrent=False)
                    recreated_indexes = []
                    
                    for recreate_sql in recreate_index_sql_list:
                        try:
                            cursor.execute(recreate_sql)
                            # Extract index name from SQL for logging
                            index_name = recreate_sql.split("INDEX ")[1].split(" ON ")[0] if " ON " in recreate_sql else "unknown"
                            # Remove CONCURRENTLY keyword if present for cleaner logging
                            index_name = index_name.replace("CONCURRENTLY ", "")
                            recreated_indexes.append(index_name)
                            logger.info(f"  Recreated index: {index_name}")
                        except Exception as e:
                            logger.warning(f"  Could not recreate index with SQL '{recreate_sql}': {e}")
                    
                    # Skip autovacuum re-enable for partitioned tables
                    logger.info("  Skipping autovacuum re-enable on partitioned tables (not supported)")
                    
                    # Step 4: Run ANALYZE to update table statistics for optimal query planning
                    logger.info("  Running ANALYZE to update table statistics for optimal query planning...")
                    analyze_start = time.time()
                    
                    cursor.execute(f"ANALYZE {term_table};")
                    logger.info(f"  Analyzed table: {term_table}")
                    
                    cursor.execute(f"ANALYZE {quad_table};")
                    logger.info(f"  Analyzed table: {quad_table}")
                    
                    analyze_time = time.time() - analyze_start
                    
                    phase4_stats['index_recreate_time'] = time.time() - index_recreate_start
                    phase4_stats['recreated_indexes_count'] = len(recreated_indexes)
                    phase4_stats['analyze_time'] = analyze_time
                    logger.info(f"Index recreation completed: {len(recreated_indexes)} indexes recreated in {phase4_stats['index_recreate_time']:.2f}s")
                    logger.info(f"Table analysis completed in {analyze_time:.2f}s")
                    
                    phase4_stats['total_time'] = time.time() - start_time
                    
                    # Calculate performance metrics
                    if phase4_stats['total_time'] > 0:
                        terms_per_sec = terms_transferred / phase4_stats['term_transfer_time'] if phase4_stats['term_transfer_time'] > 0 else 0
                        quads_per_sec = quads_transferred / phase4_stats['quad_transfer_time'] if phase4_stats['quad_transfer_time'] > 0 else 0
                        overall_rate = quads_transferred / phase4_stats['total_time']
                        
                        phase4_stats.update({
                            'terms_per_sec': terms_per_sec,
                            'quads_per_sec': quads_per_sec,
                            'overall_transfer_rate': overall_rate
                        })
                        
                        logger.info(f"Traditional Transfer Performance: {terms_per_sec:,.0f} terms/sec, {quads_per_sec:,.0f} quads/sec, {overall_rate:,.0f} overall rate")
                        logger.info(f"Index Management: {phase4_stats['dropped_indexes_count']} dropped, {phase4_stats['recreated_indexes_count']} recreated")
                        logger.info(f"Table Analysis: {phase4_stats['analyze_time']:.2f}s - statistics updated for optimal query planning")
                    
                    logger.info(f"Traditional transfer completed successfully: {quads_transferred:,} quads, {terms_transferred:,} terms in {phase4_stats['total_time']:.2f}s")
                    
        except Exception as e:
            phase4_stats['error'] = str(e)
            phase4_stats['total_time'] = time.time() - start_time
            logger.error(f"Traditional transfer failed after {phase4_stats['total_time']:.2f}s: {e}")
            raise
        
        # Run VACUUM ANALYZE outside the main transaction for better statistics
        vacuum_stats = await self._vacuum_analyze_main_tables(term_table, quad_table)
        phase4_stats.update(vacuum_stats)
        
        # Run ANALYZE on parent partitioned tables for optimal SPARQL query planning
        parent_stats = await self._analyze_parent_partitioned_tables(space_id)
        phase4_stats.update(parent_stats)
        
        return phase4_stats

    async def _cleanup_partition_import_session(self, import_session: dict):
        """Clean up temporary tables from partition import session."""
        temp_term_table = import_session['temp_term_table']
        temp_quad_table = import_session['temp_quad_table']
        
        logger.info(f"Cleaning up partition import session {import_session['import_id']}")
        
        async with self.space_impl.get_db_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    cursor.execute(f"DROP TABLE IF EXISTS {temp_term_table}")
                    cursor.execute(f"DROP TABLE IF EXISTS {temp_quad_table}")
                    logger.info(f"Dropped temp tables: {temp_term_table}, {temp_quad_table}")
                except Exception as e:
                    logger.warning(f"Error cleaning up temp tables: {e}")

    async def convert_and_merge_unlogged_data(self, import_session: dict):
        """Convert UNLOGGED temp tables and merge data into main tables with optimal performance."""
        
        import_id = import_session['import_id']
        dataset_value = import_session['dataset_value']
        temp_term_table = import_session['temp_term_table']
        temp_quad_table = import_session['temp_quad_table']
        main_term_table = import_session['main_term_table']
        main_quad_table = import_session['main_quad_table']
        main_tables_partitioned = import_session['main_tables_partitioned']
        
        logger.info(f"Starting UNLOGGED data conversion and merge for import {import_id}")
        
        async with self.space_impl.get_db_connection() as conn:
            with conn.cursor() as cursor:
                if main_tables_partitioned:
                    # Main tables are partitioned - need to add partition key and convert to LOGGED
                    logger.info("Converting UNLOGGED temp tables for partitioned main tables")
                    
                    # Add partition key column to temp tables
                    cursor.execute(f"""
                        ALTER TABLE {temp_term_table} 
                        ADD COLUMN dataset VARCHAR(50) NOT NULL DEFAULT '{dataset_value}'
                    """)
                    cursor.execute(f"""
                        ALTER TABLE {temp_quad_table} 
                        ADD COLUMN dataset VARCHAR(50) NOT NULL DEFAULT '{dataset_value}'
                    """)
                    
                    # Convert to LOGGED for partition attachment
                    logger.info(f"Converting {temp_term_table} from UNLOGGED to LOGGED")
                    cursor.execute(f"ALTER TABLE {temp_term_table} SET LOGGED")
                    
                    logger.info(f"Converting {temp_quad_table} from UNLOGGED to LOGGED")
                    cursor.execute(f"ALTER TABLE {temp_quad_table} SET LOGGED")
                    
                    # Create indexes on temp tables before attaching as partitions
                    await self._create_partition_indexes(cursor, temp_term_table, 'term')
                    await self._create_partition_indexes(cursor, temp_quad_table, 'quad')
                    
                    # Add dataset CHECK constraints with NOT VALID to skip validation scan during ATTACH PARTITION
                    cursor.execute(f"""
                        ALTER TABLE {temp_quad_table} 
                        ADD CONSTRAINT {temp_quad_table}_dataset_check 
                        CHECK (dataset = '{dataset_value}') NOT VALID
                    """)
                    
                    cursor.execute(f"""
                        ALTER TABLE {temp_term_table} 
                        ADD CONSTRAINT {temp_term_table}_dataset_check 
                        CHECK (dataset = '{dataset_value}') NOT VALID
                    """)
                    
                    # Step 4: Attach temp tables as partitions
                    logger.info(f"Attaching {temp_term_table} as partition to {main_term_table}")
                    cursor.execute(f"""
                        ALTER TABLE {main_term_table} 
                        ATTACH PARTITION {temp_term_table} 
                        FOR VALUES IN ('{dataset_value}')
                    """)
                    
                    logger.info(f"Attaching {temp_quad_table} as partition to {main_quad_table}")
                    cursor.execute(f"""
                        ALTER TABLE {main_quad_table} 
                        ATTACH PARTITION {temp_quad_table} 
                        FOR VALUES IN ('{dataset_value}')
                    """)
                    
                    merge_method = "partition_attachment"
                    
                else:
                    # Main tables are UNLOGGED - direct INSERT from temp tables
                    logger.info("Merging UNLOGGED temp tables into UNLOGGED main tables")
                    
                    # Direct INSERT for maximum performance (both tables are UNLOGGED)
                    cursor.execute(f"""
                        INSERT INTO {main_term_table} 
                        SELECT * FROM {temp_term_table}
                    """)
                    term_rows = cursor.rowcount
                    
                    cursor.execute(f"""
                        INSERT INTO {main_quad_table} 
                        SELECT * FROM {temp_quad_table}
                    """)
                    quad_rows = cursor.rowcount
                    
                    # Drop temp tables after successful merge
                    cursor.execute(f"DROP TABLE {temp_term_table}")
                    cursor.execute(f"DROP TABLE {temp_quad_table}")
                    
                    merge_method = "direct_insert"
                    logger.info(f"Merged {term_rows} terms and {quad_rows} quads via direct INSERT")
                
                logger.info(f"UNLOGGED data conversion and merge completed for import {import_id}")
        
        return {
            'status': 'merged',
            'merge_method': merge_method,
            'dataset': dataset_value,
            'import_id': import_id
        }


    
    async def _create_temp_import_table(self, table_name: str):
        """Legacy method - replaced by setup_partition_import_session."""
        logger.warning("_create_temp_import_table is deprecated - use setup_partition_import_session instead")
        
        create_sql = sql.SQL("""
            CREATE UNLOGGED TABLE {table_name} (
                -- Raw string values from RDF parsing (Phase 2)
                subject_uri TEXT NOT NULL,
                predicate_uri TEXT NOT NULL,
                object_value TEXT NOT NULL,
                object_datatype TEXT,
                object_language TEXT,
                is_literal BOOLEAN NOT NULL DEFAULT FALSE,
                graph_uri TEXT NOT NULL,
                import_batch_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                
                -- Resolved term UUIDs (Phase 3 - populated during term processing)
                subject_uuid UUID,
                predicate_uuid UUID, 
                object_uuid UUID,
                graph_uuid UUID,
                
                -- Processing status tracking
                processing_status TEXT DEFAULT 'pending',  -- 'pending', 'processed', 'error'
                processing_error TEXT,
                
                -- Partition key for zero-copy imports
                dataset VARCHAR(50) NOT NULL DEFAULT 'primary'
            )
        """).format(table_name=sql.Identifier(table_name))
        
        async with self.space_impl.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(create_sql)
                logger.info(f"Created UNLOGGED temp table: {table_name}")



    async def convert_unlogged_to_partition(self, temp_table: str, dataset_value: str, main_table: str) -> Dict[str, Any]:
        """Convert UNLOGGED temp table to LOGGED partition and attach to main table."""
        
        logger.info(f"Converting UNLOGGED table {temp_table} to partition with dataset='{dataset_value}'")
        
        async with self.space_impl.get_db_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    # Step 1: Add partition key column
                    cursor.execute(f"ALTER TABLE {temp_table} ADD COLUMN dataset VARCHAR(50) DEFAULT %s", (dataset_value,))
                    
                    # Step 2: Update all rows with partition key value
                    cursor.execute(f"UPDATE {temp_table} SET dataset = %s", (dataset_value,))
                    
                    # Step 3: Convert UNLOGGED to LOGGED
                    cursor.execute(f"ALTER TABLE {temp_table} SET LOGGED")
                    
                    # Step 4: Attach as partition
                    cursor.execute(f"""
                        ALTER TABLE {main_table} 
                        ATTACH PARTITION {temp_table} 
                        FOR VALUES IN ('{dataset_value}')
                    """)
                    
                    logger.info(f"Successfully attached {temp_table} as partition to {main_table}")
                    
                    return {
                        'status': 'success',
                        'method': 'partition_attachment',
                        'dataset': dataset_value
                    }
                    
                except Exception as e:
                    logger.error(f"Failed to convert {temp_table} to partition: {e}")
                    # Clean up on failure
                    try:
                        cursor.execute(f"DROP TABLE IF EXISTS {temp_table}")
                    except:
                        pass
                    raise
            
    async def _convert_ntriples_to_csv(
        self, 
        ntriples_file: str, 
        graph_uri: str,
        batch_size: int,
        progress_callback: Optional[callable],
        stats: Dict[str, Any]
    ) -> str:
        """
        Parse N-Triples file using oxigraph for high-performance parsing and convert to CSV format.
        Uses streaming approach for memory efficiency with large files.
        Generates deterministic UUIDs for all terms during CSV creation.
        
        Returns path to temporary CSV file.
        """
        from pyoxigraph import parse
        from .postgresql_space_terms import PostgreSQLSpaceTerms
        from functools import lru_cache
        logger.info("Using oxigraph for high-performance N-Triples parsing with cached UUID generation")
        
        # Create LRU cache for UUID generation to avoid duplicate computations
        @lru_cache(maxsize=100000)
        def cached_generate_uuid(term_text: str, term_type: str, lang: str = None) -> str:
            """Generate UUID with LRU caching for performance."""
            return str(PostgreSQLSpaceTerms.generate_term_uuid(term_text, term_type, lang=lang))
        
        # Create temporary CSV file
        csv_fd, csv_file_path = tempfile.mkstemp(suffix='.csv', prefix='vitalgraph_import_')
        
        try:
            with os.fdopen(csv_fd, 'w', newline='', encoding='utf-8') as csv_file:
                csv_writer = csv.writer(csv_file, quoting=csv.QUOTE_NONNUMERIC)
                
                logger.info(f"Streaming oxigraph parse of N-Triples file: {ntriples_file}")
                
                batch_count = 0
                with open(ntriples_file, 'rb') as nt_file:
                    # Use oxigraph's streaming parser
                    for triple in parse(nt_file, "application/n-triples"):
                        # Extract subject, predicate, object
                        subject_uri = str(triple.subject)
                        predicate_uri = str(triple.predicate)
                        
                        # Handle different object types using oxigraph's type system
                        obj = triple.object
                        
                        # Check if it's a literal
                        if str(type(obj).__name__) == 'Literal':
                            object_value = str(obj)
                            # Extract datatype and language if present
                            if hasattr(obj, 'datatype') and obj.datatype:
                                object_datatype = str(obj.datatype)
                                object_language = None
                            elif hasattr(obj, 'language') and obj.language:
                                object_datatype = None
                                object_language = str(obj.language)
                            else:
                                object_datatype = None
                                object_language = None
                            is_literal = True
                        else:
                            # URI or blank node
                            object_value = str(obj)
                            object_datatype = None
                            object_language = None
                            is_literal = False
                        
                        # Generate deterministic UUIDs for all terms using cache
                        subject_uuid = cached_generate_uuid(subject_uri, 'U')
                        predicate_uuid = cached_generate_uuid(predicate_uri, 'U')
                        object_uuid = cached_generate_uuid(
                            object_value, 
                            'L' if is_literal else 'U',
                            lang=object_language
                        )
                        graph_uuid = cached_generate_uuid(graph_uri, 'U')
                        
                        # Create CSV row with UUIDs and processed status
                        import_batch_id = f"batch_{batch_count // batch_size}"
                        triple_data = (
                            subject_uri, predicate_uri, object_value, 
                            object_datatype or '', object_language or '', 
                            is_literal, graph_uri, import_batch_id,
                            subject_uuid, predicate_uuid, object_uuid, graph_uuid,
                            'processed'  # processing_status
                        )
                        
                        csv_writer.writerow(triple_data)
                        stats['total_triples'] += 1
                        batch_count += 1
                        
                        # Progress callback
                        if progress_callback and batch_count % batch_size == 0:
                            progress_callback(stats['total_triples'], batch_count)
                            
            logger.info(f"Converted {stats['total_triples']} triples to CSV: {csv_file_path}")
            return csv_file_path
            
        except Exception as e:
            # Clean up CSV file on error
            if os.path.exists(csv_file_path):
                os.unlink(csv_file_path)
            raise
    
            
            
    async def _bulk_copy_csv_to_table(self, csv_file_path: str, table_name: str, stats: Dict[str, Any]):
        """Use PostgreSQL COPY to bulk load CSV data into temp table."""
        
        async with self.space_impl.get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Disable synchronous_commit for better performance
                cursor.execute("SET LOCAL synchronous_commit = OFF")
                
                # Debug: Check if table exists and get structure
                cursor.execute("""
                    SELECT column_name, data_type 
                    FROM information_schema.columns 
                    WHERE table_name = %s 
                    ORDER BY ordinal_position
                """, (table_name,))
                columns = cursor.fetchall()
                logger.info(f"Table {table_name} columns: {columns}")
                
                # Use COPY command with proper CSV format including UUID columns
                copy_sql = f"""
                    COPY {table_name} (
                        subject_uri, predicate_uri, object_value, object_datatype, 
                        object_language, is_literal, graph_uri, import_batch_id,
                        subject_uuid, predicate_uuid, object_uuid, graph_uuid, processing_status
                    )
                    FROM STDIN WITH (FORMAT CSV, DELIMITER ',', QUOTE '"', ESCAPE '"', NULL '')
                """
                
                # Read a few lines for debugging
                with open(csv_file_path, 'r', encoding='utf-8') as debug_file:
                    sample_lines = [debug_file.readline().strip() for _ in range(3)]
                    logger.info(f"Sample CSV lines: {sample_lines}")
                
                # Perform COPY operation using fastest method - cursor.copy() with chunked streaming
                with cursor.copy(copy_sql) as copy:
                    with open(csv_file_path, 'rb') as csv_file:  # Binary mode for fastest I/O
                        while True:
                            data = csv_file.read(65536)  # 64KB chunks for optimal performance
                            if not data:
                                break
                            copy.write(data)
                        
                # Get row count
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                row_count = cursor.fetchone()
                stats['processed_triples'] = row_count[0]
                logger.info(f"Loaded {row_count[0]} rows into temp table {table_name}")
            
    async def get_temp_table_stats(self, table_name: str) -> Dict[str, Any]:
        """Get statistics about the temporary import table."""
        
        async with self.space_impl.get_db_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    # First check if table exists
                    cursor.execute("""
                        SELECT COUNT(*) FROM information_schema.tables 
                        WHERE table_name = %s
                    """, (table_name,))
                    
                    if cursor.fetchone()[0] == 0:
                        logger.warning(f"Table {table_name} does not exist")
                        return self._empty_stats()
                    
                    # Get basic row count first
                    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                    total_rows = cursor.fetchone()[0]
                    
                    if total_rows == 0:
                        logger.warning(f"Table {table_name} is empty")
                        return self._empty_stats()
                    
                    # Get detailed statistics
                    stats_sql = f"""
                        SELECT 
                            COUNT(*) as total_rows,
                            COUNT(DISTINCT subject_uri) as unique_subjects,
                            COUNT(DISTINCT predicate_uri) as unique_predicates,
                            COUNT(DISTINCT object_value) as unique_objects,
                            COUNT(DISTINCT graph_uri) as unique_graphs,
                            SUM(CASE WHEN is_literal THEN 1 ELSE 0 END) as literal_count,
                            SUM(CASE WHEN NOT is_literal THEN 1 ELSE 0 END) as uri_count
                        FROM {table_name}
                    """
                    
                    cursor.execute(stats_sql)
                    result = cursor.fetchone()
                    
                    if result:
                        return {
                            'total_rows': result[0] or 0,
                            'unique_subjects': result[1] or 0,
                            'unique_predicates': result[2] or 0,
                            'unique_objects': result[3] or 0,
                            'unique_graphs': result[4] or 0,
                            'literal_count': result[5] or 0,
                            'uri_count': result[6] or 0
                        }
                    else:
                        return self._empty_stats()
                        
                except Exception as e:
                    logger.error(f"Failed to get temp table stats: {e}")
                    return self._empty_stats()
    
    def _empty_stats(self) -> Dict[str, Any]:
        """Return empty statistics dictionary."""
        return {
            'total_rows': 0,
            'unique_subjects': 0,
            'unique_predicates': 0,
            'unique_objects': 0,
            'unique_graphs': 0,
            'literal_count': 0,
            'uri_count': 0
        }
            
    async def _cleanup_temp_table(self, table_name: str):
        """Drop the temporary import table."""
        try:
            drop_sql = sql.SQL("DROP TABLE IF EXISTS {table_name}").format(
                table_name=sql.Identifier(table_name)
            )
            async with self.space_impl.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(drop_sql)
                    logger.info(f"Dropped temp table: {table_name}")
        except Exception as e:
            logger.warning(f"Failed to drop temp table {table_name}: {e}")
            
    async def process_terms_phase3(self, temp_table_name: str, space_id: str, stats: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process terms using deterministic UUID generation - no JOINs needed!
        
        This method uses PostgreSQLSpaceTerms.generate_term_uuid() for deterministic
        UUIDs based on term content, eliminating the need for complex JOINs.
        """
        import time
        import uuid
        from .postgresql_space_terms import PostgreSQLSpaceTerms
        
        logger = logging.getLogger(__name__)
        start_time = time.time()
        
        async with self.space_impl.get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Get total rows in temp table
                cursor.execute(f"SELECT COUNT(*) FROM {temp_table_name}")
                total_rows = cursor.fetchone()[0]
                
                logger.info(f"Processing {total_rows:,} triples using deterministic UUID generation...")
                
                # Step 1: Create terms table with UUIDs from CSV data
                logger.info("Step 1: Create terms table with pre-generated UUIDs...")
                step1_start = time.time()
                
                terms_table = f"terms_{uuid.uuid4().hex[:8]}"
                cursor.execute(f"""
                    CREATE UNLOGGED TABLE {terms_table} AS
                    SELECT DISTINCT term_text, term_type, term_uuid FROM (
                        SELECT subject_uri as term_text, 'U' as term_type, subject_uuid as term_uuid FROM {temp_table_name}
                        UNION ALL
                        SELECT predicate_uri as term_text, 'U' as term_type, predicate_uuid as term_uuid FROM {temp_table_name}
                        UNION ALL
                        SELECT object_value as term_text, CASE WHEN is_literal THEN 'L' ELSE 'U' END as term_type, object_uuid as term_uuid FROM {temp_table_name}
                        UNION ALL
                        SELECT graph_uri as term_text, 'U' as term_type, graph_uuid as term_uuid FROM {temp_table_name}
                    ) t
                """)
                
                cursor.execute(f"SELECT COUNT(*) FROM {terms_table}")
                all_terms_count = cursor.fetchone()[0]
                step1_duration = time.time() - step1_start
                logger.info(f"Step 1 completed: {all_terms_count:,} distinct terms in {step1_duration:.2f}s")
                
                # Temp table already has UUIDs - no additional processing needed
                cursor.execute(f"SELECT COUNT(*) FROM {temp_table_name}")
                rows_processed = cursor.fetchone()[0]
                
                rows_updated = rows_processed
                new_terms_count = all_terms_count  # All terms from step 1
                
                total_duration = time.time() - start_time
                stats.update({
                    'total_duration': total_duration,
                    'processing_time': total_duration,
                    'new_terms_count': new_terms_count,
                    'rows_updated': rows_updated,
                    'step1_duration': step1_duration,
                    'unique_terms_processed': new_terms_count,
                    'existing_terms_reused': 0,  # All terms are pre-generated in CSV
                    'new_terms_created': new_terms_count
                })
                
                logger.info(f"1-step UUID workflow completed: {rows_updated:,} rows, {new_terms_count:,} terms in {total_duration:.2f}s")
                logger.info(f"Performance: {rows_updated / total_duration:,.0f} rows/sec")
                
                return stats

    


    async def transfer_to_main_tables_phase4(self, temp_table_name: str, space_id: str, graph_uri: str, import_stats: Dict[str, Any]) -> Dict[str, Any]:
        """
        Phase 4: Transfer processed data from temp table to main transactional tables.
        
        This method performs optimized bulk transfer from the UNLOGGED temp table
        to the main WAL-enabled quad and term tables using PostgreSQL's most
        efficient bulk operations while maintaining ACID compliance.
        
        Complete optimization process:
        - Step 0: Drops ALL indexes (11 total) for maximum bulk transfer performance
        - Step 1: Transfers unique terms using optimized INSERT SELECT with conflict resolution
        - Step 2: Transfers quads using optimized INSERT SELECT operations
        - Step 3: Recreates ALL indexes with CONCURRENTLY for production safety
        - Step 4: Runs ANALYZE to update table statistics for optimal query planning
        - Disables/re-enables autovacuum during bulk operations
        
        Args:
            temp_table_name: Name of temporary table with processed data
            space_id: Target space ID
            graph_uri: Target graph URI
            import_stats: Statistics dictionary to update
            
        Returns:
            Dict with transfer statistics and performance metrics including:
            - dropped_indexes_count: Number of indexes dropped
            - recreated_indexes_count: Number of indexes recreated
            - analyze_time: Time spent updating table statistics
            - terms_per_sec, quads_per_sec: Transfer performance metrics
        """
        start_time = time.time()
        logger.info(f"Starting Phase 4: Transfer to main tables for space '{space_id}'")
        
        # Get table names for the space
        table_names = self.space_impl._get_table_names(space_id)
        quad_table = table_names['rdf_quad']
        term_table = table_names['term']
        
        phase4_stats = {
            'phase': 'transfer_to_main_tables',
            'start_time': start_time,
            'terms_transferred': 0,
            'quads_transferred': 0,
            'term_transfer_time': 0,
            'quad_transfer_time': 0,
            'index_drop_time': 0,
            'index_recreate_time': 0,
            'total_time': 0
        }
        
        try:
            async with self.space_impl.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Verify temp table has processed data
                    cursor.execute(f"SELECT COUNT(*) FROM {temp_table_name} WHERE processing_status = 'processed'")
                    processed_count = cursor.fetchone()[0]
                    
                    logger.info(f"Found {processed_count:,} processed rows ready for transfer")
                    
                    # Step 0: Drop ALL indexes for maximum bulk transfer performance
                    logger.info("Step 0: Dropping ALL indexes for maximum bulk transfer performance...")
                    index_drop_start = time.time()
                    
                    # Get schema for index management
                    from .postgresql_space_schema import PostgreSQLSpaceSchema
                    schema = PostgreSQLSpaceSchema(self.space_impl.global_prefix, space_id)
                    
                    # Drop all indexes using schema's drop method
                    drop_index_sql_list = schema.get_drop_indexes_sql()
                    dropped_indexes = []
                    
                    for drop_sql in drop_index_sql_list:
                        try:
                            cursor.execute(drop_sql)
                            # Extract index name from SQL for logging
                            index_name = drop_sql.split("EXISTS ")[1].split(";")[0] if "EXISTS " in drop_sql else "unknown"
                            dropped_indexes.append(index_name)
                            logger.info(f"  Dropped index: {index_name}")
                        except Exception as e:
                            logger.warning(f"  Could not drop index with SQL '{drop_sql}': {e}")
                    
                    # Disable autovacuum on target tables during bulk transfer
                    # For partitioned tables, we need to disable on all partitions
                    try:
                        cursor.execute(f"ALTER TABLE {term_table} SET (autovacuum_enabled = off);")
                        cursor.execute(f"ALTER TABLE {quad_table} SET (autovacuum_enabled = off);")
                        logger.info("  Disabled autovacuum on target tables")
                    except Exception as e:
                        if "partitioned table" in str(e):
                            logger.info("  Skipping autovacuum disable on partitioned tables (not supported)")
                        else:
                            logger.warning(f"  Could not disable autovacuum: {e}")
                    
                    phase4_stats['index_drop_time'] = time.time() - index_drop_start
                    phase4_stats['dropped_indexes_count'] = len(dropped_indexes)
                    logger.info(f"Index drop completed: {len(dropped_indexes)} indexes dropped in {phase4_stats['index_drop_time']:.2f}s")
                    
                    # Step 1: Transfer unique terms to main term table using INSERT SELECT
                    logger.info("Step 1: Transferring unique terms to main term table...")
                    term_start = time.time()
                    
                    # Create a temporary view with unique terms for transfer
                    terms_view_name = f"terms_view_{temp_table_name}"
                    cursor.execute(f"""
                        CREATE TEMP VIEW {terms_view_name} AS
                        SELECT DISTINCT 
                            term_uuid,
                            term_text,
                            term_type,
                            NULL::VARCHAR(20) as lang,
                            NULL::BIGINT as datatype_id,
                            CURRENT_TIMESTAMP as created_time
                        FROM (
                            SELECT subject_uuid as term_uuid, subject_uri as term_text, 'U' as term_type FROM {temp_table_name} WHERE processing_status = 'processed'
                            UNION ALL
                            SELECT predicate_uuid as term_uuid, predicate_uri as term_text, 'U' as term_type FROM {temp_table_name} WHERE processing_status = 'processed'
                            UNION ALL
                            SELECT object_uuid as term_uuid, object_value as term_text, CASE WHEN is_literal THEN 'L' ELSE 'U' END as term_type FROM {temp_table_name} WHERE processing_status = 'processed'
                            UNION ALL
                            SELECT graph_uuid as term_uuid, graph_uri as term_text, 'U' as term_type FROM {temp_table_name} WHERE processing_status = 'processed'
                        ) unique_terms
                    """)
                    
                    # Use INSERT SELECT with ON CONFLICT for term transfer (handles existing terms)
                    insert_terms_sql = f"""
                        INSERT INTO {term_table} (term_uuid, term_text, term_type, lang, datatype_id, created_time)
                        SELECT * FROM {terms_view_name}
                        ON CONFLICT (term_uuid) DO NOTHING
                    """
                    
                    # Execute INSERT SELECT operation with conflict handling
                    term_start = time.time()
                    cursor.execute(insert_terms_sql)
                    terms_transferred = cursor.rowcount
                    
                    # Clean up temp view
                    cursor.execute(f"DROP VIEW {terms_view_name}")
                    
                    phase4_stats['terms_transferred'] = terms_transferred
                    phase4_stats['term_transfer_time'] = time.time() - term_start
                    
                    logger.info(f"INSERT SELECT transferred {terms_transferred:,} unique terms in {phase4_stats['term_transfer_time']:.2f}s")
                    
                    # Step 2: Transfer quads to main quad table using PostgreSQL COPY
                    logger.info("Step 2: Transferring quads to main quad table using COPY...")
                    quad_start = time.time()
                    
                    # Create a temporary view with processed quads for COPY operation
                    quads_view_name = f"quads_view_{temp_table_name}"
                    cursor.execute(f"""
                        CREATE TEMP VIEW {quads_view_name} AS
                        SELECT 
                            subject_uuid,
                            predicate_uuid,
                            object_uuid,
                            graph_uuid as context_uuid,
                            CURRENT_TIMESTAMP as created_time
                        FROM {temp_table_name}
                        WHERE processing_status = 'processed'
                        AND subject_uuid IS NOT NULL
                        AND predicate_uuid IS NOT NULL
                        AND object_uuid IS NOT NULL
                        AND graph_uuid IS NOT NULL
                    """)
                    
                    # Use optimized bulk INSERT for quad transfer
                    insert_quads_sql = f"""
                        INSERT INTO {quad_table} (subject_uuid, predicate_uuid, object_uuid, context_uuid, created_time)
                        SELECT subject_uuid, predicate_uuid, object_uuid, context_uuid, created_time 
                        FROM {quads_view_name}
                    """
                    
                    cursor.execute(insert_quads_sql)
                    quads_transferred = cursor.rowcount
                    
                    # Clean up temp view
                    cursor.execute(f"DROP VIEW {quads_view_name}")
                    
                    phase4_stats['quads_transferred'] = quads_transferred
                    phase4_stats['quad_transfer_time'] = time.time() - quad_start
                    
                    logger.info(f"INSERT SELECT transferred {quads_transferred:,} quads in {phase4_stats['quad_transfer_time']:.2f}s")
                    
                    # Step 3: Recreate ALL indexes and re-enable autovacuum
                    logger.info("Step 3: Recreating ALL indexes for optimal query performance...")
                    index_recreate_start = time.time()
                    
                    # Recreate all indexes using schema's recreate method with CONCURRENTLY for production safety
                    recreate_index_sql_list = schema.get_recreate_indexes_sql(concurrent=True)
                    recreated_indexes = []
                    
                    for recreate_sql in recreate_index_sql_list:
                        try:
                            cursor.execute(recreate_sql)
                            # Extract index name from SQL for logging
                            index_name = recreate_sql.split("INDEX ")[1].split(" ON ")[0] if " ON " in recreate_sql else "unknown"
                            # Remove CONCURRENTLY keyword if present for cleaner logging
                            index_name = index_name.replace("CONCURRENTLY ", "")
                            recreated_indexes.append(index_name)
                            logger.info(f"  Recreated index: {index_name}")
                        except Exception as e:
                            logger.warning(f"  Could not recreate index with SQL '{recreate_sql}': {e}")
                    
                    # Re-enable autovacuum on target tables
                    try:
                        cursor.execute(f"ALTER TABLE {term_table} RESET (autovacuum_enabled);")
                        cursor.execute(f"ALTER TABLE {quad_table} RESET (autovacuum_enabled);")
                        logger.info("  Re-enabled autovacuum on target tables")
                    except Exception as e:
                        if "partitioned table" in str(e):
                            logger.info("  Skipping autovacuum re-enable on partitioned tables (not supported)")
                        else:
                            logger.warning(f"  Could not re-enable autovacuum: {e}")
                    
                    # Step 4: Run ANALYZE to update table statistics for optimal query planning
                    logger.info("  Running ANALYZE to update table statistics for optimal query planning...")
                    analyze_start = time.time()
                    
                    cursor.execute(f"ANALYZE {term_table};")
                    logger.info(f"  Analyzed table: {term_table}")
                    
                    cursor.execute(f"ANALYZE {quad_table};")
                    logger.info(f"  Analyzed table: {quad_table}")
                    
                    analyze_time = time.time() - analyze_start
                    
                    phase4_stats['index_recreate_time'] = time.time() - index_recreate_start
                    phase4_stats['recreated_indexes_count'] = len(recreated_indexes)
                    phase4_stats['analyze_time'] = analyze_time
                    logger.info(f"Index recreation completed: {len(recreated_indexes)} indexes recreated in {phase4_stats['index_recreate_time']:.2f}s")
                    logger.info(f"Table analysis completed in {analyze_time:.2f}s")
                    
                    # Verify transfer success
                    if quads_transferred != processed_count:
                        logger.warning(f"Transfer mismatch: {processed_count:,} processed vs {quads_transferred:,} transferred")
                    
                    phase4_stats['total_time'] = time.time() - start_time
                    
                    # Calculate performance metrics
                    if phase4_stats['total_time'] > 0:
                        terms_per_sec = terms_transferred / phase4_stats['term_transfer_time'] if phase4_stats['term_transfer_time'] > 0 else 0
                        quads_per_sec = quads_transferred / phase4_stats['quad_transfer_time'] if phase4_stats['quad_transfer_time'] > 0 else 0
                        overall_rate = quads_transferred / phase4_stats['total_time']
                        
                        phase4_stats.update({
                            'terms_per_sec': terms_per_sec,
                            'quads_per_sec': quads_per_sec,
                            'overall_transfer_rate': overall_rate
                        })
                        
                        logger.info(f"Phase 4 Performance: {terms_per_sec:,.0f} terms/sec, {quads_per_sec:,.0f} quads/sec, {overall_rate:,.0f} overall rate")
                        logger.info(f"Index Management: {phase4_stats['dropped_indexes_count']} dropped, {phase4_stats['recreated_indexes_count']} recreated")
                        logger.info(f"Table Analysis: {phase4_stats['analyze_time']:.2f}s - statistics updated for optimal query planning")
                    
                    # Update import stats
                    import_stats.update({
                        'phase4_stats': phase4_stats,
                        'main_table_transfer_completed': True,
                        'final_quad_count': quads_transferred,
                        'final_term_count': terms_transferred
                    })
                    
                    logger.info(f"Phase 4 completed successfully: {quads_transferred:,} quads, {terms_transferred:,} terms in {phase4_stats['total_time']:.2f}s")
                    return phase4_stats
                    
        except Exception as e:
            phase4_stats['error'] = str(e)
            phase4_stats['total_time'] = time.time() - start_time
            logger.error(f"Phase 4 failed after {phase4_stats['total_time']:.2f}s: {e}")
            raise
    
    async def _copy_from_view_to_table(self, cursor, view_name: str, target_table: str, 
                                      columns: List[str], conflict_resolution: str = None) -> int:
        """
        Transfer data directly from a view/table to target table using optimized INSERT.
        
        For table-to-table transfers, direct INSERT with SELECT is more efficient
        than COPY with intermediate files.
        
        Args:
            cursor: Database cursor
            view_name: Source view/table name
            target_table: Target table name
            columns: List of column names to copy
            conflict_resolution: Optional conflict resolution (e.g., 'ON CONFLICT (id) DO NOTHING')
            
        Returns:
            Number of rows transferred
        """
        columns_str = ', '.join(columns)
        
        if conflict_resolution:
            # Direct INSERT with conflict resolution
            insert_sql = f"""
                INSERT INTO {target_table} ({columns_str})
                SELECT {columns_str} FROM {view_name}
                {conflict_resolution}
            """
        else:
            # Direct INSERT without conflict resolution
            insert_sql = f"""
                INSERT INTO {target_table} ({columns_str})
                SELECT {columns_str} FROM {view_name}
            """
        
        cursor.execute(insert_sql)
        return cursor.rowcount
    
    async def cleanup_import_session(self, import_stats: Dict[str, Any]):
        """Clean up resources from an import session."""
        temp_table_name = import_stats.get('temp_table_name')
        if temp_table_name:
            await self._cleanup_temp_table(temp_table_name)
