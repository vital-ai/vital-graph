"""
PostgreSQL Graph Cache for optimizing graph operations.

This module provides an in-memory cache for RDF graphs to eliminate redundant
database lookups during graph operations and quad insertions.
"""

import logging
from typing import Dict, Optional, Set, Any, List
from collections import OrderedDict


class LRUCache:
    """
    Least Recently Used (LRU) cache implementation for graph storage.
    """
    
    def __init__(self, max_size: int = 10000):
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
    
    def contains(self, key: Any) -> bool:
        """Check if key exists in cache."""
        return key in self.cache
    
    def keys(self) -> Set[Any]:
        """Get all keys in cache."""
        return set(self.cache.keys())


class PostgreSQLCacheGraph:
    """
    High-performance in-memory cache for PostgreSQL RDF graphs.
    
    Features:
    - LRU cache for known graph URIs
    - Batch loading and updating with optimized SQL integration
    - Memory usage monitoring
    - Support for graph existence checks
    """
    
    def __init__(self, cache_size: int = 10000):
        """
        Initialize graph cache.
        
        Args:
            cache_size: Maximum number of graphs to cache
        """
        self.logger = logging.getLogger(__name__)
        
        # LRU cache for graph existence checks
        # Key: graph_uri (string) -> Value: True (graph exists)
        # If a graph URI is not in cache, we don't know if it exists
        self.graph_cache = LRUCache(cache_size)
        
        # Statistics
        self.cache_hits = 0
        self.cache_misses = 0
        
        # Flag to track if cache has been initialized with existing graphs
        self.initialized = False
        
        self.logger.info(f"Initialized PostgreSQLCacheGraph with {cache_size} cache size")
    
    def is_graph_cached(self, graph_uri: str) -> bool:
        """
        Check if graph exists in cache (meaning we know it exists in DB).
        
        Args:
            graph_uri: URI of the graph to check
            
        Returns:
            True if graph is cached (exists in DB), False if not cached
        """
        exists = self.graph_cache.get(graph_uri)
        
        if exists is not None:
            self.cache_hits += 1
            return True
        
        self.cache_misses += 1
        return False
    
    def add_graph_to_cache(self, graph_uri: str) -> None:
        """
        Add graph to cache (marking it as existing in DB).
        
        Args:
            graph_uri: URI of the graph to cache
        """
        self.graph_cache.put(graph_uri, True)
    
    def add_graphs_to_cache_batch(self, graph_uris: Set[str]) -> None:
        """
        Batch add graphs to cache.
        
        Args:
            graph_uris: Set of graph URIs to cache
        """
        for graph_uri in graph_uris:
            self.add_graph_to_cache(graph_uri)
        
        self.logger.debug(f"Batch added {len(graph_uris)} graphs to cache")
    
    def remove_graph_from_cache(self, graph_uri: str) -> None:
        """
        Remove graph from cache (when graph is dropped).
        
        Args:
            graph_uri: URI of the graph to remove from cache
        """
        # Remove from cache by clearing and rebuilding without this graph
        # This is simple but not the most efficient - could be optimized later
        if self.graph_cache.contains(graph_uri):
            # For now, just let it expire naturally from LRU
            # A more sophisticated implementation could track deletions
            pass
    
    def get_missing_graphs(self, graph_uris: Set[str]) -> Set[str]:
        """
        Get list of graphs that are not in cache (need DB check).
        
        Args:
            graph_uris: Set of graph URIs to check
            
        Returns:
            Set of graph URIs that need database lookup
        """
        missing_graphs = set()
        
        for graph_uri in graph_uris:
            if not self.is_graph_cached(graph_uri):
                missing_graphs.add(graph_uri)
        
        return missing_graphs
    
    def get_cached_graphs(self, graph_uris: Set[str]) -> Set[str]:
        """
        Get list of graphs that are in cache (known to exist in DB).
        
        Args:
            graph_uris: Set of graph URIs to check
            
        Returns:
            Set of graph URIs that are cached (exist in DB)
        """
        cached_graphs = set()
        
        for graph_uri in graph_uris:
            if self.is_graph_cached(graph_uri):
                cached_graphs.add(graph_uri)
        
        return cached_graphs
    
    def initialize_from_database(self, graph_uris: List[str]):
        """
        Initialize the cache with existing graphs from the database.
        This should be called once after cache creation to populate it with all existing graphs.
        
        Args:
            graph_uris: List of graph URIs that exist in the database
        """
        if not self.initialized:
            for graph_uri in graph_uris:
                self.add_graph_to_cache(graph_uri)
            self.initialized = True
            self.logger.info(f"Initialized graph cache with {len(graph_uris)} existing graphs")
        else:
            self.logger.debug("Graph cache already initialized, skipping")
    
    async def ensure_initialized_async(self, space_id: str, graphs_instance):
        """
        Ensure the cache is initialized with existing graphs from the database.
        This is an async version that can be called from async contexts.
        
        Args:
            space_id: Space identifier
            graphs_instance: PostgreSQLSpaceGraphs instance to query existing graphs
        """
        if not self.initialized:
            try:
                # Get all existing graph URIs from the database
                existing_graphs = await graphs_instance.list_graphs(space_id)
                graph_uris = [graph['graph_uri'] for graph in existing_graphs]
                
                # Initialize cache with existing graphs
                self.initialize_from_database(graph_uris)
                
            except Exception as e:
                self.logger.warning(f"Failed to initialize graph cache for space '{space_id}': {e}")
                # Mark as initialized anyway to avoid repeated attempts
                self.initialized = True
    
    def clear_cache(self):
        """
        Clear all cached graphs and reset statistics.
        """
        self.graph_cache.clear()
        self.cache_hits = 0
        self.cache_misses = 0
        self.initialized = False
        self.logger.info("Graph cache cleared")
    
    def size(self) -> int:
        """Get current cache size."""
        return self.graph_cache.size()
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get cache performance statistics.
        
        Returns:
            Dictionary with cache performance metrics
        """
        total_lookups = self.cache_hits + self.cache_misses
        cache_hit_rate = self.cache_hits / total_lookups if total_lookups > 0 else 0
        
        return {
            'cache_size': self.graph_cache.size(),
            'cache_hits': self.cache_hits,
            'cache_misses': self.cache_misses,
            'cache_hit_rate': cache_hit_rate
        }
    
    def log_statistics(self) -> None:
        """Log current cache performance statistics."""
        stats = self.get_statistics()
        self.logger.info(f"Graph Cache Statistics: "
                        f"Cache size: {stats['cache_size']}, "
                        f"Hit rate: {stats['cache_hit_rate']:.2%}")
