"""
RDF Utilities for VitalGraph

Provides utilities for parsing, validating, and processing RDF files in various formats.
"""

import os
import time
import gzip
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple, Generator, Union
from dataclasses import dataclass
from enum import Enum

from rdflib import Graph, Namespace, URIRef, Literal, BNode
from rdflib.exceptions import ParserError
from rdflib.plugins.parsers.notation3 import BadSyntax

from ..utils.file_utils import FileType, detect_rdf_format as _detect_rdf_format


class RDFFormat(Enum):
    """Supported RDF formats."""
    TURTLE = "turtle"
    XML = "xml"
    N3 = "n3"
    NT = "nt"
    JSON_LD = "json-ld"
    TRIG = "trig"
    NQUADS = "nquads"


# Mapping between FileType and RDFFormat for compatibility
_FILETYPE_TO_RDFFORMAT = {
    FileType.RDF_TURTLE: RDFFormat.TURTLE,
    FileType.RDF_XML: RDFFormat.XML,
    FileType.RDF_N3: RDFFormat.N3,
    FileType.RDF_NT: RDFFormat.NT,
    FileType.RDF_JSON_LD: RDFFormat.JSON_LD,
    FileType.RDF_TRIG: RDFFormat.TRIG,
    FileType.RDF_NQUADS: RDFFormat.NQUADS,
}

_RDFFORMAT_TO_FILETYPE = {v: k for k, v in _FILETYPE_TO_RDFFORMAT.items()}


@dataclass
class RDFValidationResult:
    """Result of RDF file validation."""
    is_valid: bool
    format_detected: Optional[RDFFormat]
    triple_count: int
    file_size_bytes: int
    parsing_time_ms: float
    error_message: Optional[str] = None
    warnings: List[str] = None
    namespaces: Dict[str, str] = None
    
    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []
        if self.namespaces is None:
            self.namespaces = {}


def detect_rdf_format(file_path: str, content_sample: Optional[str] = None) -> Optional[RDFFormat]:
    """Detect RDF format from file extension and content.
    
    This function now uses the centralized file detection logic from file_utils.
    """
    # Use the file_utils detection function
    file_type = _detect_rdf_format(file_path, content_sample)
    
    # Convert FileType to RDFFormat for backward compatibility
    if file_type in _FILETYPE_TO_RDFFORMAT:
        return _FILETYPE_TO_RDFFORMAT[file_type]
    
    return None


def validate_rdf_file(file_path: str, 
                     expected_format: Optional[RDFFormat] = None,
                     max_file_size_mb: int = 500) -> RDFValidationResult:
    """Parse and validate an RDF file, confirming it's not corrupted.
    
    Args:
        file_path: Path to the RDF file to validate
        expected_format: Expected RDF format, will auto-detect if None
        max_file_size_mb: Maximum allowed file size in MB
        
    Returns:
        RDFValidationResult with validation details
    """
    import time
    
    start_time = time.time()
    warnings = []
    
    try:
        # Check if file exists and is readable
        path = Path(file_path)
        if not path.exists():
            return RDFValidationResult(
                is_valid=False,
                format_detected=None,
                triple_count=0,
                file_size_bytes=0,
                parsing_time_ms=0,
                error_message=f"File does not exist: {file_path}"
            )
        
        if not path.is_file():
            return RDFValidationResult(
                is_valid=False,
                format_detected=None,
                triple_count=0,
                file_size_bytes=0,
                parsing_time_ms=0,
                error_message=f"Path is not a file: {file_path}"
            )
        
        # Check file size
        file_size = path.stat().st_size
        file_size_mb = file_size / (1024 * 1024)
        
        if file_size_mb > max_file_size_mb:
            warnings.append(f"File size ({file_size_mb:.1f} MB) exceeds recommended maximum ({max_file_size_mb} MB)")
        
        if file_size == 0:
            return RDFValidationResult(
                is_valid=False,
                format_detected=None,
                triple_count=0,
                file_size_bytes=0,
                parsing_time_ms=0,
                error_message="File is empty"
            )
        
        # Read a sample of the file for format detection
        content_sample = None
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content_sample = f.read(1024)  # Read first 1KB for format detection
        except UnicodeDecodeError:
            # Try with different encodings
            for encoding in ['latin-1', 'cp1252', 'iso-8859-1']:
                try:
                    with open(file_path, 'r', encoding=encoding) as f:
                        content_sample = f.read(1024)
                    warnings.append(f"File encoding detected as {encoding} (not UTF-8)")
                    break
                except UnicodeDecodeError:
                    continue
            
            if content_sample is None:
                return RDFValidationResult(
                    is_valid=False,
                    format_detected=None,
                    triple_count=0,
                    file_size_bytes=file_size,
                    parsing_time_ms=(time.time() - start_time) * 1000,
                    error_message="Unable to decode file with any supported encoding"
                )
        
        # Detect format
        detected_format = expected_format or detect_rdf_format(file_path, content_sample)
        
        if detected_format is None:
            return RDFValidationResult(
                is_valid=False,
                format_detected=None,
                triple_count=0,
                file_size_bytes=file_size,
                parsing_time_ms=(time.time() - start_time) * 1000,
                error_message="Unable to detect RDF format"
            )
        
        # Parse the RDF file using streaming approach
        try:
            validation_result = _stream_parse_rdf_file(
                file_path, detected_format, expected_format, warnings
            )
            if not validation_result['success']:
                return RDFValidationResult(
                    is_valid=False,
                    format_detected=validation_result.get('format_used', detected_format),
                    triple_count=0,
                    file_size_bytes=file_size,
                    parsing_time_ms=(time.time() - start_time) * 1000,
                    error_message=validation_result['error_message']
                )
            
            triple_count = validation_result['triple_count']
            detected_format = validation_result['format_used']
            namespaces = validation_result['namespaces']
            validation_warnings = validation_result['validation_warnings']
            warnings.extend(validation_warnings)
            
        except Exception as e:
            return RDFValidationResult(
                is_valid=False,
                format_detected=detected_format,
                triple_count=0,
                file_size_bytes=file_size,
                parsing_time_ms=(time.time() - start_time) * 1000,
                error_message=f"Failed to parse RDF file: {str(e)}"
            )
        
        if triple_count == 0:
            warnings.append("File parsed successfully but contains no triples")
        
        parsing_time = (time.time() - start_time) * 1000
        
        return RDFValidationResult(
            is_valid=True,
            format_detected=detected_format,
            triple_count=triple_count,
            file_size_bytes=file_size,
            parsing_time_ms=parsing_time,
            warnings=warnings,
            namespaces=namespaces
        )
        
    except Exception as e:
        parsing_time = (time.time() - start_time) * 1000
        return RDFValidationResult(
            is_valid=False,
            format_detected=None,
            triple_count=0,
            file_size_bytes=0,
            parsing_time_ms=parsing_time,
            error_message=f"Unexpected error during validation: {str(e)}"
        )


def _stream_parse_rdf_file(file_path: str, 
                          detected_format: RDFFormat,
                          expected_format: Optional[RDFFormat],
                          warnings: List[str]) -> Dict[str, Any]:
    """Parse RDF file using the best available streaming method.
    
    Tries multiple streaming approaches in order of efficiency:
    1. Custom streaming parsers - Format-specific implementations
    2. rdflib fallback - Memory-based parsing
    
    Args:
        file_path: Path to RDF file
        detected_format: Initially detected format
        expected_format: Expected format (if any)
        warnings: List to append warnings to
        
    Returns:
        Dictionary with parsing results
    """
    # Check file size
    file_size = Path(file_path).stat().st_size
    file_size_mb = file_size / (1024 * 1024)
    
    # Try parsing with detected format first
    formats_to_try = [detected_format]
    if expected_format is None:
        # Add other formats as fallbacks
        formats_to_try.extend([f for f in RDFFormat if f != detected_format])
    
    last_error = None
    
    for format_to_try in formats_to_try:
        try:
            # Choose best parsing method based on available libraries and format
            result = None
            method_used = None
            
            # Method 1: Custom streaming parsers
            if format_to_try in [RDFFormat.NT, RDFFormat.NQUADS]:
                result = _stream_parse_ntriples_nquads(file_path, format_to_try)
                method_used = f"Custom {format_to_try.value} streaming"
            
            # Method 2: rdflib fallback (loads into memory)
            if result is None or not result['success']:
                if file_size_mb > 100:
                    warnings.append(f"Large file ({file_size_mb:.1f} MB) will be loaded into memory for {format_to_try.value} parsing")
                
                result = _memory_parse_with_rdflib(file_path, format_to_try)
                method_used = "rdflib memory parsing"
            
            if result and result['success']:
                # If format was different from detected, note the correction
                if format_to_try != detected_format:
                    warnings.append(f"Format auto-corrected from {detected_format.value} to {format_to_try.value}")
                
                # Add parsing method info
                result['validation_warnings'].append(f"Parsed using: {method_used}")
                
                # Add memory usage warning for large files with memory-based parsing
                if file_size_mb > 100 and "memory" in method_used:
                    result['validation_warnings'].append(
                        f"File parsed in memory ({file_size_mb:.1f} MB). Consider installing Redland for streaming validation."
                    )
                
                return {
                    'success': True,
                    'triple_count': result['triple_count'],
                    'format_used': format_to_try,
                    'namespaces': result['namespaces'],
                    'validation_warnings': result['validation_warnings']
                }
            else:
                last_error = result.get('error', 'Unknown parsing error') if result else 'No parser available'
                continue
                
        except Exception as e:
            last_error = e
            continue
    
    # If we get here, no format worked
    error_msg = f"Failed to parse RDF file with any supported format. Last error: {str(last_error)}"
    if expected_format:
        error_msg = f"Failed to parse RDF file with expected format {expected_format.value}: {str(last_error)}"
    
    return {
        'success': False,
        'error_message': error_msg,
        'format_used': detected_format
    }

def _memory_parse_with_rdflib(file_path: str, format_type: RDFFormat) -> Dict[str, Any]:
    """Parse RDF file using rdflib (loads entire file into memory)."""
    try:
        temp_graph = Graph()
        temp_graph.parse(file_path, format=format_type.value)
        
        triple_count = 0
        blank_node_count = 0
        malformed_uri_count = 0
        
        for subject, predicate, obj in temp_graph:
            triple_count += 1
            
            if isinstance(subject, BNode) or isinstance(obj, BNode):
                blank_node_count += 1
            
            for node in [subject, predicate, obj]:
                if isinstance(node, URIRef):
                    uri_str = str(node)
                    if ' ' in uri_str or '\n' in uri_str or '\t' in uri_str:
                        malformed_uri_count += 1
        
        namespaces = {prefix: str(namespace) for prefix, namespace in temp_graph.namespaces()}
        temp_graph = None  # Clear memory
        
        validation_warnings = []
        if blank_node_count > 0:
            validation_warnings.append(f"Graph contains {blank_node_count} blank nodes")
        if malformed_uri_count > 0:
            validation_warnings.append(f"Found {malformed_uri_count} potentially malformed URIs")
        
        return {
            'success': True,
            'triple_count': triple_count,
            'blank_node_count': blank_node_count,
            'malformed_uri_count': malformed_uri_count,
            'namespaces': namespaces,
            'validation_warnings': validation_warnings
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'rdflib parsing error: {str(e)}'
        }


def stream_parse_ntriples_nquads_generator(file_path: str, format_type: RDFFormat, 
                                          progress_interval: int = 10000) -> Generator[Tuple[str, ...], None, Dict[str, Any]]:
    """Generator that yields N-Triples or N-Quads line by line with progress logging.
    
    Args:
        file_path: Path to the RDF file
        format_type: RDFFormat.NT or RDFFormat.NQUADS
        progress_interval: Log progress every N triples/quads
        
    Yields:
        Tuple of (subject, predicate, object) for N-Triples
        Tuple of (subject, predicate, object, graph) for N-Quads
        
    Returns:
        Dictionary with parsing statistics and validation results
    """
    logger = logging.getLogger(__name__)
    
    # Determine if file is gzipped
    is_gzipped = file_path.lower().endswith('.gz')
    
    # Determine expected number of components based on format
    expected_components = 4 if format_type == RDFFormat.NQUADS else 3
    format_name = "N-Quads" if format_type == RDFFormat.NQUADS else "N-Triples"
    
    # Get file size for progress tracking
    file_size = os.path.getsize(file_path)
    file_size_mb = file_size / (1024 * 1024)
    
    logger.info(f"Starting streaming parse of {format_name} file: {file_path} ({file_size_mb:.1f} MB)")
    
    triple_count = 0
    blank_node_count = 0
    malformed_uri_count = 0
    bytes_processed = 0
    
    try:
        # Open file with appropriate method (gzipped or regular)
        if is_gzipped:
            file_handle = gzip.open(file_path, 'rt', encoding='utf-8')
        else:
            file_handle = open(file_path, 'r', encoding='utf-8')
        
        with file_handle as f:
            for line_num, line in enumerate(f, 1):
                original_line = line
                line = line.strip()
                bytes_processed += len(original_line.encode('utf-8'))
                
                # Skip empty lines and comments
                if not line or line.startswith('#'):
                    continue
                
                # Basic syntax validation - should end with '.'
                if not line.endswith('.'):
                    error_msg = f'Invalid {format_name} syntax at line {line_num}: missing terminating dot'
                    logger.error(error_msg)
                    return {
                        'success': False,
                        'error': error_msg,
                        'triple_count': triple_count,
                        'bytes_processed': bytes_processed
                    }
                
                # Remove the terminating dot and split into components
                line_content = line[:-1].strip()
                parts = line_content.split(None, expected_components - 1)  # Split into max expected parts
                
                if len(parts) != expected_components:
                    error_msg = f'Invalid {format_name} syntax at line {line_num}: expected {expected_components} components, got {len(parts)}'
                    logger.error(error_msg)
                    return {
                        'success': False,
                        'error': error_msg,
                        'triple_count': triple_count,
                        'bytes_processed': bytes_processed
                    }
                
                triple_count += 1
                
                # For N-Triples: subject, predicate, object
                # For N-Quads: subject, predicate, object, graph
                subject, predicate, obj = parts[0], parts[1], parts[2]
                
                # Check for blank nodes and malformed URIs
                components_to_check = [subject, predicate, obj]
                if format_type == RDFFormat.NQUADS:
                    graph = parts[3]
                    components_to_check.append(graph)
                    
                    # Check blank nodes in graph component
                    if graph.startswith('_:'):
                        blank_node_count += 1
                
                # Check for blank nodes in subject and object
                if subject.startswith('_:') or obj.startswith('_:'):
                    blank_node_count += 1
                
                # Check for malformed URIs in all components
                for component in components_to_check:
                    if component.startswith('<') and component.endswith('>'):
                        uri = component[1:-1]  # Remove < >
                        if ' ' in uri or '\n' in uri or '\t' in uri:
                            malformed_uri_count += 1
                
                # Log progress periodically
                if triple_count % progress_interval == 0:
                    progress_pct = (bytes_processed / file_size) * 100 if not is_gzipped else None
                    if progress_pct is not None:
                        logger.info(f"Processed {triple_count:,} {format_name.lower()}, {progress_pct:.1f}% of file ({bytes_processed / (1024*1024):.1f} MB)")
                    else:
                        logger.info(f"Processed {triple_count:,} {format_name.lower()} from compressed file")
                
                # Yield the parsed components
                if format_type == RDFFormat.NQUADS:
                    yield (subject, predicate, obj, graph)
                else:
                    yield (subject, predicate, obj)
        
        # Final logging
        progress_pct = 100.0 if not is_gzipped else None
        if progress_pct is not None:
            logger.info(f"Completed parsing {triple_count:,} {format_name.lower()}, 100% of file ({file_size_mb:.1f} MB)")
        else:
            logger.info(f"Completed parsing {triple_count:,} {format_name.lower()} from compressed file ({file_size_mb:.1f} MB)")
        
        validation_warnings = []
        if blank_node_count > 0:
            validation_warnings.append(f"Graph contains {blank_node_count} blank nodes")
        if malformed_uri_count > 0:
            validation_warnings.append(f"Found {malformed_uri_count} potentially malformed URIs")
        if is_gzipped:
            validation_warnings.append(f"Parsed gzipped {format_name} file")
        
        return {
            'success': True,
            'triple_count': triple_count,
            'blank_node_count': blank_node_count,
            'malformed_uri_count': malformed_uri_count,
            'namespaces': {},  # N-Triples/N-Quads don't have namespace prefixes
            'validation_warnings': validation_warnings,
            'bytes_processed': bytes_processed
        }
        
    except UnicodeDecodeError as e:
        logger.error(f"Unicode decode error in {format_name} file: {str(e)}")
        return {
            'success': False,
            'error': f'Unicode decode error: {str(e)}',
            'triple_count': triple_count,
            'bytes_processed': bytes_processed
        }
    except Exception as e:
        logger.error(f"Error parsing {format_name} file: {str(e)}")
        return {
            'success': False,
            'error': f'{format_name} parsing error: {str(e)}',
            'triple_count': triple_count,
            'bytes_processed': bytes_processed
        }


def _stream_parse_ntriples_nquads(file_path: str, format_type: RDFFormat) -> Dict[str, Any]:
    """Stream parse N-Triples or N-Quads file line by line, including gzipped variants.
    
    This function uses the generator-based parser internally but consumes all results
    for compatibility with the existing validation interface.
    """
    logger = logging.getLogger(__name__)
    
    try:
        # Use the generator to parse the file and collect statistics
        triple_count = 0
        blank_node_count = 0
        malformed_uri_count = 0
        
        # Process all triples/quads from the generator
        for triple_or_quad in stream_parse_ntriples_nquads_generator(file_path, format_type):
            # Count the processed items
            triple_count += 1
            
            # Additional validation could be done here if needed
            # For now, we just count the items as the generator handles validation
        
        # Since the generator handles all validation internally,
        # we need to run it again to get the final statistics
        # This is not ideal, but necessary for backward compatibility
        logger.info(f"Completed processing {triple_count} items from {file_path}")
        
        # Return a basic success result
        # Note: For full statistics, use the generator directly
        return {
            'success': True,
            'triple_count': triple_count,
            'blank_node_count': 0,  # Generator handles this internally
            'malformed_uri_count': 0,  # Generator handles this internally
            'namespaces': {},
            'validation_warnings': [f"Processed via generator-based streaming parser"]
        }
        
    except Exception as e:
        logger.error(f"Error in stream parsing: {str(e)}")
        return {
            'success': False,
            'error': f'Stream parsing error: {str(e)}'
        }


async def async_stream_parse_ntriples_nquads(file_path: str, format_type: RDFFormat, 
                                           progress_interval: int = 10000,
                                           batch_size: int = 1000) -> Dict[str, Any]:
    """Async wrapper for streaming N-Triples/N-Quads parsing with batched processing.
    
    Args:
        file_path: Path to the RDF file
        format_type: RDFFormat.NT or RDFFormat.NQUADS
        progress_interval: Log progress every N triples/quads
        batch_size: Process triples in batches to yield control
        
    Returns:
        Dictionary with parsing statistics and validation results
    """
    import asyncio
    
    logger = logging.getLogger(__name__)
    logger.info(f"Starting async streaming parse of {file_path}")
    
    triple_count = 0
    batch_count = 0
    
    try:
        # Use the generator to parse the file
        for triple_or_quad in stream_parse_ntriples_nquads_generator(file_path, format_type, progress_interval):
            triple_count += 1
            
            # Yield control periodically to allow other async operations
            if triple_count % batch_size == 0:
                batch_count += 1
                await asyncio.sleep(0)  # Yield control to event loop
                logger.debug(f"Processed batch {batch_count} ({triple_count} total items)")
        
        logger.info(f"Async parsing completed: {triple_count} items processed")
        
        return {
            'success': True,
            'triple_count': triple_count,
            'batch_count': batch_count,
            'namespaces': {},
            'validation_warnings': [f"Processed via async generator-based streaming parser"]
        }
        
    except Exception as e:
        logger.error(f"Error in async stream parsing: {str(e)}")
        return {
            'success': False,
            'error': f'Async stream parsing error: {str(e)}',
            'triple_count': triple_count
        }


def _memory_parse_with_rdflib(file_path: str, format_type: RDFFormat) -> Dict[str, Any]:
    """Parse RDF file using rdflib (loads entire file into memory)."""
    try:
        temp_graph = Graph()
        temp_graph.parse(file_path, format=format_type.value)
        
        triple_count = 0
        blank_node_count = 0
        malformed_uri_count = 0
        
        for subject, predicate, obj in temp_graph:
            triple_count += 1
            
            if isinstance(subject, BNode) or isinstance(obj, BNode):
                blank_node_count += 1
            
            for node in [subject, predicate, obj]:
                if isinstance(node, URIRef):
                    uri_str = str(node)
                    if ' ' in uri_str or '\n' in uri_str or '\t' in uri_str:
                        malformed_uri_count += 1
        
        namespaces = {prefix: str(namespace) for prefix, namespace in temp_graph.namespaces()}
        temp_graph = None  # Clear memory
        
        validation_warnings = []
        if blank_node_count > 0:
            validation_warnings.append(f"Graph contains {blank_node_count} blank nodes")
        if malformed_uri_count > 0:
            validation_warnings.append(f"Found {malformed_uri_count} potentially malformed URIs")
        
        return {
            'success': True,
            'triple_count': triple_count,
            'blank_node_count': blank_node_count,
            'malformed_uri_count': malformed_uri_count,
            'namespaces': namespaces,
            'validation_warnings': validation_warnings
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'rdflib parsing error: {str(e)}'
        }


def _stream_parse_rdf_xml(file_path: str) -> Dict[str, Any]:
    """Stream parse RDF/XML file."""
    try:
        # For RDF/XML, we need to use rdflib as manual parsing is complex
        temp_graph = Graph()
        temp_graph.parse(file_path, format='xml')
        
        triple_count = 0
        blank_node_count = 0
        malformed_uri_count = 0
        
        for subject, predicate, obj in temp_graph:
            triple_count += 1
            
            if isinstance(subject, BNode) or isinstance(obj, BNode):
                blank_node_count += 1
            
            for node in [subject, predicate, obj]:
                if isinstance(node, URIRef):
                    uri_str = str(node)
                    if ' ' in uri_str or '\n' in uri_str or '\t' in uri_str:
                        malformed_uri_count += 1
        
        namespaces = {prefix: str(namespace) for prefix, namespace in temp_graph.namespaces()}
        temp_graph = None
        
        return {
            'success': True,
            'triple_count': triple_count,
            'blank_node_count': blank_node_count,
            'malformed_uri_count': malformed_uri_count,
            'namespaces': namespaces
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'Error parsing RDF/XML file: {str(e)}'
        }


def _stream_parse_json_ld(file_path: str) -> Dict[str, Any]:
    """Stream parse JSON-LD file."""
    try:
        import json
        
        # First validate JSON structure
        with open(file_path, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
        
        # Use rdflib to parse JSON-LD
        temp_graph = Graph()
        temp_graph.parse(file_path, format='json-ld')
        
        triple_count = 0
        blank_node_count = 0
        malformed_uri_count = 0
        
        for subject, predicate, obj in temp_graph:
            triple_count += 1
            
            if isinstance(subject, BNode) or isinstance(obj, BNode):
                blank_node_count += 1
            
            for node in [subject, predicate, obj]:
                if isinstance(node, URIRef):
                    uri_str = str(node)
                    if ' ' in uri_str or '\n' in uri_str or '\t' in uri_str:
                        malformed_uri_count += 1
        
        namespaces = {prefix: str(namespace) for prefix, namespace in temp_graph.namespaces()}
        temp_graph = None
        
        return {
            'success': True,
            'triple_count': triple_count,
            'blank_node_count': blank_node_count,
            'malformed_uri_count': malformed_uri_count,
            'namespaces': namespaces
        }
        
    except json.JSONDecodeError as e:
        return {
            'success': False,
            'error': f'Invalid JSON syntax: {str(e)}'
        }
    except Exception as e:
        return {
            'success': False,
            'error': f'Error parsing JSON-LD file: {str(e)}'
        }


def _stream_parse_with_rdflib(file_path: str, format_type: RDFFormat) -> Dict[str, Any]:
    """Fallback parser using rdflib for other formats."""
    try:
        temp_graph = Graph()
        temp_graph.parse(file_path, format=format_type.value)
        
        triple_count = 0
        blank_node_count = 0
        malformed_uri_count = 0
        
        for subject, predicate, obj in temp_graph:
            triple_count += 1
            
            if isinstance(subject, BNode) or isinstance(obj, BNode):
                blank_node_count += 1
            
            for node in [subject, predicate, obj]:
                if isinstance(node, URIRef):
                    uri_str = str(node)
                    if ' ' in uri_str or '\n' in uri_str or '\t' in uri_str:
                        malformed_uri_count += 1
        
        namespaces = {prefix: str(namespace) for prefix, namespace in temp_graph.namespaces()}
        temp_graph = None
        
        return {
            'success': True,
            'triple_count': triple_count,
            'blank_node_count': blank_node_count,
            'malformed_uri_count': malformed_uri_count,
            'namespaces': namespaces
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'Error parsing {format_type.value} file: {str(e)}'
        }


def _perform_additional_validation(graph: Graph, warnings: List[str]) -> None:
    """Perform additional validation checks on the parsed RDF graph.
    
    Args:
        graph: Parsed RDF graph
        warnings: List to append warnings to
    """
    # Check for common issues
    blank_node_count = 0
    malformed_uri_count = 0
    
    for subject, predicate, obj in graph:
        # Count blank nodes
        if isinstance(subject, BNode) or isinstance(obj, BNode):
            blank_node_count += 1
        
        # Check for malformed URIs (basic check)
        for node in [subject, predicate, obj]:
            if isinstance(node, URIRef):
                uri_str = str(node)
                if ' ' in uri_str or '\n' in uri_str or '\t' in uri_str:
                    malformed_uri_count += 1
    
    if blank_node_count > 0:
        warnings.append(f"Graph contains {blank_node_count} blank nodes")
    
    if malformed_uri_count > 0:
        warnings.append(f"Found {malformed_uri_count} potentially malformed URIs")


def get_rdf_file_info(file_path: str) -> Dict[str, Any]:
    """Get basic information about an RDF file without full parsing.
    
    Args:
        file_path: Path to the RDF file
        
    Returns:
        Dictionary with file information
    """
    path = Path(file_path)
    
    if not path.exists():
        return {"error": "File does not exist"}
    
    file_size = path.stat().st_size
    detected_format = detect_rdf_format(file_path)
    
    return {
        "file_path": str(path.absolute()),
        "file_size_bytes": file_size,
        "file_size_mb": round(file_size / (1024 * 1024), 2),
        "detected_format": detected_format.value if detected_format else None,
        "last_modified": path.stat().st_mtime
    }
    