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


class BloomFilter:
    """
    Simple Bloom filter implementation for fast negative lookups.
    
    This helps avoid cache misses for terms that definitely don't exist.
    """
    
    def __init__(self, capacity: int = 1000000, error_rate: float = 0.1):
        """
        Initialize Bloom filter.
        
        Args:
            capacity: Expected number of elements
            error_rate: Desired false positive rate
        """
        import math
        
        # Calculate optimal parameters
        self.capacity = capacity
        self.error_rate = error_rate
        
        # Calculate bit array size
        self.bit_size = int(-capacity * math.log(error_rate) / (math.log(2) ** 2))
        
        # Calculate number of hash functions
        self.hash_count = int(self.bit_size * math.log(2) / capacity)
        
        # Initialize bit array
        self.bit_array = [False] * self.bit_size
        self.element_count = 0
        
    def _hash(self, item: str, seed: int) -> int:
        """Simple hash function with seed."""
        hash_value = hash(f"{item}_{seed}")
        return abs(hash_value) % self.bit_size
        
    def add(self, item: str) -> None:
        """Add item to Bloom filter."""
        for i in range(self.hash_count):
            index = self._hash(item, i)
            self.bit_array[index] = True
        self.element_count += 1
        
    def might_contain(self, item: str) -> bool:
        """Check if item might be in the set (no false negatives)."""
        for i in range(self.hash_count):
            index = self._hash(item, i)
            if not self.bit_array[index]:
                return False
        return True
        
    def clear(self) -> None:
        """Clear all items from Bloom filter."""
        self.bit_array = [False] * self.bit_size
        self.element_count = 0


class PostgreSQLTermCache:
    """
    High-performance in-memory cache for PostgreSQL RDF terms.
    
    Features:
    - LRU cache for known term IDs
    - Bloom filter for fast negative lookups
    - Batch loading and updating
    - Memory usage monitoring
    """
    
    def __init__(self, 
                 cache_size: int = 100000,
                 bloom_capacity: int = 1000000,
                 bloom_error_rate: float = 0.1):
        """
        Initialize term cache.
        
        Args:
            cache_size: Maximum number of terms to cache
            bloom_capacity: Expected number of unique terms
            bloom_error_rate: Bloom filter false positive rate
        """
        self.logger = logging.getLogger(__name__)
        
        # LRU cache for term_id lookups
        # Key: (term_text, term_type, lang, datatype_id)
        # Value: term_id
        self.term_id_cache = LRUCache(cache_size)
        
        # Bloom filter for negative lookups
        self.bloom_filter = BloomFilter(bloom_capacity, bloom_error_rate)
        
        # Statistics
        self.cache_hits = 0
        self.cache_misses = 0
        self.bloom_hits = 0  # Successful negative lookups
        self.bloom_misses = 0  # False positives
        
        self.logger.info(f"Initialized PostgreSQLTermCache with {cache_size} cache size, "
                        f"{bloom_capacity} bloom capacity, {bloom_error_rate} error rate")
    
    def get_term_id(self, term_key: Tuple[str, str, Optional[str], Optional[int]]) -> Optional[int]:
        """
        Get term ID from cache.
        
        Args:
            term_key: (term_text, term_type, lang, datatype_id)
            
        Returns:
            term_id if found in cache, None otherwise
        """
        term_id = self.term_id_cache.get(term_key)
        if term_id is not None:
            self.cache_hits += 1
            return term_id
        
        self.cache_misses += 1
        return None
    
    def put_term_id(self, term_key: Tuple[str, str, Optional[str], Optional[int]], term_id: int) -> None:
        """
        Store term ID in cache.
        
        Args:
            term_key: (term_text, term_type, lang, datatype_id)
            term_id: Database term ID
        """
        self.term_id_cache.put(term_key, term_id)
        
        # Add to Bloom filter for future negative lookups
        bloom_key = f"{term_key[0]}|{term_key[1]}|{term_key[2]}|{term_key[3]}"
        self.bloom_filter.add(bloom_key)
    
    def might_exist(self, term_key: Tuple[str, str, Optional[str], Optional[int]]) -> bool:
        """
        Check if term might exist (fast negative lookup).
        
        Args:
            term_key: (term_text, term_type, lang, datatype_id)
            
        Returns:
            True if term might exist, False if definitely doesn't exist
        """
        bloom_key = f"{term_key[0]}|{term_key[1]}|{term_key[2]}|{term_key[3]}"
        might_exist = self.bloom_filter.might_contain(bloom_key)
        
        if not might_exist:
            self.bloom_hits += 1
            return False
        
        self.bloom_misses += 1
        return True
    
    def batch_update(self, term_mappings: Dict[Tuple[str, str, Optional[str], Optional[int]], int]) -> None:
        """
        Batch update cache with multiple term mappings.
        
        Args:
            term_mappings: Dictionary of term_key -> term_id mappings
        """
        for term_key, term_id in term_mappings.items():
            self.put_term_id(term_key, term_id)
        
        self.logger.debug(f"Batch updated cache with {len(term_mappings)} term mappings")
    
    def get_missing_terms(self, term_keys: Set[Tuple[str, str, Optional[str], Optional[int]]]) -> Set[Tuple[str, str, Optional[str], Optional[int]]]:
        """
        Get list of terms that are not in cache and might not exist in DB.
        
        Args:
            term_keys: Set of term keys to check
            
        Returns:
            Set of term keys that need database lookup
        """
        missing_terms = set()
        
        for term_key in term_keys:
            # First check cache
            if self.get_term_id(term_key) is not None:
                continue
            
            # Then check Bloom filter
            if self.might_exist(term_key):
                missing_terms.add(term_key)
        
        return missing_terms
    
    def clear(self) -> None:
        """Clear all cached data."""
        self.term_id_cache.clear()
        self.bloom_filter.clear()
        
        # Reset statistics
        self.cache_hits = 0
        self.cache_misses = 0
        self.bloom_hits = 0
        self.bloom_misses = 0
        
        self.logger.info("Cleared all cached data")
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get cache performance statistics.
        
        Returns:
            Dictionary with cache performance metrics
        """
        total_lookups = self.cache_hits + self.cache_misses
        cache_hit_rate = self.cache_hits / total_lookups if total_lookups > 0 else 0
        
        total_bloom_checks = self.bloom_hits + self.bloom_misses
        bloom_hit_rate = self.bloom_hits / total_bloom_checks if total_bloom_checks > 0 else 0
        
        return {
            'cache_size': self.term_id_cache.size(),
            'cache_hits': self.cache_hits,
            'cache_misses': self.cache_misses,
            'cache_hit_rate': cache_hit_rate,
            'bloom_hits': self.bloom_hits,
            'bloom_misses': self.bloom_misses,
            'bloom_hit_rate': bloom_hit_rate,
            'bloom_elements': self.bloom_filter.element_count
        }
    
    def log_statistics(self) -> None:
        """Log current cache performance statistics."""
        stats = self.get_statistics()
        self.logger.info(f"Term Cache Statistics: "
                        f"Cache size: {stats['cache_size']}, "
                        f"Hit rate: {stats['cache_hit_rate']:.2%}, "
                        f"Bloom hit rate: {stats['bloom_hit_rate']:.2%}")
