# PyOxigraph In-Memory Store Documentation

## Overview

PyOxigraph is a Python binding for the Oxigraph RDF database, providing fast in-memory and on-disk RDF storage with full SPARQL 1.1 support. This document outlines the key operations for working with quads (RDF triples with named graphs) in the in-memory store.

## Store Creation

### In-Memory Store
```python
from pyoxigraph import Store
store = Store()  # Creates an in-memory store
```

### Disk-Based Store
```python
store = Store("/path/to/database")  # Creates persistent disk-based store
```

## RDF Model Classes

### Core RDF Terms

#### NamedNode (IRI)
```python
from pyoxigraph import NamedNode
node = NamedNode('http://example.com/resource')
print(node.value)  # 'http://example.com/resource'
```

#### Literal
```python
from pyoxigraph import Literal, NamedNode

# String literal
lit1 = Literal('example')

# Typed literal
lit2 = Literal('42', datatype=NamedNode('http://www.w3.org/2001/XMLSchema#integer'))

# Language-tagged literal
lit3 = Literal('hello', language='en')

# Python types are automatically converted
lit4 = Literal(42)      # integer
lit5 = Literal(3.14)    # float
lit6 = Literal(True)    # boolean
```

#### BlankNode
```python
from pyoxigraph import BlankNode

# Auto-generated identifier
blank1 = BlankNode()

# Specific identifier
blank2 = BlankNode('node1')
print(blank2.value)  # 'node1'
```

### Triple
```python
from pyoxigraph import Triple, NamedNode, Literal

triple = Triple(
    subject=NamedNode('http://example.com/subject'),
    predicate=NamedNode('http://example.com/predicate'),
    object=Literal('value')
)

# Destructuring
s, p, o = triple
```

### Quad (Triple + Named Graph)
```python
from pyoxigraph import Quad, NamedNode, Literal, DefaultGraph

# Quad in named graph
quad1 = Quad(
    subject=NamedNode('http://example.com/subject'),
    predicate=NamedNode('http://example.com/predicate'),
    object=Literal('value'),
    graph_name=NamedNode('http://example.com/graph')
)

# Quad in default graph
quad2 = Quad(
    subject=NamedNode('http://example.com/subject'),
    predicate=NamedNode('http://example.com/predicate'),
    object=Literal('value'),
    graph_name=DefaultGraph()  # or omit graph_name parameter
)

# Destructuring
s, p, o, g = quad1
```

## Quad Operations

### Adding Quads

#### Single Quad
```python
from pyoxigraph import Store, Quad, NamedNode, Literal

store = Store()
quad = Quad(
    NamedNode('http://example.com/subject'),
    NamedNode('http://example.com/predicate'), 
    Literal('value'),
    NamedNode('http://example.com/graph')
)

store.add(quad)
```

#### Multiple Quads (Transactional)
```python
quads = [
    Quad(NamedNode('http://example.com/s1'), NamedNode('http://example.com/p'), Literal('v1')),
    Quad(NamedNode('http://example.com/s2'), NamedNode('http://example.com/p'), Literal('v2'))
]

# All quads added atomically - either all succeed or none are added
store.extend(quads)
```

#### Bulk Loading (Memory Efficient)
```python
# For very large datasets - doesn't load all into memory at once
store.bulk_extend(quad_iterator)
```

### Removing Quads

#### Single Quad
```python
store.remove(quad)
```

#### Clear Entire Store
```python
store.clear()
```

#### Clear Specific Graph
```python
from pyoxigraph import NamedNode, DefaultGraph

# Clear named graph (keeps graph, removes all triples)
store.clear_graph(NamedNode('http://example.com/graph'))

# Clear default graph
store.clear_graph(DefaultGraph())
```

#### Remove Entire Graph
```python
# Remove graph completely (graph and all triples)
store.remove_graph(NamedNode('http://example.com/graph'))
```

### Querying Quads

#### Pattern-Based Quad Matching
```python
# Find all quads (None matches anything)
all_quads = list(store.quads_for_pattern(None, None, None, None))

# Find quads with specific subject
subject_quads = list(store.quads_for_pattern(
    subject=NamedNode('http://example.com/subject'),
    predicate=None,
    object=None,
    graph_name=None
))

# Find quads in specific graph
graph_quads = list(store.quads_for_pattern(
    subject=None,
    predicate=None, 
    object=None,
    graph_name=NamedNode('http://example.com/graph')
))

# Find quads in default graph only
default_quads = list(store.quads_for_pattern(
    subject=None,
    predicate=None,
    object=None,
    graph_name=DefaultGraph()
))

# Complex pattern matching
specific_quads = list(store.quads_for_pattern(
    subject=NamedNode('http://example.com/subject'),
    predicate=NamedNode('http://example.com/predicate'),
    object=None,  # Any object
    graph_name=NamedNode('http://example.com/graph')
))
```

#### Iteration Over All Quads
```python
# Iterate over all quads in store
for quad in store:
    print(f"Subject: {quad.subject}")
    print(f"Predicate: {quad.predicate}")
    print(f"Object: {quad.object}")
    print(f"Graph: {quad.graph_name}")
```

### SPARQL Queries

#### SELECT Queries
```python
query = """
SELECT ?subject ?object WHERE {
    GRAPH <http://example.com/graph> {
        ?subject <http://example.com/predicate> ?object
    }
}
"""

results = store.query(query)
for solution in results:
    print(f"Subject: {solution['subject']}")
    print(f"Object: {solution['object']}")
```

#### CONSTRUCT Queries
```python
query = """
CONSTRUCT {
    ?s <http://example.com/newPredicate> ?o
} WHERE {
    ?s <http://example.com/predicate> ?o
}
"""

triples = list(store.query(query))
for triple in triples:
    print(triple)
```

#### ASK Queries
```python
query = """
ASK {
    <http://example.com/subject> <http://example.com/predicate> ?o
}
"""

exists = bool(store.query(query))
print(f"Pattern exists: {exists}")
```

#### Query with Parameters
```python
query = """
SELECT ?object WHERE {
    ?subject <http://example.com/predicate> ?object
}
"""

results = store.query(
    query,
    base_iri="http://example.com/",
    prefixes={"ex": "http://example.com/"},
    default_graph=[NamedNode("http://example.com/graph")],
    use_default_graph_as_union=False
)
```

### SPARQL Updates

#### INSERT DATA
```python
update = """
INSERT DATA {
    GRAPH <http://example.com/graph> {
        <http://example.com/subject> <http://example.com/predicate> "new value"
    }
}
"""

store.update(update)
```

#### DELETE DATA
```python
update = """
DELETE DATA {
    GRAPH <http://example.com/graph> {
        <http://example.com/subject> <http://example.com/predicate> "old value"
    }
}
"""

store.update(update)
```

#### DELETE WHERE
```python
update = """
DELETE WHERE {
    <http://example.com/subject> ?predicate ?object
}
"""

store.update(update)
```

## Graph Management

### Named Graph Operations

#### List All Named Graphs
```python
graphs = list(store.named_graphs())
for graph in graphs:
    print(f"Graph: {graph}")
```

#### Check if Graph Exists
```python
graph_exists = store.contains_named_graph(NamedNode('http://example.com/graph'))
```

#### Add Empty Named Graph
```python
store.add_graph(NamedNode('http://example.com/new_graph'))
```

## Data Loading and Serialization

### Load RDF Data
```python
from pyoxigraph import RdfFormat

# Load from string
turtle_data = """
@prefix ex: <http://example.com/> .
ex:subject ex:predicate "value" .
"""

store.load(
    input=turtle_data,
    format=RdfFormat.TURTLE,
    base_iri="http://example.com/",
    to_graph=NamedNode("http://example.com/graph")
)

# Load from file
store.load(
    path="/path/to/file.ttl",
    format=RdfFormat.TURTLE,
    to_graph=NamedNode("http://example.com/graph")
)
```

### Supported Formats
- **JSON-LD 1.0** (`RdfFormat.JSON_LD`)
- **N-Triples** (`RdfFormat.N_TRIPLES`)
- **N-Quads** (`RdfFormat.N_QUADS`)
- **Turtle** (`RdfFormat.TURTLE`)
- **TriG** (`RdfFormat.TRIG`)
- **N3** (`RdfFormat.N3`)
- **RDF/XML** (`RdfFormat.RDF_XML`)

### Export/Dump Data
```python
# Dump to bytes
data = store.dump(format=RdfFormat.TURTLE)

# Dump specific graph
data = store.dump(
    format=RdfFormat.TURTLE,
    from_graph=NamedNode("http://example.com/graph")
)

# Dump to file
store.dump(
    output="/path/to/output.ttl",
    format=RdfFormat.TURTLE,
    prefixes={"ex": "http://example.com/"}
)
```

## Performance Considerations

### Bulk Operations
- Use `bulk_extend()` for large datasets to avoid memory issues
- Use `extend()` for transactional insertion of moderate datasets
- Use `bulk_load()` for loading large files efficiently

### Optimization
```python
# Optimize store after bulk operations
store.optimize()

# Flush buffers to ensure writes are persisted (disk stores)
store.flush()
```

### Memory Management
- In-memory stores are automatically garbage collected
- For large datasets, consider using disk-based stores
- Use pattern matching instead of loading all quads when possible

## Error Handling

### Common Exceptions
- **ValueError**: Invalid IRI, language tag, or format
- **SyntaxError**: Invalid SPARQL query or RDF syntax
- **OSError**: File system or database errors

### Example Error Handling
```python
try:
    store.add(quad)
except ValueError as e:
    print(f"Invalid data: {e}")
except OSError as e:
    print(f"Storage error: {e}")

try:
    results = store.query("INVALID SPARQL")
except SyntaxError as e:
    print(f"Query syntax error: {e}")
```

## Best Practices for Mock Implementation

### 1. Store Management
```python
class MockSpace:
    def __init__(self, space_id: str):
        self.space_id = space_id
        self.store = Store()  # In-memory store per space
        self.graphs = {}  # Track graph metadata
    
    def add_quad(self, quad: Quad):
        self.store.add(quad)
        # Update graph statistics
        graph_name = quad.graph_name
        if graph_name not in self.graphs:
            self.graphs[graph_name] = {"triple_count": 0}
        self.graphs[graph_name]["triple_count"] += 1
```

### 2. SPARQL Query Execution
```python
def execute_sparql(self, query: str, **kwargs):
    try:
        return self.store.query(query, **kwargs)
    except SyntaxError as e:
        return {"error": f"Invalid SPARQL: {e}"}
    except OSError as e:
        return {"error": f"Query execution failed: {e}"}
```

### 3. Graph Statistics
```python
def get_graph_stats(self, graph_uri: str):
    graph_name = NamedNode(graph_uri)
    quad_count = len(list(self.store.quads_for_pattern(
        None, None, None, graph_name
    )))
    return {
        "graph_uri": graph_uri,
        "triple_count": quad_count,
        "exists": self.store.contains_named_graph(graph_name)
    }
```

### 4. Batch Operations
```python
def add_quads_batch(self, quads: List[Quad]):
    try:
        self.store.extend(quads)  # Transactional
        return {"added_count": len(quads), "success": True}
    except OSError as e:
        return {"error": f"Batch insert failed: {e}", "success": False}
```

This documentation provides a comprehensive guide for implementing quad operations using pyoxigraph's in-memory store, suitable for the VitalGraph mock client implementation.