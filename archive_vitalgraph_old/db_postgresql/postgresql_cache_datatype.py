"""
PostgreSQL Datatype Cache for VitalGraph

This module provides high-performance in-memory caching for datatype URI <-> BIGINT ID mappings.
The cache is used by both SPARQL query translation and CRUD operations to efficiently
resolve datatype information without repeated database queries.
"""

import logging
from typing import Dict, Optional, Any


class PostgreSQLCacheDatatype:
    """
    High-performance in-memory cache for datatype URI <-> BIGINT ID mappings.
    
    This cache provides fast bidirectional lookups between datatype URIs and their
    corresponding BIGINT IDs in the datatype table. It's designed to be populated
    at startup and maintained throughout the application lifecycle.
    """
    
    def __init__(self, cache_size: int = 1000):
        """
        Initialize datatype cache.
        
        Args:
            cache_size: Maximum number of datatypes to cache (should be sufficient for all standard datatypes)
        """
        self.logger = logging.getLogger(__name__)
        
        # Bidirectional mappings
        self.uri_to_id: Dict[str, int] = {}  # URI -> BIGINT ID
        self.id_to_uri: Dict[int, str] = {}  # BIGINT ID -> URI
        
        # Cache statistics
        self.cache_hits = 0
        self.cache_misses = 0
        self.max_size = cache_size
        
    def put(self, datatype_uri: str, datatype_id: int) -> None:
        """
        Add a datatype URI <-> ID mapping to the cache.
        
        Args:
            datatype_uri: The datatype URI (e.g., 'http://www.w3.org/2001/XMLSchema#string')
            datatype_id: The corresponding BIGINT ID from the datatype table
        """
        if len(self.uri_to_id) >= self.max_size:
            # Simple eviction: remove oldest entry (first in dict)
            oldest_uri = next(iter(self.uri_to_id))
            oldest_id = self.uri_to_id[oldest_uri]
            del self.uri_to_id[oldest_uri]
            del self.id_to_uri[oldest_id]
            
        self.uri_to_id[datatype_uri] = datatype_id
        self.id_to_uri[datatype_id] = datatype_uri
        
    def put_batch(self, mappings: Dict[str, int]) -> None:
        """
        Add multiple datatype URI <-> ID mappings to the cache.
        
        Args:
            mappings: Dictionary of URI -> ID mappings
        """
        for uri, datatype_id in mappings.items():
            self.put(uri, datatype_id)
            
    def get_id_by_uri(self, datatype_uri: str) -> Optional[int]:
        """
        Get datatype ID by URI.
        
        Args:
            datatype_uri: The datatype URI to look up
            
        Returns:
            The corresponding BIGINT ID, or None if not found
        """
        if datatype_uri in self.uri_to_id:
            self.cache_hits += 1
            return self.uri_to_id[datatype_uri]
        else:
            self.cache_misses += 1
            return None
            
    def get_uri_by_id(self, datatype_id: int) -> Optional[str]:
        """
        Get datatype URI by ID.
        
        Args:
            datatype_id: The BIGINT ID to look up
            
        Returns:
            The corresponding datatype URI, or None if not found
        """
        if datatype_id in self.id_to_uri:
            self.cache_hits += 1
            return self.id_to_uri[datatype_id]
        else:
            self.cache_misses += 1
            return None
            
    def contains_uri(self, datatype_uri: str) -> bool:
        """
        Check if a datatype URI is in the cache.
        
        Args:
            datatype_uri: The datatype URI to check
            
        Returns:
            True if the URI is cached, False otherwise
        """
        return datatype_uri in self.uri_to_id
        
    def contains_id(self, datatype_id: int) -> bool:
        """
        Check if a datatype ID is in the cache.
        
        Args:
            datatype_id: The BIGINT ID to check
            
        Returns:
            True if the ID is cached, False otherwise
        """
        return datatype_id in self.id_to_uri
        
    def clear(self) -> None:
        """
        Clear all cached datatype mappings.
        """
        self.uri_to_id.clear()
        self.id_to_uri.clear()
        self.cache_hits = 0
        self.cache_misses = 0
        
    def size(self) -> int:
        """
        Get the current number of cached datatype mappings.
        
        Returns:
            Number of cached mappings
        """
        return len(self.uri_to_id)
        
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get cache performance statistics.
        
        Returns:
            Dictionary with cache statistics
        """
        total_requests = self.cache_hits + self.cache_misses
        cache_hit_rate = (self.cache_hits / total_requests) if total_requests > 0 else 0.0
        
        return {
            'cache_size': self.size(),
            'cache_hits': self.cache_hits,
            'cache_misses': self.cache_misses,
            'cache_hit_rate': cache_hit_rate,
            'max_size': self.max_size
        }
        
    def log_statistics(self) -> None:
        """
        Log current cache performance statistics.
        """
        stats = self.get_statistics()
        self.logger.info(f"Datatype Cache Statistics: "
                        f"Size: {stats['cache_size']}/{stats['max_size']}, "
                        f"Hit rate: {stats['cache_hit_rate']:.2%}")
    
    def get_datatype_ids_batch(self, datatype_uris: list) -> Dict[str, Optional[int]]:
        """
        Get datatype IDs for a batch of URIs from cache only.
        
        This method only checks the cache and returns None for missing datatypes.
        The caller is responsible for handling unknown datatypes.
        
        Args:
            datatype_uris: List of datatype URIs to resolve
            
        Returns:
            Dictionary mapping datatype URIs to their BIGINT IDs (or None if not cached)
        """
        result = {}
        for uri in datatype_uris:
            result[uri] = self.get_id_by_uri(uri)
        return result
