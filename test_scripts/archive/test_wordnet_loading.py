#!/usr/bin/env python3
"""
Test script for WordNet RDF data loading using PostgreSQLSpaceImpl

This script loads WordNet RDF data into a test space using the high-performance
batch loading capabilities and validates the loading process.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import List, Tuple

# Add the parent directory to the path to import vitalgraph modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.rdf.rdf_utils import stream_parse_ntriples_nquads_generator, RDFFormat
from rdflib import Graph, URIRef, Literal, BNode

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class WordNetDataLoader:
    """WordNet RDF data loader for testing."""
    
    def __init__(self, config_path: str, space_id: str = "wordnet_space"):
        self.config_path = config_path
        self.space_id = space_id
        self.vitalgraph_impl = None
        self.db_impl = None
        self.space_impl = None
        
        # Data file path
        self.wordnet_file = Path(__file__).parent.parent / "test_data" / "kgentity_wordnet.nt"
        
    async def setup(self):
        """Initialize VitalGraph components."""
        try:
            logger.info("Setting up VitalGraph components...")
            
            # Load config first
            from vitalgraph.config.config_loader import get_config
            config = get_config(self.config_path)
            
            if not config:
                raise RuntimeError("Failed to load configuration")
            
            # Initialize VitalGraph implementation with config
            self.vitalgraph_impl = VitalGraphImpl(config=config)
            
            # Get database implementation
            self.db_impl = self.vitalgraph_impl.get_db_impl()
            if not self.db_impl:
                raise RuntimeError("Failed to initialize database implementation")
                
            await self.db_impl.connect()
            
            # Get space implementation
            self.space_impl = self.db_impl.get_space_impl()
            if not self.space_impl:
                raise RuntimeError("Space implementation not available")
            
            logger.info("VitalGraph components initialized successfully")
            
        except Exception as e:
            logger.error(f"Error setting up VitalGraph components: {e}")
            raise
    
    async def teardown(self):
        """Clean up VitalGraph components."""
        try:
            if self.db_impl:
                await self.db_impl.disconnect()
            logger.info("VitalGraph components cleaned up")
        except Exception as e:
            logger.error(f"Error during teardown: {e}")
    
    def check_wordnet_file(self) -> bool:
        """Check if WordNet data file exists."""
        if self.wordnet_file.exists():
            file_size = self.wordnet_file.stat().st_size
            logger.info(f"WordNet data file found: {self.wordnet_file}")
            logger.info(f"File size: {file_size:,} bytes ({file_size/1024/1024:.1f} MB)")
            return True
        else:
            logger.error(f"WordNet data file not found: {self.wordnet_file}")
            return False
    
    async def create_or_recreate_space(self):
        """Create or recreate the test space."""
        try:
            # Check if space exists
            try:
                space_info = await self.space_impl.get_space_info(self.space_id)
                logger.info(f"Space '{self.space_id}' already exists")
                
                # Ask if we should recreate it
                logger.info("Recreating space to ensure clean state...")
                await self.space_impl.delete_space_tables(self.space_id)
                logger.info(f"Deleted existing space '{self.space_id}'")
                
            except Exception:
                logger.info(f"Space '{self.space_id}' does not exist")
            
            # Create the space using UUID-based tables
            logger.info(f"Creating UUID-based space '{self.space_id}'...")
            success = self.space_impl.create_space_tables(self.space_id)
            if not success:
                raise RuntimeError(f"Failed to create UUID-based space tables for '{self.space_id}'")
            logger.info(f"UUID-based space '{self.space_id}' created successfully")
            
            # Verify space creation
            space_info = await self.space_impl.get_space_info(self.space_id)
            logger.info(f"Space info: {space_info}")
            
        except Exception as e:
            logger.error(f"Error creating space: {e}")
            raise
    
    def parse_ntriples_line(self, line: str) -> Tuple[str, str, str]:
        """
        Parse a single N-Triples line into subject, predicate, object.
        
        This is a simplified parser for the specific WordNet format.
        """
        line = line.strip()
        if not line or line.startswith('#'):
            return None, None, None
        
        # Split by spaces, but handle quoted literals
        parts = []
        current_part = ""
        in_quotes = False
        
        i = 0
        while i < len(line):
            char = line[i]
            
            if char == '"' and (i == 0 or line[i-1] != '\\'):
                in_quotes = not in_quotes
                current_part += char
            elif char == ' ' and not in_quotes:
                if current_part:
                    parts.append(current_part)
                    current_part = ""
            else:
                current_part += char
            
            i += 1
        
        if current_part:
            parts.append(current_part)
        
        if len(parts) >= 3:
            # Remove trailing dot from object if present
            obj = parts[2]
            if obj.endswith(' .'):
                obj = obj[:-2]
            elif obj.endswith('.'):
                obj = obj[:-1]
            
            return parts[0], parts[1], obj
        
        return None, None, None
    
    async def load_wordnet_data_batch(self, batch_size: int = 10000) -> dict:
        """
        Load WordNet data using batch processing.
        
        Args:
            batch_size: Number of triples to process in each batch
            
        Returns:
            Dictionary with loading statistics
        """
        if not self.wordnet_file.exists():
            raise FileNotFoundError(f"WordNet data file not found: {self.wordnet_file}")
        
        logger.info(f"Starting WordNet data loading with batch size {batch_size}")
        start_time = time.time()
        
        total_lines = 0
        processed_triples = 0
        batch_count = 0
        error_count = 0
        
        # Use streaming parser like the working test script
        batch_quads = []
        context = "http://vital.ai/graph/wordnet"  # Default context
        
        # Stream triples using the proven parser
        for triple in stream_parse_ntriples_nquads_generator(str(self.wordnet_file), RDFFormat.NT, progress_interval=25000):
            total_lines += 1
            
            try:
                # Extract subject, predicate, object from the triple
                subject_str, predicate_str, obj_str = triple
                
                # Convert to RDFLib terms
                subject = self._convert_string_to_rdflib_term(subject_str)
                predicate = self._convert_string_to_rdflib_term(predicate_str)
                obj = self._convert_string_to_rdflib_term(obj_str)
                context_term = URIRef(context)
                
                # Create quad tuple
                quad = (subject, predicate, obj, context_term)
                batch_quads.append(quad)
                processed_triples += 1
                
                # Process batch when full
                if len(batch_quads) >= batch_size:
                    try:
                        await self._process_rdflib_batch(batch_quads, batch_count + 1)
                        batch_count += 1
                        batch_quads = []
                    except Exception as e:
                        logger.error(f"Error processing batch {batch_count + 1}: {e}")
                        error_count += 1
                        batch_quads = []  # Clear batch and continue
                
                # Progress logging
                if processed_triples % 100000 == 0:
                    elapsed = time.time() - start_time
                    rate = processed_triples / elapsed if elapsed > 0 else 0
                    logger.info(f"Processed {processed_triples:,} triples ({rate:.0f} triples/sec)")
                    
            except Exception as e:
                logger.warning(f"Error processing triple {total_lines}: {e}")
                continue
        
        # Process remaining batch
        if batch_quads:
            try:
                await self._process_rdflib_batch(batch_quads, batch_count + 1)
                batch_count += 1
            except Exception as e:
                logger.error(f"Error processing final batch: {e}")
                error_count += 1
        
        # Calculate final statistics
        end_time = time.time()
        total_time = end_time - start_time
        avg_rate = processed_triples / total_time if total_time > 0 else 0
        
        stats = {
            "total_lines": total_lines,
            "processed_triples": processed_triples,
            "batch_count": batch_count,
            "error_count": error_count,
            "total_time_seconds": total_time,
            "average_rate_triples_per_second": avg_rate
        }
        
        logger.info(f"\n{'='*60}")
        logger.info("WORDNET DATA LOADING SUMMARY")
        logger.info(f"{'='*60}")
        logger.info(f"Total lines processed: {stats['total_lines']:,}")
        logger.info(f"Valid triples loaded: {stats['processed_triples']:,}")
        logger.info(f"Batches processed: {stats['batch_count']:,}")
        logger.info(f"Errors encountered: {stats['error_count']:,}")
        logger.info(f"Total time: {stats['total_time_seconds']:.1f} seconds")
        logger.info(f"Average rate: {stats['average_rate_triples_per_second']:.0f} triples/second")
        
        return stats
    
    async def _process_rdflib_batch(self, batch_quads: List[Tuple], batch_num: int):
        """Process a batch of RDFLib quad tuples using high-performance batch insert."""
        logger.debug(f"Processing RDFLib batch {batch_num} with {len(batch_quads)} quads")
        
        batch_start = time.time()
        
        try:
            # Use high-performance batch insert directly with RDFLib quads
            inserted_count = await self.space_impl.add_rdf_quads_batch(self.space_id, batch_quads)
            
            batch_time = time.time() - batch_start
            rate = inserted_count / batch_time if batch_time > 0 else 0
            logger.debug(f"RDFLib batch {batch_num} completed: {inserted_count:,} quads in {batch_time:.2f}s ({rate:.0f} quads/sec)")
            
            if inserted_count != len(batch_quads):
                logger.warning(f"RDFLib batch {batch_num}: Expected {len(batch_quads)} quads, inserted {inserted_count}")
                
        except Exception as e:
            logger.error(f"Error processing RDFLib batch {batch_num}: {e}")
            raise
    
    async def _process_batch(self, batch_quads: List[Tuple[str, str, str, str]], batch_num: int):
        """Process a batch of quads using high-performance batch insert."""
        logger.debug(f"Processing batch {batch_num} with {len(batch_quads)} quads")
        
        batch_start = time.time()
        
        try:
            # Convert string tuples to RDFLib quad tuples
            rdflib_quads = []
            for subject, predicate, obj, context in batch_quads:
                try:
                    # Convert strings to RDFLib terms
                    s_term = self._string_to_rdflib_term(subject)
                    p_term = self._string_to_rdflib_term(predicate)
                    o_term = self._string_to_rdflib_term(obj)
                    c_term = self._string_to_rdflib_term(context)
                    
                    rdflib_quads.append((s_term, p_term, o_term, c_term))
                    
                except Exception as e:
                    logger.warning(f"Error converting quad ({subject}, {predicate}, {obj}): {e}")
                    continue
            
            # Use high-performance batch insert
            if rdflib_quads:
                inserted_count = await self.space_impl.add_rdf_quads_batch(self.space_id, rdflib_quads)
                
                batch_time = time.time() - batch_start
                rate = inserted_count / batch_time if batch_time > 0 else 0
                logger.debug(f"Batch {batch_num} completed: {inserted_count:,} quads in {batch_time:.2f}s ({rate:.0f} quads/sec)")
                
                if inserted_count != len(rdflib_quads):
                    logger.warning(f"Batch {batch_num}: Expected {len(rdflib_quads)} quads, inserted {inserted_count}")
            else:
                logger.warning(f"Batch {batch_num}: No valid quads to insert")
                
        except Exception as e:
            logger.error(f"Error processing batch {batch_num}: {e}")
            raise
    
    def _convert_string_to_rdflib_term(self, term_str: str):
        """Convert string representation to appropriate RDFLib term (matches working test script)."""
        term_str = term_str.strip()
        
        if term_str.startswith('<') and term_str.endswith('>'):
            # URI reference
            return URIRef(term_str[1:-1])  # Remove < >
        elif term_str.startswith('_:'):
            # Blank node
            return BNode(term_str[2:])  # Remove _:
        elif term_str.startswith('"'):
            # Literal - handle various forms
            if term_str.endswith('"'):
                # Simple literal
                return Literal(term_str[1:-1])  # Remove quotes
            else:
                # Literal with language tag or datatype
                if '"@' in term_str:
                    # Language tag
                    literal_part, lang_part = term_str.rsplit('"@', 1)
                    literal_value = literal_part[1:]  # Remove opening quote
                    return Literal(literal_value, lang=lang_part)
                elif '"^^' in term_str:
                    # Datatype
                    literal_part, datatype_part = term_str.rsplit('"^^', 1)
                    literal_value = literal_part[1:]  # Remove opening quote
                    if datatype_part.startswith('<') and datatype_part.endswith('>'):
                        datatype = URIRef(datatype_part[1:-1])
                    else:
                        datatype = URIRef(datatype_part)
                    return Literal(literal_value, datatype=datatype)
                else:
                    return Literal(term_str[1:])  # Fallback
        else:
            # Assume URI if not quoted or blank node
            return URIRef(term_str)
    
    def _string_to_rdflib_term(self, term_str: str):
        """Convert string representation to RDFLib term (legacy method)."""
        return self._convert_string_to_rdflib_term(term_str)
    
    async def verify_loading(self) -> dict:
        """Verify the loaded data."""
        logger.info("Verifying loaded data...")
        
        try:
            # Get space info
            space_info = await self.space_impl.get_space_info(self.space_id)
            logger.info(f"Space info after loading: {space_info}")
            
            # Count quads
            quad_count = await self.space_impl.get_quad_count(self.space_id)
            logger.info(f"Total quads in space: {quad_count:,}")
            
            # Sample some quads
            logger.info("Sampling loaded quads...")
            sample_count = 0
            async for quad, contexts in self.space_impl.quads(self.space_id, (None, None, None, None)):
                if sample_count < 5:
                    s, p, o, c = quad
                    logger.info(f"  Sample quad {sample_count + 1}: ({s}, {p}, {o}, {c})")
                    sample_count += 1
                else:
                    break
            
            return {
                "space_info": space_info,
                "quad_count": quad_count,
                "verification_successful": True
            }
            
        except Exception as e:
            logger.error(f"Error during verification: {e}")
            return {
                "space_info": None,
                "quad_count": 0,
                "verification_successful": False,
                "error": str(e)
            }


async def main():
    """Main loading function."""
    # Configuration path
    config_path = Path(__file__).parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
    if not config_path.exists():
        logger.error(f"Configuration file not found: {config_path}")
        return 1
    
    # Initialize loader
    loader = WordNetDataLoader(str(config_path))
    
    try:
        # Setup
        await loader.setup()
        
        # Check WordNet file
        if not loader.check_wordnet_file():
            logger.error("WordNet data file not available. Cannot proceed with loading.")
            return 1
        
        # Create/recreate space
        await loader.create_or_recreate_space()
        
        # Load data
        logger.info("Starting WordNet data loading...")
        loading_stats = await loader.load_wordnet_data_batch(batch_size=5000)
        
        # Verify loading
        verification_results = await loader.verify_loading()
        
        if verification_results["verification_successful"]:
            logger.info("✅ WordNet data loading completed successfully!")
            return 0
        else:
            logger.error("❌ WordNet data loading verification failed!")
            return 1
            
    except Exception as e:
        logger.error(f"WordNet data loading failed: {e}")
        return 1
    finally:
        await loader.teardown()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
