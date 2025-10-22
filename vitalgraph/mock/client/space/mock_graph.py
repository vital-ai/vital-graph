"""Mock Graph

Mock implementation of a VitalGraph graph for testing.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
import pyoxigraph as px


class MockGraph:
    """
    Mock implementation of a VitalGraph graph.
    
    Represents a named graph within a mock space with
    basic graph properties and metadata.
    """
    
    def __init__(self, graph_id: str, graph_uri: str, space_id: int, 
                 name: Optional[str] = None, **kwargs):
        """
        Initialize a mock graph.
        
        Args:
            graph_id: Unique graph identifier
            graph_uri: Graph URI
            space_id: Parent space identifier
            name: Optional human-readable name
            **kwargs: Additional graph properties
        """
        self.graph_id = graph_id
        self.graph_uri = graph_uri
        self.space_id = space_id
        self.name = name or graph_id
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.is_active = True
        self.properties = kwargs
        
        # Graph statistics
        self.triple_count = 0
        self.last_modified = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert graph to dictionary representation.
        
        Returns:
            Dictionary containing graph data
        """
        return {
            "graph_id": self.graph_id,
            "graph_uri": self.graph_uri,
            "space_id": self.space_id,
            "name": self.name,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_modified": self.last_modified.isoformat(),
            "is_active": self.is_active,
            "triple_count": self.triple_count,
            **self.properties
        }
    
    def update(self, **kwargs) -> None:
        """
        Update graph properties.
        
        Args:
            **kwargs: Properties to update
        """
        for key, value in kwargs.items():
            if key in ["name", "graph_uri", "is_active"]:
                setattr(self, key, value)
            else:
                self.properties[key] = value
        
        self.updated_at = datetime.now()
    
    def update_stats(self, triple_count: int) -> None:
        """
        Update graph statistics.
        
        Args:
            triple_count: Current number of triples in the graph
        """
        self.triple_count = triple_count
        self.last_modified = datetime.now()
        self.updated_at = datetime.now()
    
    def get_named_graph(self) -> px.NamedNode:
        """
        Get pyoxigraph NamedNode for this graph.
        
        Returns:
            NamedNode representing this graph
        """
        return px.NamedNode(self.graph_uri)
    
    def __str__(self) -> str:
        """String representation of the graph."""
        return f"MockGraph(id='{self.graph_id}', uri='{self.graph_uri}', space={self.space_id})"
    
    def __repr__(self) -> str:
        """Detailed string representation of the graph."""
        return self.__str__()