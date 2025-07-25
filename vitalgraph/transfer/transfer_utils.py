"""
VitalGraph Data Transfer Utilities

This module provides comprehensive data transfer capabilities for SPARQL LOAD operations,
including HTTP/HTTPS fetching, RDF parsing, streaming support, and FastAPI integration.
"""

import asyncio
import logging
from typing import Optional, Tuple, List, Dict, Any, AsyncGenerator
from urllib.parse import urlparse
from dataclasses import dataclass
from enum import Enum

import aiohttp
import aiofiles
from fastapi import HTTPException, status
from rdflib import Graph
from rdflib.exceptions import ParserError


class RDFFormat(Enum):
    """Supported RDF formats."""
    TURTLE = "turtle"
    RDF_XML = "xml"
    N_TRIPLES = "nt"
    JSON_LD = "json-ld"
    N3 = "n3"
    TRIG = "trig"
    NQUADS = "nquads"


@dataclass
class TransferConfig:
    """Configuration for data transfer operations."""
    max_file_size: int = 100 * 1024 * 1024  # 100MB default
    timeout_seconds: int = 30
    chunk_size: int = 8192
    allowed_schemes: List[str] = None
    allowed_domains: List[str] = None
    user_agent: str = "VitalGraph-SPARQL-LOAD/1.0"
    
    def __post_init__(self):
        if self.allowed_schemes is None:
            self.allowed_schemes = ['http', 'https']
        if self.allowed_domains is None:
            self.allowed_domains = []  # Empty means all domains allowed


@dataclass
class LoadResult:
    """Result of a LOAD operation."""
    success: bool
    source_uri: str
    target_graph: Optional[str]
    triples_loaded: int
    format_detected: str
    content_size: int
    elapsed_seconds: float
    error_message: Optional[str] = None


class URIValidator:
    """Validates URIs for security and safety."""
    
    def __init__(self, config: TransferConfig):
        self.config = config
        self.logger = logging.getLogger(__name__)
    
    def validate_uri(self, uri: str) -> bool:
        """
        Validate URI for security and safety.
        
        Args:
            uri: URI to validate
            
        Returns:
            bool: True if URI is safe to load from
        """
        try:
            parsed = urlparse(uri)
            
            # Check scheme
            if parsed.scheme not in self.config.allowed_schemes:
                self.logger.warning(f"Unsupported URI scheme: {parsed.scheme}")
                return False
            
            # Check hostname
            if not parsed.netloc:
                self.logger.warning(f"Invalid hostname in URI: {uri}")
                return False
            
            # Check domain allowlist if configured
            if self.config.allowed_domains:
                if not self._is_allowed_domain(parsed.netloc):
                    self.logger.warning(f"Domain not allowed: {parsed.netloc}")
                    return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error validating URI {uri}: {e}")
            return False
    
    def _is_allowed_domain(self, netloc: str) -> bool:
        """Check if domain is in allowlist."""
        for allowed in self.config.allowed_domains:
            if allowed.startswith('*.'):
                # Wildcard domain
                domain_suffix = allowed[2:]
                if netloc.endswith(domain_suffix):
                    return True
            elif netloc == allowed:
                return True
        return False


class RDFFormatDetector:
    """Detects RDF format from Content-Type headers and file extensions."""
    
    CONTENT_TYPE_MAP = {
        'text/turtle': RDFFormat.TURTLE,
        'application/x-turtle': RDFFormat.TURTLE,
        'application/rdf+xml': RDFFormat.RDF_XML,
        'text/rdf+xml': RDFFormat.RDF_XML,
        'application/n-triples': RDFFormat.N_TRIPLES,
        'text/plain': RDFFormat.N_TRIPLES,  # Often used for N-Triples
        'application/ld+json': RDFFormat.JSON_LD,
        'application/json': RDFFormat.JSON_LD,
        'text/n3': RDFFormat.N3,
        'application/trig': RDFFormat.TRIG,
        'application/n-quads': RDFFormat.NQUADS
    }
    
    EXTENSION_MAP = {
        '.ttl': RDFFormat.TURTLE,
        '.rdf': RDFFormat.RDF_XML,
        '.xml': RDFFormat.RDF_XML,
        '.nt': RDFFormat.N_TRIPLES,
        '.jsonld': RDFFormat.JSON_LD,
        '.json': RDFFormat.JSON_LD,
        '.n3': RDFFormat.N3,
        '.trig': RDFFormat.TRIG,
        '.nq': RDFFormat.NQUADS
    }
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def detect_format(self, content_type: str, uri: str) -> RDFFormat:
        """
        Detect RDF format from Content-Type header or file extension.
        
        Args:
            content_type: HTTP Content-Type header
            uri: Source URI (for extension detection)
            
        Returns:
            RDFFormat: Detected format
        """
        # Check Content-Type first
        content_type_lower = content_type.lower()
        for ct, fmt in self.CONTENT_TYPE_MAP.items():
            if ct in content_type_lower:
                return fmt
        
        # Fall back to file extension
        uri_lower = uri.lower()
        for ext, fmt in self.EXTENSION_MAP.items():
            if uri_lower.endswith(ext):
                return fmt
        
        # Default to Turtle (most common and flexible)
        self.logger.warning(f"Could not detect RDF format for {uri}, defaulting to Turtle")
        return RDFFormat.TURTLE


class HTTPFetcher:
    """Handles HTTP/HTTPS fetching with streaming support."""
    
    def __init__(self, config: TransferConfig):
        self.config = config
        self.logger = logging.getLogger(__name__)
    
    async def fetch_content(self, uri: str) -> Tuple[str, str, int]:
        """
        Fetch content from HTTP/HTTPS URI.
        
        Args:
            uri: URI to fetch from
            
        Returns:
            Tuple[str, str, int]: (content, content_type, content_size)
        """
        timeout = aiohttp.ClientTimeout(total=self.config.timeout_seconds)
        
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                headers = {
                    'Accept': 'text/turtle, application/rdf+xml, application/n-triples, application/ld+json, */*',
                    'User-Agent': self.config.user_agent
                }
                
                async with session.get(uri, headers=headers) as response:
                    response.raise_for_status()
                    
                    # Check content length
                    content_length = response.headers.get('content-length')
                    if content_length and int(content_length) > self.config.max_file_size:
                        raise HTTPException(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail=f"Content too large: {content_length} bytes (max: {self.config.max_file_size})"
                        )
                    
                    # Get content with size checking
                    content = await self._read_with_size_limit(response)
                    content_type = response.headers.get('content-type', '')
                    
                    self.logger.info(f"Fetched {len(content)} characters from {uri}")
                    return content, content_type, len(content)
                    
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=status.HTTP_408_REQUEST_TIMEOUT,
                detail=f"Timeout fetching content from {uri}"
            )
        except aiohttp.ClientError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"HTTP error fetching {uri}: {e}"
            )
    
    async def _read_with_size_limit(self, response: aiohttp.ClientResponse) -> str:
        """Read response content with size limit checking."""
        content_chunks = []
        total_size = 0
        
        async for chunk in response.content.iter_chunked(self.config.chunk_size):
            total_size += len(chunk)
            if total_size > self.config.max_file_size:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"Content too large: {total_size} bytes (max: {self.config.max_file_size})"
                )
            content_chunks.append(chunk)
        
        # Decode content
        content_bytes = b''.join(content_chunks)
        return content_bytes.decode('utf-8', errors='replace')
    
    async def stream_content(self, uri: str) -> AsyncGenerator[bytes, None]:
        """Stream content from URI in chunks."""
        timeout = aiohttp.ClientTimeout(total=self.config.timeout_seconds)
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            headers = {
                'Accept': 'text/turtle, application/rdf+xml, application/n-triples, application/ld+json, */*',
                'User-Agent': self.config.user_agent
            }
            
            async with session.get(uri, headers=headers) as response:
                response.raise_for_status()
                
                async for chunk in response.content.iter_chunked(self.config.chunk_size):
                    yield chunk


class RDFParser:
    """Parses RDF content into triples."""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def parse_content(self, content: str, rdf_format: RDFFormat, base_uri: str) -> List[Tuple[str, str, str]]:
        """
        Parse RDF content into triples.
        
        Args:
            content: RDF content as string
            rdf_format: RDF format
            base_uri: Base URI for relative URI resolution
            
        Returns:
            List[Tuple[str, str, str]]: List of (subject, predicate, object) triples
        """
        try:
            g = Graph()
            
            # Parse content with base URI
            g.parse(data=content, format=rdf_format.value, publicID=base_uri)
            
            # Convert to list of triples
            triples = [(str(s), str(p), str(o)) for s, p, o in g]
            
            self.logger.info(f"Parsed {len(triples)} triples from RDF content")
            return triples
            
        except ParserError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Error parsing RDF content as {rdf_format.value}: {e}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Unexpected error parsing RDF content: {e}"
            )
    
    def convert_triples_to_quads(self, triples: List[Tuple[str, str, str]], target_graph: Optional[str]) -> List[Tuple[str, str, str, str]]:
        """
        Convert triples to quads by adding graph context.
        
        Args:
            triples: List of (subject, predicate, object) triples
            target_graph: Target graph URI (None for default graph)
            
        Returns:
            List[Tuple[str, str, str, str]]: List of (subject, predicate, object, graph) quads
        """
        # Use global graph if no target graph specified
        graph_uri = target_graph if target_graph else "urn:___GLOBAL"
        
        quads = [(s, p, o, graph_uri) for s, p, o in triples]
        
        self.logger.info(f"Converted {len(triples)} triples to quads with graph: {graph_uri}")
        return quads


class SPARQLLoadQueryParser:
    """Parses SPARQL LOAD queries."""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def parse_load_query(self, sparql_update: str) -> Tuple[str, Optional[str]]:
        """
        Parse SPARQL LOAD query to extract source URI and target graph.
        
        Args:
            sparql_update: SPARQL LOAD query
            
        Returns:
            Tuple[str, Optional[str]]: (source_uri, target_graph) - target_graph is None for default graph
        """
        import re
        
        # Remove extra whitespace and normalize
        query = ' '.join(sparql_update.split())
        
        # Pattern for LOAD <uri> INTO GRAPH <graph>
        pattern_with_graph = r'LOAD\s+<([^>]+)>\s+INTO\s+GRAPH\s+<([^>]+)>'
        match = re.search(pattern_with_graph, query, re.IGNORECASE)
        
        if match:
            source_uri = match.group(1)
            target_graph = match.group(2)
            return source_uri, target_graph
        
        # Pattern for LOAD <uri> (default graph)
        pattern_default = r'LOAD\s+<([^>]+)>'
        match = re.search(pattern_default, query, re.IGNORECASE)
        
        if match:
            source_uri = match.group(1)
            target_graph = None  # Default graph
            return source_uri, target_graph
        
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid LOAD query syntax: {sparql_update}"
        )


class DataTransferManager:
    """Main class for managing data transfer operations."""
    
    def __init__(self, config: Optional[TransferConfig] = None):
        self.config = config or TransferConfig()
        self.logger = logging.getLogger(__name__)
        
        # Initialize components
        self.uri_validator = URIValidator(self.config)
        self.format_detector = RDFFormatDetector()
        self.http_fetcher = HTTPFetcher(self.config)
        self.rdf_parser = RDFParser()
        self.query_parser = SPARQLLoadQueryParser()
    
    async def execute_load_operation(self, sparql_update: str) -> LoadResult:
        """
        Execute a complete SPARQL LOAD operation.
        
        Args:
            sparql_update: SPARQL LOAD query
            
        Returns:
            LoadResult: Result of the load operation
        """
        import time
        start_time = time.time()
        
        try:
            self.logger.info(f"Executing LOAD operation: {sparql_update}")
            
            # Parse the LOAD query
            source_uri, target_graph = self.query_parser.parse_load_query(sparql_update)
            
            # Validate the source URI
            if not self.uri_validator.validate_uri(source_uri):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid or unsafe source URI: {source_uri}"
                )
            
            # Fetch RDF content
            content, content_type, content_size = await self.http_fetcher.fetch_content(source_uri)
            
            # Detect format
            rdf_format = self.format_detector.detect_format(content_type, source_uri)
            
            # Parse RDF content
            triples = self.rdf_parser.parse_content(content, rdf_format, source_uri)
            
            # Convert to quads
            quads = self.rdf_parser.convert_triples_to_quads(triples, target_graph)
            
            elapsed = time.time() - start_time
            
            return LoadResult(
                success=True,
                source_uri=source_uri,
                target_graph=target_graph,
                triples_loaded=len(triples),
                format_detected=rdf_format.value,
                content_size=content_size,
                elapsed_seconds=elapsed
            )
            
        except HTTPException:
            # Re-raise FastAPI exceptions
            raise
        except Exception as e:
            elapsed = time.time() - start_time
            self.logger.error(f"Error in LOAD operation: {e}")
            
            return LoadResult(
                success=False,
                source_uri=source_uri if 'source_uri' in locals() else "unknown",
                target_graph=target_graph if 'target_graph' in locals() else None,
                triples_loaded=0,
                format_detected="unknown",
                content_size=0,
                elapsed_seconds=elapsed,
                error_message=str(e)
            )
    
    def get_supported_formats(self) -> List[str]:
        """Get list of supported RDF formats."""
        return [fmt.value for fmt in RDFFormat]
    
    def update_config(self, **kwargs) -> None:
        """Update configuration parameters."""
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
            else:
                self.logger.warning(f"Unknown config parameter: {key}")
