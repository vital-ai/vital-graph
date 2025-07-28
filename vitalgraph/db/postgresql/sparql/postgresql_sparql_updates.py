"""
PostgreSQL SPARQL Updates Functions for VitalGraph

This module provides pure functions for translating SPARQL 1.1 UPDATE operations
(INSERT DATA, DELETE DATA, MODIFY, LOAD, CLEAR, etc.) to SQL operations.
No inter-dependencies with other SPARQL modules - only imports utilities.
"""

import logging
from typing import Dict, List, Tuple, Set, Optional, Any, Union
from rdflib import Variable, URIRef, Literal, BNode, Graph

# Import only from core module and utilities
from .postgresql_sparql_core import SQLComponents, TableConfig, convert_rdflib_term_to_sql, extract_term_info


def translate_insert_data(triples: List[Tuple], graph_uri: Optional[str], 
                         table_config: TableConfig) -> List[str]:
    """
    Translate INSERT DATA operation to SQL INSERT statements.
    
    Args:
        triples: List of (subject, predicate, object) triples to insert
        graph_uri: Target graph URI (None for default graph)
        table_config: Table configuration
        
    Returns:
        List of SQL statements to execute the INSERT DATA operation
    """
    logger = logging.getLogger(__name__)
    logger.debug(f"Translating INSERT DATA for {len(triples)} triples into graph: {graph_uri}")
    
    if not triples:
        return []
    
    # Default graph URI if none specified
    if graph_uri is None:
        graph_uri = "urn:___GLOBAL"
    
    sql_statements = []
    
    # First, ensure all terms exist in the term table
    terms_to_insert = set()
    for triple in triples:
        for term in triple:
            term_text, term_type = extract_term_info(term)
            terms_to_insert.add((term_text, term_type))
    
    # Add graph term
    terms_to_insert.add((graph_uri, 'U'))
    
    # Generate term insertion SQL
    if terms_to_insert:
        term_values = []
        for term_text, term_type in terms_to_insert:
            escaped_text = term_text.replace("'", "''")
            term_values.append(f"('{escaped_text}', '{term_type}')")
        
        term_insert_sql = f"""
            INSERT INTO {table_config.term_table} (term_text, term_type)
            VALUES {', '.join(term_values)}
            ON CONFLICT (term_text, term_type) DO NOTHING
        """
        sql_statements.append(term_insert_sql)
    
    # Generate quad insertion SQL
    quad_values = []
    for triple in triples:
        subject, predicate, obj = triple
        s_text, s_type = extract_term_info(subject)
        p_text, p_type = extract_term_info(predicate)
        o_text, o_type = extract_term_info(obj)
        
        quad_insert = f"""
            (
                (SELECT term_uuid FROM {table_config.term_table} WHERE term_text = '{s_text.replace("'", "''")}' AND term_type = '{s_type}'),
                (SELECT term_uuid FROM {table_config.term_table} WHERE term_text = '{p_text.replace("'", "''")}' AND term_type = '{p_type}'),
                (SELECT term_uuid FROM {table_config.term_table} WHERE term_text = '{o_text.replace("'", "''")}' AND term_type = '{o_type}'),
                (SELECT term_uuid FROM {table_config.term_table} WHERE term_text = '{graph_uri.replace("'", "''")}' AND term_type = 'U')
            )
        """
        quad_values.append(quad_insert)
    
    if quad_values:
        quad_insert_sql = f"""
            INSERT INTO {table_config.quad_table} (subject_uuid, predicate_uuid, object_uuid, context_uuid)
            VALUES {', '.join(quad_values)}
        """
        sql_statements.append(quad_insert_sql)
    
    return sql_statements


def translate_delete_data(triples: List[Tuple], graph_uri: Optional[str],
                         table_config: TableConfig) -> List[str]:
    """
    Translate DELETE DATA operation to SQL DELETE statements.
    
    Args:
        triples: List of (subject, predicate, object) triples to delete
        graph_uri: Target graph URI (None for default graph)
        table_config: Table configuration
        
    Returns:
        List of SQL statements to execute the DELETE DATA operation
    """
    logger = logging.getLogger(__name__)
    logger.debug(f"Translating DELETE DATA for {len(triples)} triples from graph: {graph_uri}")
    
    if not triples:
        return []
    
    # Default graph URI if none specified
    if graph_uri is None:
        graph_uri = "urn:___GLOBAL"
    
    sql_statements = []
    
    # Generate quad deletion SQL for each triple
    for triple in triples:
        subject, predicate, obj = triple
        s_text, s_type = extract_term_info(subject)
        p_text, p_type = extract_term_info(predicate)
        o_text, o_type = extract_term_info(obj)
        
        delete_sql = f"""
            DELETE FROM {table_config.quad_table}
            WHERE subject_uuid = (SELECT term_uuid FROM {table_config.term_table} WHERE term_text = '{s_text.replace("'", "''")}' AND term_type = '{s_type}')
              AND predicate_uuid = (SELECT term_uuid FROM {table_config.term_table} WHERE term_text = '{p_text.replace("'", "''")}' AND term_type = '{p_type}')
              AND object_uuid = (SELECT term_uuid FROM {table_config.term_table} WHERE term_text = '{o_text.replace("'", "''")}' AND term_type = '{o_type}')
              AND context_uuid = (SELECT term_uuid FROM {table_config.term_table} WHERE term_text = '{graph_uri.replace("'", "''")}' AND term_type = 'U')
        """
        sql_statements.append(delete_sql)
    
    return sql_statements


def translate_modify_operation(delete_template: List[Tuple], insert_template: List[Tuple],
                             where_sql: SQLComponents, table_config: TableConfig) -> List[str]:
    """
    Translate SPARQL MODIFY operation (DELETE/INSERT with WHERE clause) to SQL.
    
    Args:
        delete_template: List of triples to delete (may contain variables)
        insert_template: List of triples to insert (may contain variables)
        where_sql: SQL components for the WHERE clause pattern matching
        table_config: Table configuration
        
    Returns:
        List of SQL statements to execute the MODIFY operation
    """
    logger = logging.getLogger(__name__)
    logger.debug(f"Translating MODIFY operation: DELETE {len(delete_template)}, INSERT {len(insert_template)} templates")
    
    sql_statements = []
    
    # MODIFY operations are complex because they involve:
    # 1. Finding all variable bindings that match the WHERE clause
    # 2. For each binding, instantiate the DELETE template and delete those triples
    # 3. For each binding, instantiate the INSERT template and insert those triples
    
    # Build a CTE (Common Table Expression) to get all variable bindings
    if where_sql.variable_mappings:
        # Create a subquery to get all matching variable bindings
        binding_vars = list(where_sql.variable_mappings.keys())
        binding_columns = []
        for var in binding_vars:
            var_name = str(var).replace('?', '')
            binding_columns.append(f"{where_sql.variable_mappings[var]} AS {var_name}")
        
        bindings_query = f"SELECT DISTINCT {', '.join(binding_columns)}"
        if where_sql.from_clause:
            bindings_query += f" {where_sql.from_clause}"
        if where_sql.joins:
            bindings_query += f" {' '.join(where_sql.joins)}"
        if where_sql.where_conditions:
            bindings_query += f" WHERE {' AND '.join(where_sql.where_conditions)}"
        
        # Use the bindings to instantiate templates
        if delete_template:
            # Generate DELETE operations for each template pattern
            for i, (s, p, o) in enumerate(delete_template):
                delete_sql = f"""
                    DELETE FROM {table_config.quad_table}
                    WHERE (subject_uuid, predicate_uuid, object_uuid, context_uuid) IN (
                        SELECT 
                            {_build_term_expression(s, binding_vars, table_config)},
                            {_build_term_expression(p, binding_vars, table_config)},
                            {_build_term_expression(o, binding_vars, table_config)},
                            (SELECT term_uuid FROM {table_config.term_table} WHERE term_text = 'urn:___GLOBAL' AND term_type = 'U')
                        FROM ({bindings_query}) AS bindings
                    )
                """
                sql_statements.append(delete_sql)
        
        if insert_template:
            # Generate INSERT operations for each template pattern
            insert_values = []
            for i, (s, p, o) in enumerate(insert_template):
                insert_values.append(f"""
                    SELECT 
                        {_build_term_expression(s, binding_vars, table_config)},
                        {_build_term_expression(p, binding_vars, table_config)},
                        {_build_term_expression(o, binding_vars, table_config)},
                        (SELECT term_uuid FROM {table_config.term_table} WHERE term_text = 'urn:___GLOBAL' AND term_type = 'U')
                    FROM ({bindings_query}) AS bindings
                """)
            
            if insert_values:
                insert_sql = f"""
                    INSERT INTO {table_config.quad_table} (subject_uuid, predicate_uuid, object_uuid, context_uuid)
                    {' UNION ALL '.join(insert_values)}
                """
                sql_statements.append(insert_sql)
    
    return sql_statements


def translate_load_operation(source_uri: str, target_graph: Optional[str],
                           table_config: TableConfig) -> List[str]:
    """
    Translate SPARQL LOAD operation to SQL statements.
    
    Args:
        source_uri: URI of the RDF document to load
        target_graph: Target graph URI (None for default graph)
        table_config: Table configuration
        
    Returns:
        List of SQL statements to execute the LOAD operation
    """
    logger = logging.getLogger(__name__)
    logger.debug(f"Translating LOAD operation from {source_uri} to graph: {target_graph}")
    
    # LOAD operations require:
    # 1. Fetching the RDF document from the source URI
    # 2. Parsing the RDF content
    # 3. Converting to triples/quads
    # 4. Inserting into the target graph
    
    # This is a placeholder - actual implementation would need HTTP client
    # and RDF parser integration
    
    sql_statements = [
        f"-- LOAD operation: fetch and parse {source_uri}",
        f"-- Target graph: {target_graph or 'default'}",
        f"-- Implementation requires external RDF parsing"
    ]
    
    return sql_statements


def translate_clear_operation(graph_uri: Optional[str], table_config: TableConfig) -> List[str]:
    """
    Translate SPARQL CLEAR operation to SQL DELETE statements.
    
    Args:
        graph_uri: Graph URI to clear (None for default graph, 'ALL' for all graphs)
        table_config: Table configuration
        
    Returns:
        List of SQL statements to execute the CLEAR operation
    """
    logger = logging.getLogger(__name__)
    logger.debug(f"Translating CLEAR operation for graph: {graph_uri}")
    
    sql_statements = []
    
    if graph_uri == 'ALL':
        # Clear all graphs - delete all quads
        clear_all_sql = f"DELETE FROM {table_config.quad_table}"
        sql_statements.append(clear_all_sql)
    elif graph_uri is None:
        # Clear default graph
        default_graph_uri = "urn:___GLOBAL"
        clear_default_sql = f"""
            DELETE FROM {table_config.quad_table}
            WHERE context_uuid = (SELECT term_uuid FROM {table_config.term_table} 
                                WHERE term_text = '{default_graph_uri}' AND term_type = 'U')
        """
        sql_statements.append(clear_default_sql)
    else:
        # Clear specific graph
        clear_graph_sql = f"""
            DELETE FROM {table_config.quad_table}
            WHERE context_uuid = (SELECT term_uuid FROM {table_config.term_table} 
                                WHERE term_text = '{graph_uri.replace("'", "''")}' AND term_type = 'U')
        """
        sql_statements.append(clear_graph_sql)
    
    return sql_statements


def translate_create_operation(graph_uri: str, table_config: TableConfig) -> List[str]:
    """
    Translate SPARQL CREATE operation to SQL statements.
    
    Args:
        graph_uri: URI of the graph to create
        table_config: Table configuration
        
    Returns:
        List of SQL statements to execute the CREATE operation
    """
    logger = logging.getLogger(__name__)
    logger.debug(f"Translating CREATE operation for graph: {graph_uri}")
    
    # CREATE operation just ensures the graph URI exists in the term table
    # The graph is implicitly created when triples are added to it
    
    sql_statements = [
        f"""
            INSERT INTO {table_config.term_table} (term_text, term_type)
            VALUES ('{graph_uri.replace("'", "''")}', 'U')
            ON CONFLICT (term_text, term_type) DO NOTHING
        """
    ]
    
    return sql_statements


def translate_drop_operation(graph_uri: str, table_config: TableConfig) -> List[str]:
    """
    Translate SPARQL DROP operation to SQL DELETE statements.
    
    Args:
        graph_uri: URI of the graph to drop
        table_config: Table configuration
        
    Returns:
        List of SQL statements to execute the DROP operation
    """
    logger = logging.getLogger(__name__)
    logger.debug(f"Translating DROP operation for graph: {graph_uri}")
    
    sql_statements = []
    
    # First, delete all quads in the graph
    delete_quads_sql = f"""
        DELETE FROM {table_config.quad_table}
        WHERE context_uuid = (SELECT term_uuid FROM {table_config.term_table} 
                            WHERE term_text = '{graph_uri.replace("'", "''")}' AND term_type = 'U')
    """
    sql_statements.append(delete_quads_sql)
    
    # Optionally, remove the graph term itself
    # (This is debatable - some implementations keep the graph term)
    delete_graph_term_sql = f"""
        DELETE FROM {table_config.term_table}
        WHERE term_text = '{graph_uri.replace("'", "''")}' AND term_type = 'U'
          AND NOT EXISTS (
              SELECT 1 FROM {table_config.quad_table} 
              WHERE context_uuid = (SELECT term_uuid FROM {table_config.term_table} t2 
                                  WHERE t2.term_text = '{graph_uri.replace("'", "''")}' AND t2.term_type = 'U')
          )
    """
    sql_statements.append(delete_graph_term_sql)
    
    return sql_statements


def translate_copy_operation(source_graph: str, target_graph: str, 
                           table_config: TableConfig) -> List[str]:
    """
    Translate SPARQL COPY operation to SQL statements.
    
    Args:
        source_graph: URI of the source graph
        target_graph: URI of the target graph
        table_config: Table configuration
        
    Returns:
        List of SQL statements to execute the COPY operation
    """
    logger = logging.getLogger(__name__)
    logger.debug(f"Translating COPY operation from {source_graph} to {target_graph}")
    
    sql_statements = []
    
    # First, ensure target graph term exists
    create_target_sql = f"""
        INSERT INTO {table_config.term_table} (term_text, term_type)
        VALUES ('{target_graph.replace("'", "''")}', 'U')
        ON CONFLICT (term_text, term_type) DO NOTHING
    """
    sql_statements.append(create_target_sql)
    
    # Copy all quads from source graph to target graph
    copy_quads_sql = f"""
        INSERT INTO {table_config.quad_table} (subject_uuid, predicate_uuid, object_uuid, context_uuid)
        SELECT 
            subject_uuid, 
            predicate_uuid, 
            object_uuid,
            (SELECT term_uuid FROM {table_config.term_table} WHERE term_text = '{target_graph.replace("'", "''")}' AND term_type = 'U') AS context_uuid
        FROM {table_config.quad_table}
        WHERE context_uuid = (SELECT term_uuid FROM {table_config.term_table} 
                            WHERE term_text = '{source_graph.replace("'", "''")}' AND term_type = 'U')
    """
    sql_statements.append(copy_quads_sql)
    
    return sql_statements


def translate_move_operation(source_graph: str, target_graph: str,
                           table_config: TableConfig) -> List[str]:
    """
    Translate SPARQL MOVE operation to SQL statements.
    
    Args:
        source_graph: URI of the source graph
        target_graph: URI of the target graph
        table_config: Table configuration
        
    Returns:
        List of SQL statements to execute the MOVE operation
    """
    logger = logging.getLogger(__name__)
    logger.debug(f"Translating MOVE operation from {source_graph} to {target_graph}")
    
    sql_statements = []
    
    # First, ensure target graph term exists
    create_target_sql = f"""
        INSERT INTO {table_config.term_table} (term_text, term_type)
        VALUES ('{target_graph.replace("'", "''")}', 'U')
        ON CONFLICT (term_text, term_type) DO NOTHING
    """
    sql_statements.append(create_target_sql)
    
    # Move all quads from source graph to target graph (UPDATE context_uuid)
    move_quads_sql = f"""
        UPDATE {table_config.quad_table}
        SET context_uuid = (SELECT term_uuid FROM {table_config.term_table} WHERE term_text = '{target_graph.replace("'", "''")}' AND term_type = 'U')
        WHERE context_uuid = (SELECT term_uuid FROM {table_config.term_table} 
                            WHERE term_text = '{source_graph.replace("'", "''")}' AND term_type = 'U')
    """
    sql_statements.append(move_quads_sql)
    
    return sql_statements


def translate_add_operation(source_graph: str, target_graph: str,
                          table_config: TableConfig) -> List[str]:
    """
    Translate SPARQL ADD operation to SQL statements.
    
    Args:
        source_graph: URI of the source graph
        target_graph: URI of the target graph
        table_config: Table configuration
        
    Returns:
        List of SQL statements to execute the ADD operation
    """
    logger = logging.getLogger(__name__)
    logger.debug(f"Translating ADD operation from {source_graph} to {target_graph}")
    
    sql_statements = []
    
    # First, ensure target graph term exists
    create_target_sql = f"""
        INSERT INTO {table_config.term_table} (term_text, term_type)
        VALUES ('{target_graph.replace("'", "''")}', 'U')
        ON CONFLICT (term_text, term_type) DO NOTHING
    """
    sql_statements.append(create_target_sql)
    
    # Add (copy) all quads from source graph to target graph
    # This is similar to COPY but doesn't clear the target graph first
    add_quads_sql = f"""
        INSERT INTO {table_config.quad_table} (subject_uuid, predicate_uuid, object_uuid, context_uuid)
        SELECT 
            subject_uuid, 
            predicate_uuid, 
            object_uuid,
            (SELECT term_uuid FROM {table_config.term_table} WHERE term_text = '{target_graph.replace("'", "''")}' AND term_type = 'U') AS context_uuid
        FROM {table_config.quad_table}
        WHERE context_uuid = (SELECT term_uuid FROM {table_config.term_table} 
                            WHERE term_text = '{source_graph.replace("'", "''")}' AND term_type = 'U')
        ON CONFLICT DO NOTHING
    """
    sql_statements.append(add_quads_sql)
    
    return sql_statements


def validate_update_operation(operation_type: str, **kwargs) -> bool:
    """
    Validate that an update operation has the required parameters.
    
    Args:
        operation_type: Type of update operation
        **kwargs: Operation parameters
        
    Returns:
        True if the operation is valid
    """
    logger = logging.getLogger(__name__)
    logger.debug(f"Validating {operation_type} operation")
    
    try:
        if operation_type == "INSERT_DATA":
            return 'triples' in kwargs and isinstance(kwargs['triples'], list)
        elif operation_type == "DELETE_DATA":
            return 'triples' in kwargs and isinstance(kwargs['triples'], list)
        elif operation_type == "MODIFY":
            return all(key in kwargs for key in ['delete_template', 'insert_template', 'where_sql'])
        elif operation_type == "LOAD":
            return 'source_uri' in kwargs and isinstance(kwargs['source_uri'], str)
        elif operation_type == "CLEAR":
            return True  # CLEAR can work with or without graph_uri
        elif operation_type in ["CREATE", "DROP"]:
            return 'graph_uri' in kwargs and isinstance(kwargs['graph_uri'], str)
        elif operation_type in ["COPY", "MOVE", "ADD"]:
            return all(key in kwargs for key in ['source_graph', 'target_graph'])
        else:
            logger.error(f"Unknown update operation type: {operation_type}")
            return False
            
    except Exception as e:
        logger.error(f"Error validating {operation_type} operation: {e}")
        return False


def estimate_update_cost(operation_type: str, **kwargs) -> int:
    """
    Estimate the computational cost of an update operation.
    
    Args:
        operation_type: Type of update operation
        **kwargs: Operation parameters
        
    Returns:
        Estimated cost score (higher = more expensive)
    """
    logger = logging.getLogger(__name__)
    logger.debug(f"Estimating cost for {operation_type} operation")
    
    base_costs = {
        "INSERT_DATA": 2,
        "DELETE_DATA": 3,
        "MODIFY": 10,  # Most expensive due to pattern matching
        "LOAD": 8,     # Expensive due to external fetch and parsing
        "CLEAR": 5,    # Expensive due to potentially large deletes
        "CREATE": 1,   # Cheapest - just term insertion
        "DROP": 6,     # Expensive due to cascade deletes
        "COPY": 7,     # Expensive due to large inserts
        "MOVE": 4,     # Moderate - just updates context_uuid
        "ADD": 6       # Similar to COPY but with conflict handling
    }
    
    base_cost = base_costs.get(operation_type, 5)
    
    # Add cost based on operation parameters
    if operation_type in ["INSERT_DATA", "DELETE_DATA"] and 'triples' in kwargs:
        base_cost += len(kwargs['triples']) // 10  # Scale with number of triples
    
    if operation_type == "MODIFY":
        if 'delete_template' in kwargs:
            base_cost += len(kwargs['delete_template']) * 2
        if 'insert_template' in kwargs:
            base_cost += len(kwargs['insert_template']) * 2
    
    return base_cost


def _build_term_expression(term, binding_vars: List[Variable], table_config: TableConfig) -> str:
    """
    Build SQL expression for a term that may be a variable or constant.
    
    Args:
        term: RDF term (Variable, URIRef, Literal, or BNode)
        binding_vars: List of variables available in the current binding context
        table_config: Table configuration
        
    Returns:
        SQL expression for the term
    """
    if isinstance(term, Variable) and term in binding_vars:
        # Variable - use the bound value from the bindings table
        var_name = str(term).replace('?', '')
        return f"bindings.{var_name}"
    else:
        # Constant term - look up in term table
        term_text, term_type = extract_term_info(term)
        escaped_text = term_text.replace("'", "''")
        return f"(SELECT term_uuid FROM {table_config.term_table} WHERE term_text = '{escaped_text}' AND term_type = '{term_type}')"


def batch_update_operations(operations: List[Tuple[str, Dict]], table_config: TableConfig) -> List[str]:
    """
    Batch multiple update operations into optimized SQL statements.
    
    Args:
        operations: List of (operation_type, kwargs) tuples
        table_config: Table configuration
        
    Returns:
        List of optimized SQL statements
    """
    logger = logging.getLogger(__name__)
    logger.debug(f"Batching {len(operations)} update operations")
    
    all_statements = []
    
    # Group similar operations for batching
    insert_data_ops = []
    delete_data_ops = []
    other_ops = []
    
    for op_type, kwargs in operations:
        if op_type == "INSERT_DATA":
            insert_data_ops.append(kwargs)
        elif op_type == "DELETE_DATA":
            delete_data_ops.append(kwargs)
        else:
            other_ops.append((op_type, kwargs))
    
    # Batch INSERT DATA operations
    if insert_data_ops:
        all_triples = []
        graph_uri = None
        for op in insert_data_ops:
            all_triples.extend(op.get('triples', []))
            if graph_uri is None:
                graph_uri = op.get('graph_uri')
        
        if all_triples:
            batched_statements = translate_insert_data(all_triples, graph_uri, table_config)
            all_statements.extend(batched_statements)
    
    # Batch DELETE DATA operations
    if delete_data_ops:
        all_triples = []
        graph_uri = None
        for op in delete_data_ops:
            all_triples.extend(op.get('triples', []))
            if graph_uri is None:
                graph_uri = op.get('graph_uri')
        
        if all_triples:
            batched_statements = translate_delete_data(all_triples, graph_uri, table_config)
            all_statements.extend(batched_statements)
    
    # Process other operations individually
    for op_type, kwargs in other_ops:
        if op_type == "MODIFY":
            statements = translate_modify_operation(
                kwargs.get('delete_template', []),
                kwargs.get('insert_template', []),
                kwargs.get('where_sql'),
                table_config
            )
        elif op_type == "LOAD":
            statements = translate_load_operation(
                kwargs.get('source_uri'),
                kwargs.get('target_graph'),
                table_config
            )
        elif op_type == "CLEAR":
            statements = translate_clear_operation(
                kwargs.get('graph_uri'),
                table_config
            )
        elif op_type == "CREATE":
            statements = translate_create_operation(
                kwargs.get('graph_uri'),
                table_config
            )
        elif op_type == "DROP":
            statements = translate_drop_operation(
                kwargs.get('graph_uri'),
                table_config
            )
        elif op_type == "COPY":
            statements = translate_copy_operation(
                kwargs.get('source_graph'),
                kwargs.get('target_graph'),
                table_config
            )
        elif op_type == "MOVE":
            statements = translate_move_operation(
                kwargs.get('source_graph'),
                kwargs.get('target_graph'),
                table_config
            )
        elif op_type == "ADD":
            statements = translate_add_operation(
                kwargs.get('source_graph'),
                kwargs.get('target_graph'),
                table_config
            )
        else:
            logger.warning(f"Unknown operation type: {op_type}")
            statements = []
        
        all_statements.extend(statements)
    
    return all_statements
    
    return base_cost
