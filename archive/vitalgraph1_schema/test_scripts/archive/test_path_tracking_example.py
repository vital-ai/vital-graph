#!/usr/bin/env python3
"""
Example of how to capture path information from property path queries.
This demonstrates modifying the CTE to return path arrays.
"""

async def test_path_tracking():
    """Example of capturing the actual path traversed in property paths."""
    
    # Modified CTE that returns path information
    path_query = """
    WITH RECURSIVE path_cte(start_node, end_node, path, depth) AS (
        -- Base case: direct relationships
        SELECT subject_uuid as start_node, object_uuid as end_node,
               ARRAY[subject_uuid, object_uuid] as path, 1 as depth
        FROM vitalgraph1__space_test__rdf_quad
        WHERE predicate_uuid = 'e8165b83-00bf-501c-8a28-54c6fab9f526'  -- ex:knows
        
        UNION ALL
        
        -- Recursive case: extend paths
        SELECT r.start_node, q.object_uuid as end_node,
               r.path || q.object_uuid as path, r.depth + 1 as depth
        FROM vitalgraph1__space_test__rdf_quad q
        JOIN path_cte r ON q.subject_uuid = r.end_node
        WHERE q.predicate_uuid = 'e8165b83-00bf-501c-8a28-54c6fab9f526'
          AND r.depth < 5  -- Limit depth
          AND NOT (q.object_uuid = ANY(r.path))  -- Cycle detection
    )
    SELECT 
        start_term.term_text as start_name,
        end_term.term_text as end_name,
        path,
        depth
    FROM path_cte
    JOIN vitalgraph1__space_test__term start_term ON path_cte.start_node = start_term.term_uuid
    JOIN vitalgraph1__space_test__term end_term ON path_cte.end_node = end_term.term_uuid
    WHERE depth > 1  -- Only multi-hop paths
    ORDER BY depth, start_name, end_name
    LIMIT 10;
    """
    
    print("Example paths with intermediate nodes:")
    print("Format: start -> end (path_array, depth)")
    print("-" * 50)
    
    # This would show results like:
    # Alice -> Charlie ([uuid1, uuid2, uuid3], 2)
    # Bob -> David ([uuid4, uuid5, uuid6, uuid7], 3)
    
    return path_query

# To convert UUID arrays back to readable names, you'd need additional joins:
def convert_path_to_names():
    """Convert UUID path arrays to readable names."""
    return """
    WITH path_results AS (
        -- Your path CTE here
    ),
    path_names AS (
        SELECT 
            start_name,
            end_name,
            depth,
            ARRAY(
                SELECT t.term_text 
                FROM unnest(path) AS path_uuid
                JOIN vitalgraph1__space_test__term t ON path_uuid = t.term_uuid
            ) as path_names
        FROM path_results
    )
    SELECT start_name, end_name, path_names, depth
    FROM path_names;
    """

if __name__ == "__main__":
    print("Path tracking example for SPARQL property paths")
    print("This shows how to modify CTEs to capture traversal paths")
