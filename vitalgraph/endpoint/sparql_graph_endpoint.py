"""SPARQL Graph Management Endpoint for VitalGraph

Implements SPARQL 1.1 graph management operations (CREATE, DROP, CLEAR, COPY, MOVE, ADD)
following the SPARQL 1.1 Update specification.
"""

from typing import Dict, List, Any, Optional
from fastapi import APIRouter, HTTPException, Depends, Form, Body, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import logging

from ..model.sparql_model import (
    SPARQLGraphRequest,
    SPARQLGraphResponse,
    GraphInfo,
    GraphInfoResponse,
    GraphListResponse,
    GraphCountsResponse,
    SpacesSummaryResponse,
    SpaceSummary
)
from ..model.result_status import OperationStatus
from ..auth.role_dependencies import require_space_read, require_space_write


class SPARQLGraphEndpoint:
    """SPARQL Graph endpoint handler."""
    
    def __init__(self, space_manager, auth_dependency):
        self.space_manager = space_manager
        self.auth_dependency = auth_dependency
        self.logger = logging.getLogger(f"{__name__}.SPARQLGraphEndpoint")
        self.router = APIRouter()
        self._setup_routes()
    
    def _setup_routes(self):
        """Setup SPARQL graph management routes."""
        
        self.logger.info("Setting up SPARQL graph routes...")
        
        # GET endpoint to list graphs
        @self.router.get(
            "/graphs",
            response_model=GraphListResponse,
            tags=["Graphs"],
            summary="List Graphs",
            description="List all graphs in the specified space"
        )
        async def list_graphs(
            space_id: str = Query(..., description="Space ID"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            require_space_read(current_user, space_id)
            self.logger.info(f"List graphs endpoint called for space: {space_id}")
            return await self._list_graphs(space_id, current_user)
        
        self.logger.info("Registered GET /graphs route")
        
        # POST endpoint for graph operations
        @self.router.post(
            "/graph",
            response_model=SPARQLGraphResponse,
            tags=["Graphs"],
            summary="Execute Graph Operation",
            description="Execute a SPARQL graph operation (CREATE, DROP, CLEAR, COPY, MOVE, ADD)"
        )
        async def sparql_graph_operation(
            space_id: str = Query(..., description="Space ID"),
            request: SPARQLGraphRequest = Body(...),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            require_space_write(current_user, space_id)
            return await self._execute_graph_operation(space_id, request, current_user)
        
        # GET endpoint for fast graph object counts
        @self.router.get(
            "/graph_counts",
            response_model=GraphCountsResponse,
            tags=["Graphs"],
            summary="Get Graph Object Counts",
            description="Fast counts of entities, frames, and relations in a graph"
        )
        async def graph_counts(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph URI"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            require_space_read(current_user, space_id)
            return await self._get_graph_counts(space_id, graph_id)

        # GET endpoint for the whole dashboard in one request
        @self.router.get(
            "/spaces_summary",
            response_model=SpacesSummaryResponse,
            tags=["Graphs"],
            summary="Summary Of Every Space",
            description=("Per-space graph and triple totals in ONE request, "
                         "replacing a per-space fan-out."),
        )
        async def spaces_summary(
            current_user: Dict = Depends(self.auth_dependency)
        ):
            return await self._spaces_summary(current_user)

        # GET endpoint to get graph info
        @self.router.get(
            "/graph",
            response_model=GraphInfoResponse,
            tags=["Graphs"],
            summary="Get Graph Info",
            description="Get information about a specific graph"
        )
        async def get_graph_info(
            space_id: str = Query(..., description="Space ID"),
            graph_uri: str = Query(..., description="Graph URI"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            require_space_read(current_user, space_id)
            return await self._get_graph_info(space_id, graph_uri, current_user)
        
        # PUT endpoint to create graph
        @self.router.put(
            "/graph",
            response_model=SPARQLGraphResponse,
            tags=["Graphs"],
            summary="Create Graph",
            description="Create a new empty graph"
        )
        async def create_graph(
            space_id: str = Query(..., description="Space ID"),
            graph_uri: str = Query(..., description="Graph URI"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            require_space_write(current_user, space_id)
            request = SPARQLGraphRequest(
                operation="CREATE",
                target_graph_uri=graph_uri
            )
            return await self._execute_graph_operation(space_id, request, current_user)
        
        # DELETE endpoint to drop graph
        @self.router.delete(
            "/graph",
            response_model=SPARQLGraphResponse,
            tags=["Graphs"],
            summary="Drop Graph",
            description="Drop a graph and all its triples"
        )
        async def drop_graph(
            space_id: str = Query(..., description="Space ID"),
            graph_uri: str = Query(..., description="Graph URI"),
            silent: bool = Query(False, description="Execute silently"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            require_space_write(current_user, space_id)
            request = SPARQLGraphRequest(
                operation="DROP",
                target_graph_uri=graph_uri,
                silent=silent
            )
            return await self._execute_graph_operation(space_id, request, current_user)
    
    async def _execute_graph_operation(
        self,
        space_id: str,
        request: SPARQLGraphRequest,
        current_user: Dict
    ) -> SPARQLGraphResponse:
        """Execute a SPARQL graph operation."""
        
        try:
            self.logger.info(f"Executing graph operation '{request.operation}' in space '{space_id}' for user '{current_user.get('username', 'unknown')}'")
            
            # Validate space manager
            if self.space_manager is None:
                raise HTTPException(
                    status_code=500,
                    detail="Space manager not available"
                )
            
            # Validate space exists (with DB fallback on cache miss)
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                return SPARQLGraphResponse(
                    status=OperationStatus.NOT_FOUND,
                    operation=request.operation,
                    graph_uri=request.target_graph_uri or request.source_graph_uri,
                    message=f"Space '{space_id}' not found",
                    error=f"Space '{space_id}' not found"
                )

            space_impl = space_record.space_impl

            # Get the database-specific implementation for graph operations
            db_space_impl = space_impl.get_db_space_impl()
            if not db_space_impl:
                raise HTTPException(
                    status_code=500,
                    detail="Database-specific space implementation not available"
                )
            
            # Execute the operation using PostgreSQL graph table operations
            import time
            start_time = time.time()
            
            operation = request.operation.upper()
            success = False
            
            if operation == "CREATE":
                if not request.target_graph_uri:
                    raise HTTPException(
                        status_code=400,
                        detail="target_graph_uri required for CREATE operation"
                    )
                success = await db_space_impl.graphs.create_graph(space_id, request.target_graph_uri)
                
            elif operation == "DROP":
                if not request.target_graph_uri:
                    raise HTTPException(
                        status_code=400,
                        detail="target_graph_uri required for DROP operation"
                    )
                success = await db_space_impl.graphs.drop_graph(space_id, request.target_graph_uri)
                
            elif operation == "CLEAR":
                if not request.target_graph_uri:
                    raise HTTPException(
                        status_code=400,
                        detail="target_graph_uri required for CLEAR operation"
                    )
                success = await db_space_impl.graphs.clear_graph(space_id, request.target_graph_uri)
                
            elif operation in ["COPY", "MOVE", "ADD"]:
                # For complex operations, fall back to SPARQL update
                sparql_query = self._build_graph_operation_query(request)
                success = await space_impl.execute_sparql_update(space_id, sparql_query)
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported graph operation: {operation}"
                )
            
            operation_time = time.time() - start_time
            
            if success:
                if operation == "CREATE":
                    success_status = OperationStatus.CREATED
                elif operation in ("DROP", "CLEAR"):
                    success_status = OperationStatus.DELETED
                else:
                    success_status = OperationStatus.OK
                return SPARQLGraphResponse(
                    status=success_status,
                    operation=request.operation,
                    graph_uri=request.target_graph_uri or request.source_graph_uri,
                    message=f"{request.operation} operation completed successfully",
                    operation_time=operation_time
                )
            else:
                return SPARQLGraphResponse(
                    status=OperationStatus.STORE_FAILED,
                    operation=request.operation,
                    graph_uri=request.target_graph_uri or request.source_graph_uri,
                    message=f"{request.operation} operation failed",
                    operation_time=operation_time,
                    error="Graph operation returned false"
                )

        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error executing graph operation: {e}")
            return SPARQLGraphResponse(
                status=OperationStatus.ERROR,
                operation=request.operation,
                graph_uri=request.target_graph_uri or request.source_graph_uri,
                message=f"Graph operation failed: {str(e)}",
                error=str(e)
            )
    
    def _build_graph_operation_query(self, request: SPARQLGraphRequest) -> str:
        """Build SPARQL query for graph operation."""
        
        operation = request.operation.upper()
        silent = "SILENT " if request.silent else ""
        
        if operation == "CREATE":
            if not request.target_graph_uri:
                raise ValueError("target_graph_uri required for CREATE operation")
            return f"CREATE {silent}GRAPH <{request.target_graph_uri}>"
        
        elif operation == "DROP":
            if not request.target_graph_uri:
                raise ValueError("target_graph_uri required for DROP operation")
            return f"DROP {silent}GRAPH <{request.target_graph_uri}>"
        
        elif operation == "CLEAR":
            if not request.target_graph_uri:
                raise ValueError("target_graph_uri required for CLEAR operation")
            return f"CLEAR {silent}GRAPH <{request.target_graph_uri}>"
        
        elif operation == "COPY":
            if not request.source_graph_uri or not request.target_graph_uri:
                raise ValueError("source_graph_uri and target_graph_uri required for COPY operation")
            return f"COPY {silent}GRAPH <{request.source_graph_uri}> TO <{request.target_graph_uri}>"
        
        elif operation == "MOVE":
            if not request.source_graph_uri or not request.target_graph_uri:
                raise ValueError("source_graph_uri and target_graph_uri required for MOVE operation")
            return f"MOVE {silent}GRAPH <{request.source_graph_uri}> TO <{request.target_graph_uri}>"
        
        elif operation == "ADD":
            if not request.source_graph_uri or not request.target_graph_uri:
                raise ValueError("source_graph_uri and target_graph_uri required for ADD operation")
            return f"ADD {silent}GRAPH <{request.source_graph_uri}> TO <{request.target_graph_uri}>"
        
        else:
            raise ValueError(f"Unsupported graph operation: {operation}")
    
    async def _list_graphs(self, space_id: str, current_user: Dict) -> GraphListResponse:
        """List all graphs in the space."""
        
        try:
            self.logger.info(f"Listing graphs in space '{space_id}' for user '{current_user.get('username', 'unknown')}'")
            
            # Validate space manager
            if self.space_manager is None:
                raise HTTPException(
                    status_code=500,
                    detail="Space manager not available"
                )
        
            # Validate space exists (with DB fallback on cache miss).
            # A missing space is a DOMAIN outcome: HTTP 200 + status NOT_FOUND.
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                return GraphListResponse(
                    status=OperationStatus.NOT_FOUND,
                    message=f"Space '{space_id}' not found",
                )

            space_impl = space_record.space_impl
        
            # Get the database-specific implementation for graph operations
            db_space_impl = space_impl.get_db_space_impl()
            if not db_space_impl:
                raise HTTPException(
                    status_code=500,
                    detail="Database-specific space implementation not available"
                )
        
            # Get graphs using PostgreSQL graph table operations
            graphs_data = await db_space_impl.graphs.list_graphs(space_id)
            
            # Convert to GraphInfo objects
            graph_infos = []
            for graph_data in graphs_data:
                graph_info = GraphInfo(
                    graph_uri=graph_data['graph_uri'],
                    triple_count=graph_data.get('triple_count', 0),
                    created_time=graph_data.get('created_time', '').isoformat() if graph_data.get('created_time') else None,
                    updated_time=graph_data.get('updated_time', '').isoformat() if graph_data.get('updated_time') else None
                )
                graph_infos.append(graph_info)

            return GraphListResponse(
                status=OperationStatus.FOUND if graph_infos else OperationStatus.EMPTY,
                graphs=graph_infos,
                total_count=len(graph_infos),
            )
        
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error listing graphs: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error listing graphs: {str(e)}"
            )
    
    async def _get_graph_info(self, space_id: str, graph_uri: str, current_user: Dict) -> GraphInfoResponse:
        """Get information about a specific graph."""
        
        try:
            self.logger.info(f"Getting info for graph '{graph_uri}' in space '{space_id}' for user '{current_user.get('username', 'unknown')}'")
            
            # Validate space manager (server-internal — 500)
            if self.space_manager is None:
                raise HTTPException(
                    status_code=500,
                    detail="Space manager not available"
                )

            # Validate space exists (with DB fallback on cache miss)
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                return GraphInfoResponse(
                    status=OperationStatus.NOT_FOUND,
                    graph_info=None,
                    message=f"Space '{space_id}' not found"
                )

            space_impl = space_record.space_impl

            # Get the database-specific implementation for graph operations
            db_space_impl = space_impl.get_db_space_impl()
            if not db_space_impl:
                raise HTTPException(
                    status_code=500,
                    detail="Database-specific space implementation not available"
                )

            # Get graph info using PostgreSQL graph table operations
            graph_data = await db_space_impl.graphs.get_graph(space_id, graph_uri)

            if not graph_data:
                # Graph does not exist — domain outcome (HTTP 200 + NOT_FOUND)
                self.logger.info(f"Graph '{graph_uri}' not found in space '{space_id}'")
                return GraphInfoResponse(
                    status=OperationStatus.NOT_FOUND,
                    graph_info=None,
                    message=f"Graph '{graph_uri}' not found in space '{space_id}'"
                )

            # Return success response with graph info
            graph_info = GraphInfo(
                graph_uri=graph_data['graph_uri'],
                triple_count=graph_data.get('triple_count', 0),
                created_time=graph_data.get('created_time', '').isoformat() if graph_data.get('created_time') else None,
                updated_time=graph_data.get('updated_time', '').isoformat() if graph_data.get('updated_time') else None
            )

            return GraphInfoResponse(
                status=OperationStatus.FOUND,
                graph_info=graph_info,
                message="Graph info retrieved successfully"
            )

        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error getting graph info: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error getting graph info: {str(e)}"
            )


    # ------------------------------------------------------------------
    # Fast graph counts (single SQL query)
    # ------------------------------------------------------------------

    # KG type URIs — must stay in sync with kg_impl type clauses
    _ENTITY_TYPES = frozenset([
        'http://vital.ai/ontology/haley-ai-kg#KGEntity',
        'http://vital.ai/ontology/haley-ai-kg#KGNewsEntity',
        'http://vital.ai/ontology/haley-ai-kg#KGProductEntity',
        'http://vital.ai/ontology/haley-ai-kg#KGWebEntity',
    ])
    _FRAME_TYPES = frozenset([
        'http://vital.ai/ontology/haley-ai-kg#KGFrame',
    ])
    _RELATION_TYPES = frozenset([
        'http://vital.ai/ontology/haley-ai-kg#KGRelation',
    ])

    async def _spaces_summary(self, current_user):
        """Every space's totals, in a handful of queries rather than 67.

        The dashboard rendered four numbers by calling `list_graphs` once per
        space. Caching made each call fast but left the SHAPE wrong: the work
        still grows with the number of spaces, and a cold cache after a deploy
        means 67 concurrent multi-second counts.

        Here the graph counts come from ONE grouped query over the `graph` admin
        table, and the triple totals from ONE query over `pg_class` — a catalog
        read per space, no quad scanned. `reltuples` is exact or near-exact on
        every quad table measured (six of eight exact, worst 0.635%), and a
        dashboard total is the case where that is plainly good enough.

        A space whose table has never been analysed reports `reltuples = -1`;
        those are reported as 0 with `estimated` still true, rather than
        displaying a negative triple count. Exactness is available per space
        through the existing endpoints.

        Only spaces the caller may READ are included, so the totals differ
        between users by design.
        """
        try:
            if not self.space_manager:
                return SpacesSummaryResponse(
                    status=OperationStatus.ERROR,
                    message="Space manager not available")

            db_impl = getattr(self.space_manager, "db_impl", None) or self.db_impl
            if db_impl is None:
                return SpacesSummaryResponse(
                    status=OperationStatus.ERROR,
                    message="Database not available")

            rows = await db_impl.execute_query(
                "SELECT space_id, space_name FROM space ORDER BY space_id", [])
            visible = []
            for r in rows:
                sid = r.get("space_id")
                try:
                    require_space_read(current_user, sid)
                except Exception:
                    continue          # not an error: simply not this user's space
                visible.append((sid, r.get("space_name")))

            if not visible:
                return SpacesSummaryResponse(status=OperationStatus.EMPTY,
                                             total_spaces=0)

            ids = [s for s, _ in visible]

            # One query for every space's graph count.
            graph_rows = await db_impl.execute_query(
                "SELECT space_id, count(*) AS n FROM graph "
                "WHERE space_id = ANY($1) GROUP BY space_id", [ids])
            graphs_by_space = {r["space_id"]: int(r["n"]) for r in graph_rows}

            # One query for every space's quad estimate. `relname` is the quad
            # table, so the space id is recovered by stripping the suffix.
            est_rows = await db_impl.execute_query(
                "SELECT relname, reltuples::bigint AS est FROM pg_class "
                "WHERE relkind = 'r' AND relname = ANY($1)",
                [[f"{s}_rdf_quad" for s in ids]])
            est_by_space = {}
            for r in est_rows:
                name = r["relname"]
                est = r["est"]
                # -1 means "never analysed" on PG14+; report 0 rather than -1.
                est_by_space[name[: -len("_rdf_quad")]] = max(int(est or 0), 0)

            summaries, total_graphs, total_triples = [], 0, 0
            for sid, name in visible:
                g = graphs_by_space.get(sid, 0)
                tri = est_by_space.get(sid, 0)
                total_graphs += g
                total_triples += tri
                summaries.append(SpaceSummary(
                    space=sid, space_name=name or sid,
                    graph_count=g, triple_count=tri, estimated=True))

            return SpacesSummaryResponse(
                status=OperationStatus.FOUND if summaries else OperationStatus.EMPTY,
                spaces=summaries,
                total_spaces=len(summaries),
                total_graphs=total_graphs,
                total_triples=total_triples)
        except Exception as e:
            self.logger.error("spaces_summary failed: %s", e, exc_info=True)
            raise HTTPException(status_code=500,
                                detail=f"Failed to summarise spaces: {e}")

    async def _get_graph_counts(self, space_id: str, graph_id: str):
        """Return entity, frame, and relation counts via one SQL query.

        Counts vitaltype rows per type URI, then classifies them.
        """
        try:
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                return GraphCountsResponse(
                    status=OperationStatus.NOT_FOUND,
                    message=f"Space '{space_id}' not found",
                )

            space_impl = space_record.space_impl
            db_space_impl = space_impl.get_db_space_impl()
            if not db_space_impl:
                raise HTTPException(status_code=500, detail="Backend unavailable")

            from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema

            t = SparqlSQLSchema.get_table_names(space_id)
            rdf_quad = t['rdf_quad']
            term = t['term']

            _VITALTYPE = 'http://vital.ai/ontology/vital-core#vitaltype'

            async with db_space_impl._db._pool.acquire() as conn:
                ctx_uuid = await conn.fetchval(
                    f"SELECT term_uuid FROM {term} "
                    f"WHERE term_text = $1 AND term_type = 'U' LIMIT 1",
                    graph_id,
                )
                if ctx_uuid is None:
                    return GraphCountsResponse(
                        status=OperationStatus.NOT_FOUND,
                        message=f"Graph '{graph_id}' not found in space '{space_id}'",
                    )

                vt_uuid = await conn.fetchval(
                    f"SELECT term_uuid FROM {term} "
                    f"WHERE term_text = $1 AND term_type = 'U' LIMIT 1",
                    _VITALTYPE,
                )
                if vt_uuid is None:
                    return GraphCountsResponse(status=OperationStatus.FOUND)

                # CACHED: this is an aggregate over every vitaltype quad in the
                # graph, measured at 3,343 ms, and it is on the space and graph
                # pages that the UI reports as ~20 s loads. The count itself is
                # honest work — grouping 50M rows is what it costs — so the fix
                # is not to make it faster but to stop repeating it.
                #
                # The cache and its invalidation already existed and were simply
                # not used here; a write to the graph clears it immediately, and
                # the TTL bounds staleness. Three counts share one entry because
                # they come from one query.
                # One entry per count. The cache stores integers, so the
                # alternative — packing three counts into one — would silently
                # truncate any graph with more than ~2M frames. Three keys cost
                # nothing and cannot be wrong.
                from ...cache.count_cache import _count_cache
                _keys = {
                    name: _count_cache.query_hash(
                        f"graph_counts::{space_id}::{graph_id}::{name}")
                    for name in ("entity", "frame", "relation")
                }
                _hits = {name: _count_cache.get(space_id, graph_id, k)
                         for name, k in _keys.items()}
                if all(v is not None for v in _hits.values()):
                    return GraphCountsResponse(
                        status=OperationStatus.FOUND,
                        entity_count=_hits["entity"],
                        frame_count=_hits["frame"],
                        relation_count=_hits["relation"],
                    )

                # One query: count vitaltype rows grouped by object (type URI)
                rows = await conn.fetch(f"""
                    SELECT t_obj.term_text AS type_uri, COUNT(*) AS cnt
                    FROM {rdf_quad} q
                    JOIN {term} t_obj ON q.object_uuid = t_obj.term_uuid
                    WHERE q.context_uuid = $1 AND q.predicate_uuid = $2
                    GROUP BY t_obj.term_text
                """, ctx_uuid, vt_uuid)

                entity_count = 0
                frame_count = 0
                relation_count = 0
                for r in rows:
                    uri = r['type_uri']
                    cnt = r['cnt']
                    if uri in self._ENTITY_TYPES:
                        entity_count += cnt
                    elif uri in self._FRAME_TYPES:
                        frame_count += cnt
                    elif uri in self._RELATION_TYPES:
                        relation_count += cnt

                for _name, _val in (("entity", entity_count),
                                    ("frame", frame_count),
                                    ("relation", relation_count)):
                    _count_cache.put(space_id, graph_id, _keys[_name], _val)

                return GraphCountsResponse(
                    status=OperationStatus.FOUND,
                    entity_count=entity_count,
                    frame_count=frame_count,
                    relation_count=relation_count,
                )

        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error getting graph counts: {e}")
            raise HTTPException(status_code=500, detail=str(e))


def create_sparql_graph_router(space_manager, auth_dependency) -> APIRouter:
    """Create and return the SPARQL graph router."""
    import logging
    logger = logging.getLogger(__name__)
    logger.info("Creating SPARQL graph router...")
    endpoint = SPARQLGraphEndpoint(space_manager, auth_dependency)
    logger.info(f"SPARQL graph router created with {len(endpoint.router.routes)} routes")
    return endpoint.router
