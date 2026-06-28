import logging
from rdflib.namespace import RDF
from six import text_type
from sqlalchemy.sql import expression, functions

from .constants import (
    ASSERTED_TYPE_PARTITION,
    ASSERTED_NON_TYPE_PARTITION,
    ASSERTED_LITERAL_PARTITION,
    QUOTED_PARTITION,
    CONTEXT_SELECT,
    COUNT_SELECT,
    FULL_TRIPLE_PARTITIONS,
    TRIPLE_SELECT,
    OPTIMIZED_TEXT_SELECT,
    SINGLE_TABLE_SELECT,
    TEXT_SEARCH_LITERAL_TABLE_PRIORITY,
)

_logger = logging.getLogger(__name__)


def query_analysis(query, store, connection):
    """
    Helper function.

    For executing EXPLAIN on all dispatched SQL statements -
    for the purpose of analyzing index usage.

    """
    _logger.info(f"🚀 query_analysis: FUNCTION STARTED with query length={len(query)}")
    res = connection.execute("explain " + query)
    rt = res.fetchall()[0]
    table, joinType, posKeys, _key, key_len, \
        comparedCol, rowsExamined, extra = rt
    if not _key:
        assert joinType == "ALL"
        if not hasattr(store, "queryOptMarks"):
            store.queryOptMarks = {}
        hits = store.queryOptMarks.get(("FULL SCAN", table), 0)
        store.queryOptMarks[("FULL SCAN", table)] = hits + 1

    if not hasattr(store, "queryOptMarks"):
        store.queryOptMarks = {}
    hits = store.queryOptMarks.get((_key, table), 0)
    store.queryOptMarks[(_key, table)] = hits + 1


def union_select(select_components, distinct=False, select_type=TRIPLE_SELECT, limit=None, offset=None):
    """
    Helper function for building union all select statement.

    Args:
        select_components (iterable of tuples): Indicates the table and table type
            (table_name, where_clause_string, table_type)
        distinct (bool): Whether to eliminate duplicate results
        select_type (int): From `rdflib_sqlalchemy.constants`. Either `.COUNT_SELECT`,
            `.CONTEXT_SELECT`, `.TRIPLE_SELECT`
        limit (int, optional): Maximum number of rows to return
        offset (int, optional): Number of rows to skip

    """
    _logger.info(f"🚀 union_select: FUNCTION STARTED with {len(list(select_components))} components, distinct={distinct}, select_type={select_type}, limit={limit}, offset={offset}")
    select_components = list(select_components)  # Convert to list for reuse
    selects = []
    for table, whereClause, tableType in select_components:

        if select_type == COUNT_SELECT:
            c = table.c
            if tableType == ASSERTED_TYPE_PARTITION:
                cols = [c.member, c.klass]
            elif tableType in (ASSERTED_LITERAL_PARTITION, ASSERTED_NON_TYPE_PARTITION, QUOTED_PARTITION):
                cols = [c.subject, c.predicate, c.object]
            else:
                raise ValueError('Unrecognized table type {}'.format(tableType))
            select_clause = expression.select(*[functions.count().label('aCount')]).select_from(
                expression.select(*cols).where(whereClause).distinct().select_from(table))
        elif select_type == CONTEXT_SELECT:
            select_clause = expression.select(table.c.context)
            if whereClause is not None:
                select_clause = expression.select(table.c.context).where(whereClause)
        elif tableType in FULL_TRIPLE_PARTITIONS:
            select_clause = table.select().where(whereClause)
        elif tableType == ASSERTED_TYPE_PARTITION:
            select_clause = expression.select(
                *[table.c.id.label("id"),
                 table.c.member.label("subject"),
                 expression.literal(text_type(RDF.type)).label("predicate"),
                 table.c.klass.label("object"),
                 table.c.context.label("context"),
                 table.c.termComb.label("termcomb"),
                 expression.literal_column("NULL").label("objlanguage"),
                 expression.literal_column("NULL").label("objdatatype")]).where(
                whereClause)
        elif tableType == ASSERTED_NON_TYPE_PARTITION:
            all_table_columns = [c for c in table.columns] + \
                                [expression.literal_column("NULL").label("objlanguage"),
                                 expression.literal_column("NULL").label("objdatatype")]
            if whereClause is not None:
                select_clause = expression.select(*all_table_columns).select_from(table).where(whereClause)
            else:
                select_clause = expression.select(*all_table_columns).select_from(table)
        selects.append(select_clause)

    order_statement = []
    if select_type == TRIPLE_SELECT:
        order_statement = [
            expression.literal_column("subject"),
            expression.literal_column("predicate"),
            expression.literal_column("object"),
        ]
    if distinct and select_type != COUNT_SELECT:
        query = expression.union(*selects).order_by(*order_statement)
    else:
        query = expression.union_all(*selects).order_by(*order_statement)
    
    # Apply LIMIT and OFFSET if specified
    if limit is not None:
        query = query.limit(limit)
        _logger.info(f"Applied SQL LIMIT: {limit}")
    if offset is not None:
        query = query.offset(offset)
        _logger.info(f"Applied SQL OFFSET: {offset}")
    
    return query


def optimized_single_table_select(table, whereClause, tableType, select_type=TRIPLE_SELECT, limit=None, offset=None):
    """Optimized path for single-table queries with optional LIMIT/OFFSET support"""
    _logger.info(f"🚀 optimized_single_table_select: FUNCTION STARTED with tableType={tableType}, select_type={select_type}, limit={limit}, offset={offset}")
    if select_type == COUNT_SELECT:
        c = table.c
        if tableType == ASSERTED_TYPE_PARTITION:
            cols = [c.member, c.klass]
        elif tableType in (ASSERTED_LITERAL_PARTITION, ASSERTED_NON_TYPE_PARTITION, QUOTED_PARTITION):
            cols = [c.subject, c.predicate, c.object]
        else:
            raise ValueError('Unrecognized table type {}'.format(tableType))
        select_clause = expression.select(*[functions.count().label('aCount')]).select_from(
            expression.select(*cols).where(whereClause).distinct().select_from(table))
    elif select_type == CONTEXT_SELECT:
        select_clause = expression.select(table.c.context)
        if whereClause is not None:
            select_clause = expression.select(table.c.context).where(whereClause)
    elif tableType in FULL_TRIPLE_PARTITIONS:
        select_clause = table.select().where(whereClause)
    elif tableType == ASSERTED_TYPE_PARTITION:
        select_clause = expression.select(
            *[table.c.id.label("id"),
             table.c.member.label("subject"),
             expression.literal(text_type(RDF.type)).label("predicate"),
             table.c.klass.label("object"),
             table.c.context.label("context"),
             table.c.termComb.label("termcomb"),
             expression.literal_column("NULL").label("objlanguage"),
             expression.literal_column("NULL").label("objdatatype")]).where(
            whereClause)
    elif tableType == ASSERTED_NON_TYPE_PARTITION:
        all_table_columns = [c for c in table.columns] + \
                            [expression.literal_column("NULL").label("objlanguage"),
                             expression.literal_column("NULL").label("objdatatype")]
        if whereClause is not None:
            select_clause = expression.select(*all_table_columns).select_from(table).where(whereClause)
        else:
            select_clause = expression.select(*all_table_columns).select_from(table)
    elif tableType == ASSERTED_LITERAL_PARTITION:
        # Optimized path for literal table (most common for text search)
        if whereClause is not None:
            select_clause = table.select().where(whereClause)
        else:
            select_clause = table.select()
    
    # Add ordering for consistency
    if select_type == TRIPLE_SELECT:
        order_statement = [
            expression.literal_column("subject"),
            expression.literal_column("predicate"),
            expression.literal_column("object"),
        ]
        select_clause = select_clause.order_by(*order_statement)
    
    # Apply LIMIT and OFFSET if specified
    if limit is not None:
        select_clause = select_clause.limit(limit)
        _logger.info(f"Applied SQL LIMIT: {limit}")
    if offset is not None:
        select_clause = select_clause.offset(offset)
        _logger.info(f"Applied SQL OFFSET: {offset}")
    
    return select_clause


def prioritize_literal_table_for_text_search(select_components, has_text_filter=False):
    """Prioritize literal table when text search is detected"""
    _logger.info(f"🚀 prioritize_literal_table_for_text_search: FUNCTION STARTED with {len(select_components)} components, has_text_filter={has_text_filter}")
    if not has_text_filter or not TEXT_SEARCH_LITERAL_TABLE_PRIORITY:
        return select_components
    
    # Separate literal table from others
    literal_components = []
    other_components = []
    
    for component in select_components:
        table, whereClause, tableType = component
        if tableType == ASSERTED_LITERAL_PARTITION:
            literal_components.append(component)
        else:
            other_components.append(component)
    
    # Return literal table first for better performance
    return literal_components + other_components


def union_select_with_pushdown(select_components, text_filters=None, distinct=False, select_type=TRIPLE_SELECT, limit=None, offset=None):
    """Enhanced union with filter pushdown optimization"""
    _logger.info(f"🚀 union_select_with_pushdown: FUNCTION STARTED with {len(select_components)} components, text_filters={text_filters is not None}, distinct={distinct}, limit={limit}, offset={offset}")
    # If only one component and it's a text search, use optimized single table path
    if len(select_components) == 1 and text_filters:
        table, whereClause, tableType = select_components[0]
        return optimized_single_table_select(table, whereClause, tableType, select_type)
    
    # Prioritize literal table for text searches
    has_text_filter = text_filters is not None and len(text_filters) > 0
    prioritized_components = prioritize_literal_table_for_text_search(select_components, has_text_filter)
    
    # Fall back to standard union select
    return union_select(prioritized_components, distinct, select_type, limit, offset)
