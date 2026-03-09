"""
Top-level orchestrator: SPARQL string → PostgreSQL execution → results.

Wires together:
  1. SidecarClient  — SPARQL → JSON
  2. jena_ast_mapper — JSON → Python Op tree
  3. jena_sql_generator — Op tree → PostgreSQL SQL
  4. db.execute_query — SQL → result rows
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
from vitalgraph.db.jena_sparql.jena_types import VarNode, URINode, LiteralNode, BNodeNode
from . import db

logger = logging.getLogger(__name__)


@dataclass
class QueryResult:
    """Result of a SPARQL query execution."""
    ok: bool
    rows: List[Dict[str, Any]] = field(default_factory=list)
    columns: List[str] = field(default_factory=list)
    row_count: int = 0
    sparql_form: Optional[str] = None  # QUERY or UPDATE
    query_type: Optional[str] = None  # SELECT, CONSTRUCT, ASK, DESCRIBE
    sql: Optional[str] = None  # generated SQL (for debugging)
    error: Optional[str] = None
    timing: Optional[Dict[str, float]] = None  # ms for each phase
    boolean: Optional[bool] = None  # ASK result
    triples: List[Dict[str, Any]] = field(default_factory=list)  # CONSTRUCT/DESCRIBE
    # SPARQL→SQL variable name mapping (opaque sql col → original SPARQL name)
    var_map: Dict[str, str] = field(default_factory=dict)
    sparql_vars: List[str] = field(default_factory=list)


class SparqlOrchestrator:
    """
    Async orchestrator: SPARQL string → PostgreSQL execution → results.

    Uses native async throughout: httpx.AsyncClient for the sidecar,
    asyncpg for PostgreSQL.

    Usage:
        orch = SparqlOrchestrator(space_id="lead_test")
        result = await orch.execute("SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10")
        for row in result.rows:
            print(row)
        await orch.close()
    """

    def __init__(
        self,
        space_id: str,
        sidecar_url: Optional[str] = None,
        db_params: Optional[Dict[str, Any]] = None,
        graph_uri: Optional[str] = None,
    ):
        from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
        self.space_id = space_id
        self.db_params = db_params
        self.graph_uri = graph_uri
        self.client = AsyncSidecarClient(base_url=sidecar_url)

        # Ensure the pipeline's db_provider is configured with a DbImplInterface
        from vitalgraph.db.sparql_sql import db_provider
        if not db_provider.is_configured():
            from .db import DevDbImpl
            self._dev_db_impl = DevDbImpl(db_params)
            # connect() is async — defer to first execute() call
            self._dev_db_impl_needs_connect = True

        logger.info(
            "SparqlOrchestrator: space=%s graph=%s sidecar=%s",
            space_id, graph_uri, self.client.base_url,
        )

    async def close(self):
        await self.client.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()

    async def _ensure_db_provider(self):
        """Lazily connect and configure db_provider if using DevDbImpl."""
        if getattr(self, '_dev_db_impl_needs_connect', False):
            from vitalgraph.db.sparql_sql import db_provider
            await self._dev_db_impl.connect()
            db_provider.configure(self._dev_db_impl)
            self._dev_db_impl_needs_connect = False

    async def execute(self, sparql: str, include_sql: bool = False,
                      sql_only: bool = False) -> QueryResult:
        """
        Execute a SPARQL query/update against PostgreSQL asynchronously.

        Args:
            sparql: SPARQL query or update string.
            include_sql: If True, include the generated SQL in the result.
            sql_only: If True, generate SQL but skip execution.

        Returns:
            QueryResult with rows, columns, timing, etc.
        """
        await self._ensure_db_provider()
        timing = {}

        # Phase 1: Compile via sidecar (async HTTP)
        try:
            t0 = time.monotonic()
            raw_json = await self.client.compile(sparql)
            timing["sidecar_ms"] = (time.monotonic() - t0) * 1000
        except Exception as e:
            logger.error("Sidecar compile failed: %s", e)
            return QueryResult(ok=False, error=f"Sidecar error: {e}", timing=timing)

        # Phase 2: Map JSON → Python types (pure, no I/O)
        try:
            t0 = time.monotonic()
            compile_result = map_compile_response(raw_json)
            timing["mapper_ms"] = (time.monotonic() - t0) * 1000
        except Exception as e:
            logger.error("AST mapping failed: %s", e)
            return QueryResult(ok=False, error=f"Mapper error: {e}", timing=timing)

        if not compile_result.ok:
            return QueryResult(
                ok=False,
                error=f"SPARQL parse error: {compile_result.error}",
                sparql_form=getattr(compile_result.meta, 'sparql_form', None),
                timing=timing,
            )

        sparql_form = compile_result.meta.sparql_form if compile_result.meta else None
        query_type = compile_result.meta.query_type if compile_result.meta else None

        # Open one async connection for both generate and execute
        async with db.get_connection(self.db_params) as conn:

            # Phase 3: Generate SQL (async for constant materialization)
            try:
                from vitalgraph.db.sparql_sql.generator import generate_sql as v2_generate_sql
                t0 = time.monotonic()
                gen_result = await v2_generate_sql(
                    compile_result, self.space_id,
                    conn_params=self.db_params, conn=conn,
                    graph_lock_uri=self.graph_uri,
                )
                sql = gen_result.sql
                var_map = gen_result.var_map
                sparql_vars = gen_result.sparql_vars
                timing["generate_ms"] = (time.monotonic() - t0) * 1000
            except Exception as e:
                logger.error("Async SQL generation failed: %s", e)
                return QueryResult(
                    ok=False, error=f"SQL generation error: {e}",
                    sparql_form=sparql_form, query_type=query_type, timing=timing,
                )

            if sql_only:
                return QueryResult(
                    ok=True, sql=sql,
                    sparql_form=sparql_form, query_type=query_type, timing=timing,
                )

            # Phase 4: Execute SQL (async)
            # Adaptive planner hints
            _JOIN_COLLAPSE_DEFAULT = 8
            _MAX_EXHAUSTIVE = 14
            quad_table = f"{self.space_id}_rdf_quad"
            edge_mv_table = f"{self.space_id}_edge_mv"
            femv_table = f"{self.space_id}_frame_entity_mv"
            join_count = sql.count(quad_table) + sql.count(edge_mv_table) + sql.count(femv_table)
            if _JOIN_COLLAPSE_DEFAULT < join_count <= _MAX_EXHAUSTIVE:
                limit = join_count + 1
                await conn.execute(f"SET LOCAL join_collapse_limit = {limit}")
                await conn.execute(f"SET LOCAL geqo_threshold = {limit}")
                logger.debug("Planner hints: join_collapse_limit=%d geqo_threshold=%d "
                             "for %d-table query", limit, limit, join_count)
            elif join_count > _MAX_EXHAUSTIVE:
                await conn.execute(f"SET LOCAL geqo_threshold = {join_count + 1}")
                logger.debug("Planner hints: geqo OFF (threshold=%d) "
                             "for %d-table query", join_count + 1, join_count)

            try:
                t0 = time.monotonic()
                if sparql_form == "UPDATE":
                    await self._execute_update(sql)
                    timing["execute_ms"] = (time.monotonic() - t0) * 1000
                    return QueryResult(
                        ok=True,
                        sparql_form=sparql_form, query_type=query_type,
                        sql=sql if include_sql else None,
                        timing=timing,
                    )
                else:
                    rows = await db.execute_query(
                        sql, conn_params=self.db_params, conn=conn)
                    timing["execute_ms"] = (time.monotonic() - t0) * 1000
                    columns = list(rows[0].keys()) if rows else []

                    # ASK: return boolean
                    if query_type == "ASK":
                        bool_val = bool(rows and rows[0].get("result", False))
                        return QueryResult(
                            ok=True, boolean=bool_val,
                            rows=rows, columns=columns, row_count=1,
                            sparql_form=sparql_form, query_type=query_type,
                            sql=sql if include_sql else None, timing=timing,
                        )

                    # CONSTRUCT: apply template to result rows
                    if query_type == "CONSTRUCT" and compile_result.meta:
                        triples = self._apply_construct_template(
                            rows, compile_result.meta.construct_template
                        )
                        return QueryResult(
                            ok=True, triples=triples,
                            rows=rows, columns=columns, row_count=len(rows),
                            sparql_form=sparql_form, query_type=query_type,
                            sql=sql if include_sql else None, timing=timing,
                        )

                    # DESCRIBE: rows are already triples
                    if query_type == "DESCRIBE":
                        triples = [
                            {"subject": r.get("subject"),
                             "predicate": r.get("predicate"),
                             "object": r.get("object"),
                             "object_type": r.get("object_type"),
                             "object_lang": r.get("object_lang"),
                             "object_datatype": r.get("object_datatype")}
                            for r in rows
                        ]
                        return QueryResult(
                            ok=True, triples=triples,
                            rows=rows, columns=columns, row_count=len(rows),
                            sparql_form=sparql_form, query_type=query_type,
                            sql=sql if include_sql else None, timing=timing,
                        )

                    # SELECT (default)
                    return QueryResult(
                        ok=True,
                        rows=rows, columns=columns, row_count=len(rows),
                        sparql_form=sparql_form, query_type=query_type,
                        sql=sql if include_sql else None, timing=timing,
                        var_map=var_map, sparql_vars=sparql_vars,
                    )
            except Exception as e:
                logger.error("Async SQL execution failed: %s\nSQL: %s", e, sql[:500])
                return QueryResult(
                    ok=False,
                    error=f"SQL execution error: {e}",
                    sparql_form=sparql_form, query_type=query_type,
                    sql=sql if include_sql else None, timing=timing,
                )

    def _apply_construct_template(self, rows, template) -> List[Dict[str, Any]]:
        """Apply a CONSTRUCT template to query result rows to produce triples."""
        triples = []
        for row in rows:
            for tp in template:
                s = self._resolve_template_node(tp.subject, row)
                p = self._resolve_template_node(tp.predicate, row)
                o = self._resolve_template_node(tp.object, row)
                if s is not None and p is not None and o is not None:
                    triples.append({"subject": s, "predicate": p, "object": o})
        return triples

    @staticmethod
    def _resolve_template_node(node, row) -> Optional[str]:
        """Resolve a CONSTRUCT template node against a result row."""
        if isinstance(node, VarNode):
            return row.get(node.name)
        elif isinstance(node, URINode):
            return node.value
        elif isinstance(node, LiteralNode):
            return node.value
        elif isinstance(node, BNodeNode):
            return node.label
        return None

    async def _execute_update(self, sql: str):
        """Execute one or more SQL update statements in a transaction."""
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        async with db.get_connection(self.db_params) as conn:
            async with conn.transaction():
                for stmt in statements:
                    await conn.execute(stmt)
