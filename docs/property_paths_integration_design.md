# Property Paths Integration Design

## Variable Mapping Integration

### Current Variable Mapping System
The existing `_translate_bgp()` method maintains a `Dict[Variable, str]` that maps SPARQL variables to SQL column references:
```python
variable_mappings[subject] = f"{term_alias}.term_text"
```

### Property Path Variable Mapping Challenges

#### 1. CTE Result Integration
Property path CTEs produce results that need to integrate with the main BGP variable mapping:

```python
# Property path CTE produces columns like:
# - start_node (subject variable)
# - end_node (object variable)

# These need to map to SPARQL variables:
variable_mappings[subject_var] = f"{cte_alias}.start_node"
variable_mappings[object_var] = f"{cte_alias}.end_node"
```

#### 2. Mixed BGP Integration
When a BGP contains both regular triples and property paths:

```sparql
SELECT ?person ?name WHERE {
  ?person foaf:knows+ ?friend .     # Property path
  ?friend foaf:name ?name .         # Regular triple
}
```

The property path CTE must JOIN with regular BGP patterns:
```sql
WITH RECURSIVE knows_path AS (
  -- Property path CTE
) 
SELECT p_term.term_text as person, n_term.term_text as name
FROM knows_path kp
JOIN vitalgraph1__space_test__rdf_quad name_q ON name_q.subject_uuid = (
  SELECT term_uuid FROM vitalgraph1__space_test__term WHERE term_text = kp.end_node
)
JOIN vitalgraph1__space_test__term n_term ON name_q.object_uuid = n_term.term_uuid
JOIN vitalgraph1__space_test__term p_term ON p_term.term_text = kp.start_node
WHERE name_q.predicate_uuid = '{foaf_name_uuid}'
```

### Integration Strategy

#### 1. CTE-to-Variable Mapping
```python
async def _map_path_variables(self, subject, obj, cte_alias, variable_mappings, projected_vars):
    """Map property path CTE results to SPARQL variables."""
    if isinstance(subject, Variable) and (projected_vars is None or subject in projected_vars):
        variable_mappings[subject] = f"{cte_alias}.start_node"
    
    if isinstance(obj, Variable) and (projected_vars is None or obj in projected_vars):
        variable_mappings[obj] = f"{cte_alias}.end_node"
```

#### 2. CTE Integration with BGP
```python
async def _integrate_path_with_bgp(self, path_cte, path_vars, bgp_from, bgp_where, bgp_joins, bgp_vars):
    """Integrate property path CTE with regular BGP patterns."""
    
    # Find shared variables between path and BGP
    shared_vars = set(path_vars.keys()) & set(bgp_vars.keys())
    
    if shared_vars:
        # Create JOINs based on shared variables
        join_conditions = []
        for var in shared_vars:
            path_col = path_vars[var]
            bgp_col = bgp_vars[var]
            
            # Convert text-based path results to UUID-based BGP joins
            join_conditions.append(f"""
                {bgp_col.split('.')[0]}.term_uuid = (
                    SELECT term_uuid FROM {table_config.term_table} 
                    WHERE term_text = {path_col}
                )
            """)
        
        # Combine path CTE with BGP
        combined_from = f"FROM ({path_cte}) path_cte, {bgp_from.replace('FROM ', '')}"
        combined_where = bgp_where + join_conditions
        
        return combined_from, combined_where, bgp_joins, {**path_vars, **bgp_vars}
    else:
        # No shared variables - Cartesian product
        combined_from = f"FROM ({path_cte}) path_cte, {bgp_from.replace('FROM ', '')}"
        return combined_from, bgp_where, bgp_joins, {**path_vars, **bgp_vars}
```

## JOIN Integration Strategy

### 1. Path-to-BGP JOINs
When property paths share variables with regular BGP patterns:

```python
async def _create_path_bgp_joins(self, shared_variables, path_alias, bgp_patterns, table_config):
    """Create JOINs between property path results and BGP patterns."""
    joins = []
    
    for var in shared_variables:
        # Property path produces text results, BGP uses UUIDs
        # Need to convert via term table lookup
        joins.append(f"""
            JOIN {table_config.term_table} {var}_bridge 
            ON {var}_bridge.term_text = {path_alias}.{self._get_path_column(var)}
        """)
    
    return joins
```

### 2. Multi-Path JOINs
When multiple property paths share variables:

```sparql
SELECT ?person ?friend1 ?friend2 WHERE {
  ?person foaf:knows+ ?friend1 .
  ?person foaf:knows+ ?friend2 .
  FILTER(?friend1 != ?friend2)
}
```

```sql
WITH RECURSIVE 
path1 AS (/* first knows+ path */),
path2 AS (/* second knows+ path */)
SELECT p1.start_node as person, p1.end_node as friend1, p2.end_node as friend2
FROM path1 p1
JOIN path2 p2 ON p1.start_node = p2.start_node
WHERE p1.end_node != p2.end_node
```

## Modified BGP Translation Logic

### Enhanced _translate_bgp Method
```python
async def _translate_bgp(self, bgp_pattern, table_config: TableConfig, projected_vars: List[Variable] = None, context_constraint: str = None, alias_gen: AliasGenerator = None):
    """Enhanced BGP translation with property path support."""
    
    triples = bgp_pattern.get('triples', [])
    if not triples:
        return f"FROM {table_config.quad_table} {alias_gen.next_quad_alias()}", [], [], {}
    
    # Separate regular triples from property path triples
    regular_triples = []
    path_triples = []
    
    for triple in triples:
        subject, predicate, obj = triple
        if isinstance(predicate, Path):
            path_triples.append(triple)
        else:
            regular_triples.append(triple)
    
    # Process regular triples with existing logic
    if regular_triples:
        bgp_from, bgp_where, bgp_joins, bgp_vars = await self._process_regular_triples(
            regular_triples, table_config, projected_vars, context_constraint, alias_gen
        )
    else:
        bgp_from, bgp_where, bgp_joins, bgp_vars = "", [], [], {}
    
    # Process property path triples
    path_ctes = []
    path_vars = {}
    
    for path_triple in path_triples:
        subject, path, obj = path_triple
        
        path_cte, path_where, path_joins, path_var_map = await self._translate_property_path(
            subject, path, obj, table_config, projected_vars, alias_gen
        )
        
        path_ctes.append(path_cte)
        path_vars.update(path_var_map)
    
    # Integrate paths with regular BGP
    if path_ctes and regular_triples:
        return await self._integrate_paths_with_bgp(
            path_ctes, path_vars, bgp_from, bgp_where, bgp_joins, bgp_vars, table_config, alias_gen
        )
    elif path_ctes:
        return await self._combine_path_ctes(path_ctes, path_vars, table_config, alias_gen)
    else:
        return bgp_from, bgp_where, bgp_joins, bgp_vars
```

## Performance Considerations

### 1. CTE Materialization
PostgreSQL may materialize CTEs, affecting performance:
```sql
-- Force materialization for complex paths
WITH path_results AS MATERIALIZED (
  -- Property path CTE
)
```

### 2. Index Utilization
Ensure property path queries use appropriate indexes:
- Subject/predicate/object indexes on quad table
- Term text indexes for path result lookups
- Composite indexes for common path patterns

### 3. Query Plan Optimization
```sql
-- Use EXPLAIN ANALYZE to optimize path queries
EXPLAIN (ANALYZE, BUFFERS) 
WITH RECURSIVE knows_path AS (...)
SELECT * FROM knows_path;
```

## Error Handling

### 1. Cycle Detection
```sql
WITH RECURSIVE path_traversal AS (
  -- Base case
  UNION ALL
  -- Recursive case with cycle detection
  WHERE NOT (new_node = ANY(path_array))
    AND depth < 100  -- Maximum depth limit
) CYCLE start_node, end_node SET is_cycle USING path
```

### 2. Path Not Found
Handle cases where property paths return no results:
```python
if not path_results:
    self.logger.warning(f"Property path {path} returned no results")
    # Return empty result set instead of error
    return "SELECT NULL as start_node, NULL as end_node WHERE 1=0", [], [], {}
```

## Testing Strategy

### Unit Tests
- Individual path type translation (MulPath, SequencePath, etc.)
- Variable mapping integration
- JOIN generation with regular BGP patterns

### Integration Tests
- Mixed BGP patterns with paths and regular triples
- Multiple property paths in same query
- Property paths with OPTIONAL, UNION, FILTER

### Performance Tests
- Large graph traversal with cycle detection
- Deep path traversal (10+ levels)
- Complex path combinations

This integration design ensures property paths work seamlessly with VitalGraph's existing SPARQL infrastructure while maintaining performance and correctness.
