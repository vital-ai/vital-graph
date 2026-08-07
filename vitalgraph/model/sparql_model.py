"""SPARQL Model Classes

Pydantic models for SPARQL operations (Query, Update, Insert, Delete, Graph operations).
"""

from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field

from .api_model import BaseOperationResponse
from .result_status import ResultStatus, OperationStatus


# SPARQL Graph Models
class GraphInfo(BaseModel):
    """Information about a graph."""
    graph_uri: str = Field(
        ...,
        description="Graph URI"
    )
    triple_count: Optional[int] = Field(
        None,
        description="Number of triples in the graph"
    )
    created_time: Optional[str] = Field(
        None,
        description="Graph creation timestamp"
    )
    updated_time: Optional[str] = Field(
        None,
        description="Graph last update timestamp"
    )


class GraphListResponse(ResultStatus):
    """Response model for GET /api/graphs/graphs.

    Previously a bare JSON array, which could not carry status/message and made
    "space has no graphs" (EMPTY) indistinguishable from "space not found"
    (NOT_FOUND) — both serialized as [].
    """
    status: OperationStatus = Field(
        OperationStatus.FOUND, description="Outcome discriminator (FOUND/EMPTY/NOT_FOUND)"
    )
    graphs: List[GraphInfo] = Field(
        default_factory=list, description="Graphs in the space"
    )
    total_count: int = Field(0, description="Number of graphs returned")


class GraphInfoResponse(ResultStatus):
    """Response model for graph info requests.

    Carries the unified success/status/message contract (``success`` derived from
    ``status``). ``status`` defaults to FOUND; set NOT_FOUND when the graph does
    not exist.
    """
    status: OperationStatus = Field(
        OperationStatus.FOUND, description="Outcome discriminator (FOUND/NOT_FOUND/...)"
    )
    graph_info: Optional[GraphInfo] = Field(
        None,
        description="Graph information (None if graph not found)"
    )


class GraphCountsResponse(ResultStatus):
    """Response model for graph object counts.

    Carries the unified success/status/message contract (``success`` derived from
    ``status``). ``status`` defaults to FOUND.
    """
    status: OperationStatus = Field(
        OperationStatus.FOUND, description="Outcome discriminator (FOUND/...)"
    )
    entity_count: int = Field(0, description="Number of entities in the graph")
    frame_count: int = Field(0, description="Number of frames in the graph")
    relation_count: int = Field(0, description="Number of relations in the graph")


# SPARQL Query Models
class SPARQLQueryRequest(BaseModel):
    """Request model for SPARQL query operations."""
    query: str = Field(
        ...,
        description="SPARQL query string (SELECT, CONSTRUCT, ASK, or DESCRIBE)",
        example="SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10"
    )
    default_graph_uri: Optional[List[str]] = Field(
        None,
        description="Default graph URIs for the query",
        example=["http://example.org/graph1"]
    )
    named_graph_uri: Optional[List[str]] = Field(
        None,
        description="Named graph URIs for the query",
        example=["http://example.org/graph2"]
    )
    format: Optional[str] = Field(
        "application/sparql-results+json",
        description="Response format (application/sparql-results+json, text/csv, etc.)",
        example="application/sparql-results+json"
    )


class SPARQLQueryTiming(BaseModel):
    """Server-side stage breakdown for one SPARQL query, in milliseconds.

    These are measured inside the backend pipeline and were previously only
    written to a log line, which meant the one place that could explain a slow
    query was the one place a caller could not reach. Returning them lets a
    client attribute latency without shell access to the server: `total_ms`
    against the caller's own wall-clock shows transport and serialization
    overhead, and the stages show where server time went.

    Always populated for `sparql_sql` backend SELECT/ASK/CONSTRUCT/DESCRIBE
    queries; `None` for backends that do not report stages.
    """
    acquire_ms: Optional[float] = Field(
        None, description="Waiting for a connection from the pool")
    sidecar_ms: Optional[float] = Field(
        None, description="SPARQL→AST compilation by the Jena sidecar")
    gen_ms: Optional[float] = Field(
        None, description="SQL generation from the AST")
    exec_ms: Optional[float] = Field(
        None, description="SQL execution in PostgreSQL")
    rows_to_dict_ms: Optional[float] = Field(
        None, description="Converting result rows to dicts")
    bindings_ms: Optional[float] = Field(
        None, description="Building SPARQL JSON bindings from rows")
    total_ms: Optional[float] = Field(
        None, description="Server-side total across the stages above")
    rows: Optional[int] = Field(None, description="Result rows returned")
    joins: Optional[int] = Field(
        None, description="JOIN count in the generated SQL (complexity hint)")
    sql_chars: Optional[int] = Field(
        None, description="Length of the generated SQL")


class SPARQLQueryResponse(BaseModel):
    """Response model for SPARQL query results."""
    head: Optional[Dict[str, Any]] = Field(
        None,
        description="Query result metadata (variables, links)"
    )
    results: Optional[Dict[str, Any]] = Field(
        None,
        description="Query result bindings for SELECT queries"
    )
    boolean: Optional[bool] = Field(
        None,
        description="Boolean result for ASK queries"
    )
    triples: Optional[List[Dict[str, Any]]] = Field(
        None,
        description=(
            "RDF triples for CONSTRUCT/DESCRIBE queries. Each entry is "
            "{'subject': term, 'predicate': term, 'object': term}, where a "
            "term is a SPARQL JSON node — {'type': 'uri'|'literal'|'bnode', "
            "'value': str, and for literals optionally 'xml:lang'/'datatype'}. "
            "Values are nested objects, not strings."
        )
    )
    query_time: Optional[float] = Field(
        None,
        description="Query execution time in seconds, measured at the endpoint"
    )
    timing: Optional[SPARQLQueryTiming] = Field(
        None,
        description=(
            "Server-side stage breakdown in milliseconds. Always present for "
            "the sparql_sql backend; use with query_time to separate server "
            "cost from transport."
        )
    )
    error: Optional[str] = Field(
        None,
        description="Error message if query failed"
    )


# SPARQL Update Models
class SPARQLUpdateRequest(BaseModel):
    """Request model for SPARQL update operations."""
    update: str = Field(
        ...,
        description="SPARQL update string (INSERT, DELETE, LOAD, CLEAR, etc.)",
        example="INSERT DATA { <http://example.org/s> <http://example.org/p> <http://example.org/o> }"
    )
    using_graph_uri: Optional[List[str]] = Field(
        None,
        description="USING graph URIs for the update",
        example=["http://example.org/graph1"]
    )
    using_named_graph_uri: Optional[List[str]] = Field(
        None,
        description="USING NAMED graph URIs for the update",
        example=["http://example.org/graph2"]
    )


class SPARQLUpdateResponse(BaseOperationResponse):
    """Response model for SPARQL update results."""
    update_time: Optional[float] = Field(
        None,
        description="Update execution time in seconds"
    )
    error: Optional[str] = Field(
        None,
        description="Error message if update failed"
    )


# SPARQL Insert Models
class SPARQLInsertRequest(BaseModel):
    """Request model for SPARQL insert operations (W3C SPARQL 1.1 Protocol compliant)."""
    update: str = Field(
        ...,
        description="SPARQL update string (INSERT DATA, DELETE DATA, INSERT WHERE, etc.)",
        example="INSERT DATA { <http://example.org/s> <http://example.org/p> <http://example.org/o> }"
    )
    graph_uri: Optional[str] = Field(
        None,
        description="Target graph URI for the insert operation",
        example="http://example.org/graph1"
    )
    format: Optional[str] = Field(
        "application/n-triples",
        description="RDF format for data insertion",
        example="application/n-triples"
    )


class SPARQLInsertResponse(BaseOperationResponse):
    """Response model for SPARQL insert results."""
    insert_time: Optional[float] = Field(
        None,
        description="Insert execution time in seconds"
    )
    inserted_triples: Optional[int] = Field(
        None,
        description="Number of triples inserted"
    )
    error: Optional[str] = Field(
        None,
        description="Error message if insert failed"
    )


# SPARQL Delete Models
class SPARQLDeleteRequest(BaseModel):
    """Request model for SPARQL delete operations (W3C SPARQL 1.1 Protocol compliant)."""
    update: str = Field(
        ...,
        description="SPARQL update string (DELETE DATA, DELETE WHERE, etc.)",
        example="DELETE DATA { <http://example.org/s> <http://example.org/p> <http://example.org/o> }"
    )
    graph_uri: Optional[str] = Field(
        None,
        description="Target graph URI for the delete operation",
        example="http://example.org/graph1"
    )


class SPARQLDeleteResponse(BaseOperationResponse):
    """Response model for SPARQL delete results."""
    delete_time: Optional[float] = Field(
        None,
        description="Delete execution time in seconds"
    )
    deleted_triples: Optional[int] = Field(
        None,
        description="Number of triples deleted"
    )
    error: Optional[str] = Field(
        None,
        description="Error message if delete failed"
    )


# SPARQL Graph Operation Models
class SPARQLGraphRequest(BaseModel):
    """Request model for SPARQL graph operations."""
    operation: str = Field(
        ...,
        description="Graph operation (CREATE, DROP, CLEAR, COPY, MOVE, ADD)",
        example="CREATE"
    )
    source_graph_uri: Optional[str] = Field(
        None,
        description="Source graph URI for COPY, MOVE, ADD operations",
        example="http://example.org/source-graph"
    )
    target_graph_uri: Optional[str] = Field(
        None,
        description="Target graph URI for the operation",
        example="http://example.org/target-graph"
    )
    silent: bool = Field(
        False,
        description="Whether to execute operation silently (ignore errors)"
    )


class SPARQLGraphResponse(BaseOperationResponse):
    """Response model for SPARQL graph operation results."""
    operation_time: Optional[float] = Field(
        None,
        description="Graph operation execution time in seconds"
    )
    graphs_info: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Information about affected graphs"
    )
    error: Optional[str] = Field(
        None,
        description="Error message if graph operation failed"
    )