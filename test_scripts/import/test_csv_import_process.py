#!/usr/bin/env python3
"""
Self-Contained CSV Import Process Script
=======================================

This script parses N-Triples files and converts them to CSV format for PostgreSQL import.
It is completely self-contained and does not depend on other VitalGraph code.

Features:
- Parse N-Triples files using pyoxigraph
- Generate deterministic UUIDs for RDF terms
- Convert to CSV format suitable for PostgreSQL COPY operations
- Optional PostgreSQL database import functionality
- Progress monitoring and performance metrics

Usage:
    python test_csv_import_process.py
"""

import asyncio
import csv
import hashlib
import logging
import os
import sys
import tempfile
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Dict, Any, Optional, Callable, Set

import psycopg
from pyoxigraph import parse


# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
VITALGRAPH_NAMESPACE = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')
DEFAULT_GRAPH_URI = "http://vital.ai/test/csv_import_graph"
DEFAULT_BATCH_SIZE = 100000
TABLE_IDENTIFIER = "csv_import_001"  # Change this between runs if needed
BLOCK_SIZE = 1024 * 1024  # 1MB blocks for optimal COPY performance


class TermUUIDGenerator:
    """Generate deterministic UUIDs for RDF terms."""
    
    @staticmethod
    @lru_cache(maxsize=100000)
    def generate_term_uuid(term_text: str, term_type: str, lang: Optional[str] = None, datatype: Optional[str] = None) -> str:
        """
        Generate a deterministic UUID for an RDF term based on its components.
        
        Args:
            term_text: The term's text value
            term_type: The term type ('U' for URI, 'L' for literal, 'B' for blank node)
            lang: Language tag for literals (optional)
            datatype: Datatype URI for typed literals (optional)
            
        Returns:
            str: Deterministic UUID for the term
        """
        # Create a consistent string representation of the term
        components = [term_text, term_type]
        
        if lang is not None:
            components.append(f"lang:{lang}")
        
        if datatype is not None:
            components.append(f"datatype:{datatype}")
        
        # Join components with a separator that won't appear in normal term text
        term_string = "\x00".join(components)
        
        # Generate UUID v5 using the namespace and term string
        return str(uuid.uuid5(VITALGRAPH_NAMESPACE, term_string))


class NTriplesCSVConverter:
    """Convert N-Triples files to CSV format for PostgreSQL import."""
    
    def __init__(self):
        self.uuid_generator = TermUUIDGenerator()
        self.stats = {
            'total_triples': 0,
            'processing_time': 0,
            'file_size_mb': 0,
            'unique_terms': 0,
            'terms_processing_time': 0
        }
    
    def convert_ntriples_to_csv(
        self, 
        ntriples_file: str, 
        output_csv: Optional[str] = None,
        graph_uri: str = DEFAULT_GRAPH_URI,
        table_identifier: str = 'primary',
        batch_size: int = DEFAULT_BATCH_SIZE,
        progress_callback: Optional[Callable] = None
    ) -> str:
        """
        Parse N-Triples file and convert to CSV format for PostgreSQL import.
        
        Args:
            ntriples_file: Path to N-Triples file
            output_csv: Output CSV file path (optional, creates temp file if None)
            graph_uri: Graph URI for context
            table_identifier: Dataset identifier to use in generated CSVs
            batch_size: Batch size for progress reporting
            progress_callback: Optional callback for progress updates
            
        Returns:
            str: Path to generated CSV file
        """
        # pyoxigraph imported at module level
        
        logger.info(f"Converting N-Triples file to CSV: {ntriples_file}")
        
        # Calculate file size
        file_path = Path(ntriples_file)
        if not file_path.exists():
            raise FileNotFoundError(f"N-Triples file not found: {ntriples_file}")
        
        self.stats['file_size_mb'] = file_path.stat().st_size / 1024 / 1024
        logger.info(f"File size: {self.stats['file_size_mb']:.1f} MB")
        
        # Create output CSV file
        if output_csv is None:
            csv_fd, csv_file_path = tempfile.mkstemp(suffix='.csv', prefix='vitalgraph_import_')
            csv_file = os.fdopen(csv_fd, 'w', newline='', encoding='utf-8')
        else:
            csv_file_path = output_csv
            csv_file = open(csv_file_path, 'w', newline='', encoding='utf-8')
        
        start_time = time.time()
        
        try:
            
            with csv_file:
                csv_writer = csv.writer(csv_file, quoting=csv.QUOTE_NONNUMERIC)
                
                # Write CSV header
                csv_writer.writerow([
                    'subject_text', 'predicate_text', 'object_text', 
                    'object_datatype', 'object_language', 'is_literal', 
                    'graph_uri', 'import_batch_id',
                    'subject_uuid', 'predicate_uuid', 'object_uuid', 'context_uuid',
                    'processing_status', 'dataset'
                ])
                
                logger.info("Starting N-Triples parsing with oxigraph...")
                
                batch_count = 0
                
                with open(ntriples_file, 'rb') as nt_file:
                    for triple in parse(nt_file, "application/n-triples"):
                        if batch_count == 0:
                            logger.info("First triple parsed successfully")
                        elif batch_count % 100000 == 0:
                            logger.info(f"Parsed {batch_count:,} triples so far...")
                        
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
                                object_language = ''
                            elif hasattr(obj, 'language') and obj.language:
                                object_datatype = ''
                                object_language = str(obj.language)
                            else:
                                object_datatype = ''
                                object_language = ''
                            is_literal = True
                            object_term_type = 'L'
                        else:
                            # URI or blank node
                            object_value = str(obj)
                            object_datatype = ''
                            object_language = ''
                            is_literal = False
                            object_term_type = 'U' if not str(obj).startswith('_:') else 'B'
                        
                        # Generate deterministic UUIDs for all terms
                        subject_uuid = self.uuid_generator.generate_term_uuid(subject_uri, 'U')
                        predicate_uuid = self.uuid_generator.generate_term_uuid(predicate_uri, 'U')
                        object_uuid = self.uuid_generator.generate_term_uuid(
                            object_value, 
                            object_term_type,
                            lang=object_language if object_language else None,
                            datatype=object_datatype if object_datatype else None
                        )
                        context_uuid = self.uuid_generator.generate_term_uuid(graph_uri, 'U')
                        
                        # Create CSV row
                        import_batch_id = f"batch_{batch_count // batch_size}"
                        dataset_value = f"import_{int(start_time)}"
                        
                        triple_data = (
                            subject_uri, predicate_uri, object_value, 
                            object_datatype, object_language, is_literal, 
                            graph_uri, import_batch_id,
                            subject_uuid, predicate_uuid, object_uuid, context_uuid,
                            'processed', dataset_value
                        )
                        
                        csv_writer.writerow(triple_data)
                        self.stats['total_triples'] += 1
                        batch_count += 1
                        
                        # Progress callback
                        if progress_callback and batch_count % 100000 == 0:
                            elapsed = time.time() - start_time
                            rate = batch_count / elapsed if elapsed > 0 else 0
                            progress_callback(batch_count, rate)
                
                # Explicitly flush and sync the file
                csv_file.flush()
                if hasattr(csv_file, 'fileno'):
                    os.fsync(csv_file.fileno())
            
            self.stats['processing_time'] = time.time() - start_time
            
            logger.info(f"Conversion completed successfully!")
            logger.info(f"Total triples: {self.stats['total_triples']:,}")
            logger.info(f"Processing time: {self.stats['processing_time']:.2f}s")
            logger.info(f"Output CSV: {csv_file_path}")
            
            # Generate terms CSV from the quads CSV
            terms_csv_path = self._generate_terms_csv(csv_file_path, table_identifier, batch_size)
            logger.info(f"Terms CSV generated: {terms_csv_path}")
            
            return csv_file_path
                
        except Exception as e:
            # Clean up CSV file on error if it was a temp file
            if output_csv is None and os.path.exists(csv_file_path):
                os.unlink(csv_file_path)
            logger.error(f"N-Triples parsing failed: {e}")
            raise
    
    def _generate_terms_csv(self, quads_csv_path: str, table_identifier: str, batch_size: int = DEFAULT_BATCH_SIZE) -> str:
        """
        Generate terms CSV by reading quads CSV and extracting unique terms.
        
        Args:
            quads_csv_path: Path to the quads CSV file
            table_identifier: Dataset identifier to use in terms CSV
            batch_size: Number of rows to process in each batch
            
        Returns:
            str: Path to generated terms CSV file
        """
        logger.info(f"Generating terms CSV from quads CSV: {quads_csv_path}")
        
        # Create terms CSV path in same directory
        quads_path = Path(quads_csv_path)
        terms_csv_path = quads_path.parent / f"{quads_path.stem}_terms.csv"
        
        start_time = time.time()
        seen_term_hashes: Set[str] = set()
        unique_terms_count = 0
        
        def _create_term_hash(term_uuid: str, term_text: str, term_type: str, 
                             language: str = '', datatype: str = '') -> str:
            """Create a hash for term deduplication."""
            components = [term_uuid, term_text, term_type, language, datatype]
            term_string = "\x00".join(components)
            return hashlib.sha256(term_string.encode('utf-8')).hexdigest()
        
        # Open terms CSV file for streaming output
        with open(terms_csv_path, 'w', newline='', encoding='utf-8') as terms_file:
            csv_writer = csv.writer(terms_file, quoting=csv.QUOTE_MINIMAL)
            
            # Write header
            csv_writer.writerow([
                'term_uuid', 'term_text', 'term_type', 'lang', 'datatype_id', 'created_time', 'dataset'
            ])
            
            def _add_term_if_unique(term_uuid: str, term_text: str, term_type: str,
                                   language: str = '', datatype: str = ''):
                """Write term to CSV if not seen before."""
                nonlocal unique_terms_count
                term_hash = _create_term_hash(term_uuid, term_text, term_type, language, datatype)
                if term_hash not in seen_term_hashes:
                    seen_term_hashes.add(term_hash)
                    unique_terms_count += 1
                    # Write directly to CSV file
                    csv_writer.writerow([
                        term_uuid,
                        term_text,
                        term_type,
                        language or '',  # Empty string for NULL
                        '',  # datatype_id (empty string for NULL)
                        '',  # created_time (empty string for NULL)
                        table_identifier  # dataset
                    ])
        
            logger.info(f"Reading quads CSV in batches of {batch_size:,}")
            
            with open(quads_csv_path, 'r', encoding='utf-8') as quads_file:
                csv_reader = csv.DictReader(quads_file)
                
                batch_count = 0
                row_count = 0
                
                batch_rows = []
                
                for row in csv_reader:
                    batch_rows.append(row)
                    row_count += 1
                    
                    # Process batch when it reaches batch_size
                    if len(batch_rows) >= batch_size:
                        self._process_batch_for_terms(batch_rows, _add_term_if_unique)
                        batch_count += 1
                        
                        if batch_count % 10 == 0:
                            logger.info(f"Processed {batch_count * batch_size:,} rows, found {unique_terms_count:,} unique terms")
                        
                        batch_rows = []
                
                # Process remaining rows
                if batch_rows:
                    self._process_batch_for_terms(batch_rows, _add_term_if_unique)
                    batch_count += 1
            
            logger.info(f"Processed {row_count:,} total rows, found {unique_terms_count:,} unique terms")
        
        end_time = time.time()
        processing_time = end_time - start_time
        
        # Update stats
        self.stats['unique_terms'] = unique_terms_count
        self.stats['terms_processing_time'] = processing_time
        
        logger.info(f"Terms CSV generation completed: {terms_csv_path}")
        logger.info(f"Unique terms: {unique_terms_count:,}")
        logger.info(f"Processing time: {processing_time:.2f}s")
        
        return str(terms_csv_path)
    
    def _process_batch_for_terms(self, batch_rows: list, add_term_func: Callable):
        """Process a batch of rows to extract unique terms."""
        for row in batch_rows:
            # Extract subject term
            add_term_func(
                row['subject_uuid'],
                row['subject_text'],
                'U'  # Subject is always URI
            )
            
            # Extract predicate term
            add_term_func(
                row['predicate_uuid'],
                row['predicate_text'],
                'U'  # Predicate is always URI
            )
            
            # Extract object term
            object_type = 'L' if row['is_literal'].lower() == 'true' else 'U'
            add_term_func(
                row['object_uuid'],
                row['object_text'],
                object_type,
                row['object_language'],
                row['object_datatype']
            )
            
            # Extract context term (graph URI)
            add_term_func(
                row['context_uuid'],
                row['graph_uri'],
                'U'  # Context is always URI
            )

    def get_stats(self) -> Dict[str, Any]:
        """Get conversion statistics."""
        stats = self.stats.copy()
        if stats['processing_time'] > 0:
            stats['triples_per_sec'] = stats['total_triples'] / stats['processing_time']
            stats['mb_per_sec'] = stats['file_size_mb'] / stats['processing_time']
        return stats


class PostgreSQLTempTableManager:
    """Manage temporary PostgreSQL tables for CSV import testing."""
    
    def __init__(self, connection_params: Dict[str, str]):
        """
        Initialize with PostgreSQL connection parameters.
        
        Args:
            connection_params: Dict with keys: host, port, database, user, password
        """
        self.connection_params = connection_params
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    async def create_temp_tables(self, table_identifier: str) -> Dict[str, str]:
        """
        Create temporary tables for CSV import testing.
        
        Args:
            table_identifier: Identifier to include in table names
            
        Returns:
            Dict with table names
        """
        # Generate table names
        temp_term_table = f"temp_term_{table_identifier}"
        temp_quad_table = f"temp_quad_{table_identifier}"
        
        self.logger.info(f"Creating temporary tables with identifier: {table_identifier}")
        
        # Connect to database
        conn_string = (
            f"host={self.connection_params['host']} "
            f"port={self.connection_params['port']} "
            f"dbname={self.connection_params['database']} "
            f"user={self.connection_params['user']} "
            f"password={self.connection_params['password']}"
        )
        
        conn = await psycopg.AsyncConnection.connect(conn_string)
        async with conn:
            async with conn.cursor() as cursor:
                # Set session-level optimization parameters for bulk loading
                # Only include parameters that can be changed at session level
                optimization_settings = [
                    "SET synchronous_commit = off",
                    "SET work_mem = '256MB'",
                    "SET maintenance_work_mem = '1GB'",
                    "SET commit_delay = 10000",  # 10ms delay for group commits
                    "SET commit_siblings = 10"   # Wait for 10 concurrent transactions
                ]
                
                self.logger.info("Applying bulk load optimization settings...")
                for setting in optimization_settings:
                    await cursor.execute(setting)
                    self.logger.debug(f"Applied: {setting}")
                
                # Drop existing tables if they exist
                await cursor.execute(f"DROP TABLE IF EXISTS {temp_term_table}")
                await cursor.execute(f"DROP TABLE IF EXISTS {temp_quad_table}")
                
                self.logger.info(f"Dropped existing tables (if they existed)")
                
                # Create temp term table (matching main schema without indexes/partitions)
                term_sql = f"""
                    CREATE UNLOGGED TABLE {temp_term_table} (
                        term_uuid UUID PRIMARY KEY,
                        term_text TEXT NOT NULL,
                        term_type CHAR(1) NOT NULL CHECK (term_type IN ('U', 'L', 'B', 'G')),
                        lang VARCHAR(20),
                        datatype_id BIGINT,
                        created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        dataset VARCHAR(50) NOT NULL DEFAULT 'primary'
                    )
                """
                
                await cursor.execute(term_sql)
                self.logger.info(f"Created temp term table: {temp_term_table}")
                
                # Create temp quad table (matching main schema without indexes/partitions)
                quad_sql = f"""
                    CREATE UNLOGGED TABLE {temp_quad_table} (
                        subject_uuid UUID NOT NULL,
                        predicate_uuid UUID NOT NULL,
                        object_uuid UUID NOT NULL,
                        context_uuid UUID NOT NULL,
                        quad_uuid UUID NOT NULL DEFAULT gen_random_uuid(),
                        created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        dataset VARCHAR(50) NOT NULL DEFAULT 'primary',
                        PRIMARY KEY (subject_uuid, predicate_uuid, object_uuid, context_uuid, quad_uuid)
                    )
                """
                
                await cursor.execute(quad_sql)
                self.logger.info(f"Created temp quad table: {temp_quad_table}")
                
                await conn.commit()
        
        table_names = {
            'term_table': temp_term_table,
            'quad_table': temp_quad_table
        }
        
        self.logger.info(f"Successfully created temporary tables: {table_names}")
        return table_names


class PostgreSQLCSVImporter:
    """Import CSV data into PostgreSQL database."""
    
    def __init__(self, connection_params: Dict[str, str]):
        """
        Initialize with PostgreSQL connection parameters.
        
        Args:
            connection_params: Dict with keys: host, port, database, user, password
        """
        self.connection_params = connection_params
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    async def import_binary_data(self, records: list, table_name: str, columns: list) -> Dict[str, Any]:
        """
        Import structured data using binary COPY format for maximum performance.
        
        Args:
            records: List of tuples/records to import
            table_name: Target table name
            columns: List of column names
            
        Returns:
            Dict with import results
        """
        self.logger.info(f"Importing {len(records):,} records using binary COPY to: {table_name}")
        
        start_time = time.time()
        
        # Connect to database
        conn_string = (
            f"host={self.connection_params['host']} "
            f"port={self.connection_params['port']} "
            f"dbname={self.connection_params['database']} "
            f"user={self.connection_params['user']} "
            f"password={self.connection_params['password']}"
        )
        
        conn = await psycopg.AsyncConnection.connect(conn_string)
        async with conn:
            async with conn.cursor() as cursor:
                # Use binary format COPY for maximum performance
                columns_str = ', '.join(columns)
                copy_sql = f"COPY {table_name} ({columns_str}) FROM STDIN (FORMAT BINARY)"
                
                async with cursor.copy(copy_sql) as copy:
                    for record in records:
                        await copy.write_row(record)  # psycopg3 handles binary encoding
                
                # Get row count
                await cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                row_count = (await cursor.fetchone())[0]
                
                await conn.commit()
        
        import_time = time.time() - start_time
        
        result = {
            'status': 'success',
            'rows_imported': row_count,
            'import_time': import_time,
            'table_name': table_name,
            'format': 'binary'
        }
        
        self.logger.info(f"Binary import completed: {row_count:,} rows in {import_time:.2f}s")
        return result
    
    async def import_csv_to_database(self, csv_file: str, table_name: str = "rdf_quads") -> Dict[str, Any]:
        """
        Import CSV file into PostgreSQL database.
        
        Args:
            csv_file: Path to CSV file
            table_name: Target table name
            
        Returns:
            Dict with import results
        """
        self.logger.info(f"Importing CSV to PostgreSQL table: {table_name}")
        
        start_time = time.time()
        
        # Connect to database
        conn_string = (
            f"host={self.connection_params['host']} "
            f"port={self.connection_params['port']} "
            f"dbname={self.connection_params['database']} "
            f"user={self.connection_params['user']} "
            f"password={self.connection_params['password']}"
        )
        
        conn = await psycopg.AsyncConnection.connect(conn_string)
        async with conn:
            async with conn.cursor() as cursor:
                # Create table if it doesn't exist
                await self._create_table_if_not_exists(cursor, table_name)
                
                # Import CSV using COPY
                with open(csv_file, 'r', encoding='utf-8') as f:
                    # Skip header row
                    next(f)
                    
                    copy_sql = f"""
                        COPY {table_name} (
                            subject_text, predicate_text, object_text, 
                            object_datatype, object_language, is_literal, 
                            graph_uri, import_batch_id,
                            subject_uuid, predicate_uuid, object_uuid, context_uuid,
                            processing_status, dataset
                        ) FROM STDIN WITH CSV QUOTE '"'
                    """
                    
                    await cursor.copy(copy_sql, f)
                
                # Get row count
                await cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                row_count = (await cursor.fetchone())[0]
                
                await conn.commit()
        
        import_time = time.time() - start_time
        
        result = {
            'status': 'success',
            'rows_imported': row_count,
            'import_time': import_time,
            'table_name': table_name
        }
        
        self.logger.info(f"Import completed: {row_count:,} rows in {import_time:.2f}s")
        return result
    
    async def _create_table_if_not_exists(self, cursor, table_name: str):
        """Create the target table if it doesn't exist."""
        create_sql = f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id SERIAL PRIMARY KEY,
                subject_text TEXT NOT NULL,
                predicate_text TEXT NOT NULL,
                object_text TEXT NOT NULL,
                object_datatype TEXT,
                object_language TEXT,
                is_literal BOOLEAN NOT NULL,
                graph_uri TEXT NOT NULL,
                import_batch_id TEXT,
                subject_uuid UUID NOT NULL,
                predicate_uuid UUID NOT NULL,
                object_uuid UUID NOT NULL,
                context_uuid UUID NOT NULL,
                processing_status TEXT DEFAULT 'processed',
                dataset TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        
        await cursor.execute(create_sql)
        self.logger.info(f"Ensured table exists: {table_name}")


def progress_callback(processed_triples: int, rate: float):
    """Default progress callback for monitoring conversion progress."""
    print(f"  Processed: {processed_triples:,} triples ({rate:.0f} triples/sec)")


def main():
    """Main function for testing CSV conversion."""
    # Configuration - modify these as needed
    input_file = "/Users/hadfield/Local/vital-git/vital-graph/test_data/kgframe-wordnet-0.0.2.nt"
    output_dir = "/Users/hadfield/Local/vital-git/vital-graph/test_data"
    output_csv = f"{output_dir}/wordnet_output.csv"
    graph_uri = DEFAULT_GRAPH_URI
    batch_size = DEFAULT_BATCH_SIZE
    
    # Validate input file exists
    if not Path(input_file).exists():
        print(f"❌ ERROR: Input file not found: {input_file}")
        return False
    
    # Ensure output directory exists
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # Database configuration (optional)
    import_to_db = False  # Set to True to import to database
    connection_params = {
        'host': 'localhost',
        'port': '5432',
        'database': 'vitalgraphdb',
        'user': 'postgres',
        'password': ''
    }
    table_name = "rdf_quads"
    
    # Convert N-Triples to CSV
    converter = NTriplesCSVConverter()
    
    try:
        print(f"🚀 Converting N-Triples to CSV")
        print(f"Input file: {input_file}")
        print(f"Graph URI: {graph_uri}")
        
        # Start total processing timer
        total_start_time = time.time()
        
        csv_file = converter.convert_ntriples_to_csv(
            input_file,
            output_csv,
            graph_uri,
            TABLE_IDENTIFIER,
            batch_size,
            progress_callback
        )
        
        total_processing_time = time.time() - total_start_time
        
        # Display comprehensive timing statistics
        stats = converter.get_stats()
        
        print(f"\n⏱️ Detailed Timing Breakdown:")
        print(f"Total processing time: {total_processing_time:.2f}s")
        print(f"N-Triples parsing time: {stats['processing_time']:.2f}s ({stats['processing_time']/total_processing_time*100:.1f}% of total)")
        if stats['unique_terms'] > 0 and stats['terms_processing_time'] > 0:
            print(f"Terms extraction time: {stats['terms_processing_time']:.2f}s ({stats['terms_processing_time']/total_processing_time*100:.1f}% of total)")
            other_time = total_processing_time - stats['processing_time'] - stats['terms_processing_time']
            if other_time > 0:
                print(f"Other operations time: {other_time:.2f}s ({other_time/total_processing_time*100:.1f}% of total)")
        
        print(f"\n📊 Conversion Results:")
        print(f"Total triples: {stats['total_triples']:,}")
        print(f"N-Triples parsing: {stats['processing_time']:.2f}s")
        print(f"File size: {stats['file_size_mb']:.1f} MB")
        if 'triples_per_sec' in stats:
            print(f"Parsing rate: {stats['triples_per_sec']:,.0f} triples/sec")
            print(f"MB/sec: {stats['mb_per_sec']:.2f}")
        print(f"Output CSV: {csv_file}")
        
        # Display terms statistics
        if stats['unique_terms'] > 0:
            print(f"\n📋 Terms Extraction Results:")
            print(f"Unique terms: {stats['unique_terms']:,}")
            print(f"Terms processing time: {stats['terms_processing_time']:.2f}s")
            if stats['terms_processing_time'] > 0:
                terms_per_sec = stats['unique_terms'] / stats['terms_processing_time']
                print(f"Terms extraction rate: {terms_per_sec:,.0f} terms/sec")
            
            # Show terms CSV path
            quads_path = Path(csv_file)
            terms_csv_path = quads_path.parent / f"{quads_path.stem}_terms.csv"
            print(f"Terms CSV: {terms_csv_path}")
        
        # Create temporary tables after CSV generation
        print(f"\n🗄️ Creating temporary PostgreSQL tables...")
        table_creation_start = time.time()
        table_manager = PostgreSQLTempTableManager(connection_params)
        
        async def create_tables():
            return await table_manager.create_temp_tables(TABLE_IDENTIFIER)
        
        table_names = asyncio.run(create_tables())
        table_creation_time = time.time() - table_creation_start
        
        print(f"📋 Temporary Tables Created in {table_creation_time:.2f}s:")
        print(f"Term table: {table_names['term_table']}")
        print(f"Quad table: {table_names['quad_table']}")
        
        # Import CSV data into temporary tables
        print(f"\n📥 Importing CSV data into temporary tables...")
        import_start_time = time.time()
        
        async def import_csv_data():
            # Convert connection_params to use 'dbname' instead of 'database'
            conn_params = connection_params.copy()
            conn_params['dbname'] = conn_params.pop('database')
            conn = await psycopg.AsyncConnection.connect(**conn_params)
            async with conn:
                async with conn.cursor() as cursor:
                    # Import terms CSV using block-level COPY (optimal performance)
                    print(f"Importing terms from: {terms_csv_path}")
                    terms_import_start = time.time()
                    
                    async with cursor.copy(f"COPY {table_names['term_table']} (term_uuid, term_text, term_type, lang, datatype_id, created_time, dataset) FROM STDIN WITH (FORMAT CSV, HEADER true, NULL '')") as copy:
                        with open(terms_csv_path, 'rb') as f:
                            while chunk := f.read(BLOCK_SIZE):
                                await copy.write(chunk)
                    
                    terms_import_time = time.time() - terms_import_start
                    
                    # Get terms count
                    await cursor.execute(f"SELECT COUNT(*) FROM {table_names['term_table']}")
                    terms_count = (await cursor.fetchone())[0]
                    terms_per_sec = terms_count / terms_import_time if terms_import_time > 0 else 0
                    print(f"✅ Imported {terms_count:,} terms in {terms_import_time:.2f}s ({terms_per_sec:,.0f} terms/sec)")
                    
                    # Import quads CSV using block-level COPY with column selection (optimal performance)
                    print(f"Importing quads from: {csv_file}")
                    quads_import_start = time.time()
                    
                    # Use PostgreSQL COPY with column selection to skip unwanted columns
                    # Original CSV columns: subject_text, predicate_text, object_text, context_text, 
                    #                      subject_type, predicate_type, object_type, context_type,
                    #                      subject_uuid, predicate_uuid, object_uuid, context_uuid
                    # We want columns 9,10,11,12 (1-indexed) which are the UUID columns
                    copy_sql = f"""
                        COPY {table_names['quad_table']} (subject_uuid, predicate_uuid, object_uuid, context_uuid, dataset) 
                        FROM STDIN WITH (
                            FORMAT CSV, 
                            HEADER true,
                            NULL '',
                            FORCE_NULL (subject_uuid, predicate_uuid, object_uuid, context_uuid)
                        )
                    """
                    
                    async with cursor.copy(copy_sql) as copy:
                        with open(csv_file, 'rb') as f:
                            # Read and modify each line to add dataset column and select only UUID columns
                            import csv as csv_module
                            import io
                            
                            # Process in chunks for memory efficiency
                            chunk_lines = []
                            line_count = 0
                            
                            for line in f:
                                line_str = line.decode('utf-8').strip()
                                if line_count == 0:  # Skip header
                                    line_count += 1
                                    continue
                                    
                                if line_str:
                                    # Parse CSV line and extract UUID columns (indices 8,9,10,11) + add dataset
                                    row = next(csv_module.reader([line_str]))
                                    if len(row) >= 12:
                                        # Extract UUID columns and add dataset
                                        uuid_line = f"{row[8]},{row[9]},{row[10]},{row[11]},{TABLE_IDENTIFIER}\n"
                                        chunk_lines.append(uuid_line)
                                        
                                        # Write in chunks of 10000 lines for optimal performance
                                        if len(chunk_lines) >= 10000:
                                            chunk_data = ''.join(chunk_lines).encode('utf-8')
                                            await copy.write(chunk_data)
                                            chunk_lines = []
                                
                                line_count += 1
                            
                            # Write remaining lines
                            if chunk_lines:
                                chunk_data = ''.join(chunk_lines).encode('utf-8')
                                await copy.write(chunk_data)
                    
                    quads_import_time = time.time() - quads_import_start
                    
                    # Get quads count
                    await cursor.execute(f"SELECT COUNT(*) FROM {table_names['quad_table']}")
                    quads_count = (await cursor.fetchone())[0]
                    quads_per_sec = quads_count / quads_import_time if quads_import_time > 0 else 0
                    print(f"✅ Imported {quads_count:,} quads in {quads_import_time:.2f}s ({quads_per_sec:,.0f} quads/sec)")
                    
                    await conn.commit()
                    
                    # Return timing statistics
                    return {
                        'terms_count': terms_count,
                        'terms_import_time': terms_import_time,
                        'terms_per_sec': terms_per_sec,
                        'quads_count': quads_count,
                        'quads_import_time': quads_import_time,
                        'quads_per_sec': quads_per_sec
                    }
        
        import_stats = asyncio.run(import_csv_data())
        total_import_time = time.time() - import_start_time
        
        # Display comprehensive import timing results
        print(f"\n📊 Import Performance Results:")
        print(f"Terms import: {import_stats['terms_import_time']:.2f}s ({import_stats['terms_per_sec']:,.0f} terms/sec)")
        print(f"Quads import: {import_stats['quads_import_time']:.2f}s ({import_stats['quads_per_sec']:,.0f} quads/sec)")
        print(f"Total import time: {total_import_time:.2f}s")
        
        # Calculate overall throughput
        total_records = import_stats['terms_count'] + import_stats['quads_count']
        overall_throughput = total_records / total_import_time if total_import_time > 0 else 0
        print(f"Overall throughput: {overall_throughput:,.0f} records/sec")
        
        # Display comprehensive end-to-end timing
        end_to_end_time = time.time() - total_start_time
        print(f"\n🕐 End-to-End Performance Summary:")
        print(f"N-Triples parsing: {stats['processing_time']:.2f}s ({stats['processing_time']/end_to_end_time*100:.1f}%)")
        if stats['unique_terms'] > 0 and stats['terms_processing_time'] > 0:
            print(f"Terms extraction: {stats['terms_processing_time']:.2f}s ({stats['terms_processing_time']/end_to_end_time*100:.1f}%)")
        print(f"Table creation: {table_creation_time:.2f}s ({table_creation_time/end_to_end_time*100:.1f}%)")
        print(f"Database import: {total_import_time:.2f}s ({total_import_time/end_to_end_time*100:.1f}%)")
        print(f"Total end-to-end: {end_to_end_time:.2f}s")
        print(f"Overall pipeline throughput: {stats['total_triples']/end_to_end_time:,.0f} triples/sec")
        
        print(f"\n🎉 CSV import completed successfully!")
        
        # Import to database if requested
        if import_to_db:
            print(f"\n📥 Importing to PostgreSQL database...")
            
            importer = PostgreSQLCSVImporter(connection_params)
            
            async def import_data():
                return await importer.import_csv_to_database(csv_file, table_name)
            
            import_result = asyncio.run(import_data())
            
            print(f"📈 Import Results:")
            print(f"Rows imported: {import_result['rows_imported']:,}")
            print(f"Import time: {import_result['import_time']:.2f}s")
            print(f"Table: {import_result['table_name']}")
        
        print(f"\n✅ SUCCESS: Conversion completed successfully!")
        return True
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        logger.exception("Conversion failed")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)