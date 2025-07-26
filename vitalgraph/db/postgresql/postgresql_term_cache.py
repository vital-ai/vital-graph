"""
PostgreSQL Term Cache for optimizing batch RDF operations.

This module provides an in-memory cache for RDF terms to eliminate redundant
database lookups during bulk import operations.
"""

import logging
from typing import Dict, Optional, Set, Tuple, Any
from collections import OrderedDict


class LRUCache:
    """
    Least Recently Used (LRU) cache implementation for term storage.
    """
    
    def __init__(self, max_size: int = 100000):
        self.max_size = max_size
        self.cache = OrderedDict()
        
    def get(self, key: Any) -> Optional[Any]:
        """Get value from cache, moving it to end (most recent)."""
        if key in self.cache:
            # Move to end (most recent)
            value = self.cache.pop(key)
            self.cache[key] = value
            return value
        return None
        
    def put(self, key: Any, value: Any) -> None:
        """Put value in cache, evicting oldest if necessary."""
        if key in self.cache:
            # Update existing key
            self.cache.pop(key)
        elif len(self.cache) >= self.max_size:
            # Remove oldest item
            self.cache.popitem(last=False)
        
        self.cache[key] = value
        
    def clear(self) -> None:
        """Clear all cached items."""
        self.cache.clear()
        
    def size(self) -> int:
        """Get current cache size."""
        return len(self.cache)


class PostgreSQLTermCache:
    """
    High-performance in-memory cache for PostgreSQL RDF terms with UUID support.
    
    Features:
    - LRU cache for known term UUIDs
    - Batch loading and updating with optimized SQL integration
    - Memory usage monitoring
    - Support for both (term_text, term_type) and full term key formats
    """
    
    def __init__(self, cache_size: int = 100000):
        """
        Initialize term cache.
        
        Args:
            cache_size: Maximum number of terms to cache
        """
        self.logger = logging.getLogger(__name__)
        
        # LRU cache for term_uuid lookups - supports both formats:
        # Key: (term_text, term_type) -> term_uuid (for SPARQL queries)
        # Key: (term_text, term_type, lang, datatype_id) -> term_uuid (for full term info)
        # Value: term_uuid (string)
        self.term_uuid_cache = LRUCache(cache_size)
        
        # Statistics
        self.cache_hits = 0
        self.cache_misses = 0
        
        self.logger.info(f"Initialized PostgreSQLTermCache with {cache_size} cache size")
    
    def get_term_uuid(self, term_key) -> Optional[str]:
        """
        Get term UUID from cache.
        
        Args:
            term_key: Either (term_text, term_type) or (term_text, term_type, lang, datatype_id)
            
        Returns:
            term_uuid if found in cache, None otherwise
        """
        term_uuid = self.term_uuid_cache.get(term_key)
        
        if term_uuid is not None:
            self.cache_hits += 1
            return term_uuid
        
        self.cache_misses += 1
        return None
    
    def put_term_uuid(self, term_key, term_uuid: str) -> None:
        """
        Store term UUID in cache.
        
        Args:
            term_key: Either (term_text, term_type) or (term_text, term_type, lang, datatype_id)
            term_uuid: Database term UUID
        """
        self.term_uuid_cache.put(term_key, term_uuid)
    

    
    def put_batch(self, term_mappings: Dict) -> None:
        """
        Batch update cache with multiple term UUID mappings.
        
        Args:
            term_mappings: Dictionary of term_key -> term_uuid mappings
                          Keys can be either (term_text, term_type) or (term_text, term_type, lang, datatype_id)
        """
        for term_key, term_uuid in term_mappings.items():
            self.put_term_uuid(term_key, term_uuid)
        
        self.logger.debug(f"Batch updated cache with {len(term_mappings)} term UUID mappings")
    
    def get_batch(self, term_keys) -> Dict:
        """
        Batch get term UUIDs from cache.
        
        Args:
            term_keys: List of term keys to lookup
            
        Returns:
            Dictionary of term_key -> term_uuid mappings for found terms
        """
        results = {}
        for term_key in term_keys:
            term_uuid = self.get_term_uuid(term_key)
            if term_uuid is not None:
                results[term_key] = term_uuid
        
        return results
    
    def get_missing_terms(self, term_keys) -> Set:
        """
        Get list of terms that are not in cache.
        
        Args:
            term_keys: Set of term keys to check (either format supported)
            
        Returns:
            Set of term keys that need database lookup
        """
        missing_terms = set()
        
        for term_key in term_keys:
            # Check cache - if not found, it needs database lookup
            if self.get_term_uuid(term_key) is None:
                missing_terms.add(term_key)
        
        return missing_terms
    
    def clear(self) -> None:
        """Clear all cached data."""
        self.term_uuid_cache.clear()
        
        # Reset statistics
        self.cache_hits = 0
        self.cache_misses = 0
        
        self.logger.info("Cleared all cached data")
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get cache performance statistics.
        
        Returns:
            Dictionary with cache performance metrics
        """
        total_lookups = self.cache_hits + self.cache_misses
        cache_hit_rate = self.cache_hits / total_lookups if total_lookups > 0 else 0
        
        return {
            'cache_size': self.term_uuid_cache.size(),
            'cache_hits': self.cache_hits,
            'cache_misses': self.cache_misses,
            'cache_hit_rate': cache_hit_rate
        }
    
    def log_statistics(self) -> None:
        """Log current cache performance statistics."""
        stats = self.get_statistics()
        self.logger.info(f"Term Cache Statistics: "
                        f"Cache size: {stats['cache_size']}, "
                        f"Hit rate: {stats['cache_hit_rate']:.2%}")
