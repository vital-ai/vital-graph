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

from .jena_sidecar_client import SidecarClient
from .jena_ast_mapper import map_compile_response
from .jena_sql_generator import generate_sql
from .jena_types import CompileResult, VarNode, URINode, LiteralNode, BNodeNode
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


class SparqlOrchestrator:
    """
    Orchestrates SPARQL → SQL execution.

    Usage:
        orch = SparqlOrchestrator(space_id="lead_test")
        result = orch.execute("SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10")
        for row in result.rows:
            print(row)
        orch.close()
    """

    def __init__(
        self,
        space_id: str,
        sidecar_url: Optional[str] = None,
        db_params: Optional[Dict[str, Any]] = None,
        graph_uri: Optional[str] = None,
        optimize: bool = False,
    ):
        self.space_id = space_id
        self.db_params = db_params
        self.graph_uri = graph_uri
        self.optimize = optimize
        self.client = SidecarClient(base_url=sidecar_url)
        logger.info(
            "SparqlOrchestrator: space=%s graph=%s optimize=%s sidecar=%s",
            space_id, graph_uri, optimize, self.client.base_url,
        )

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def execute(self, sparql: str, include_sql: bool = False,
                sql_only: bool = False) -> QueryResult:
        """
        Execute a SPARQL query/update against PostgreSQL.

        Args:
            sparql: SPARQL query or update string.
            include_sql: If True, include the generated SQL in the result.
            sql_only: If True, generate SQL but skip execution.

        Returns:
            QueryResult with rows, columns, timing, etc.
        """
        timing = {}

        # Phase 1: Compile via sidecar
        try:
            t0 = time.monotonic()
            raw_json = self.client.compile(sparql)
            timing["sidecar_ms"] = (time.monotonic() - t0) * 1000
        except Exception as e:
            logger.error("Sidecar compile failed: %s", e)
            return QueryResult(ok=False, error=f"Sidecar error: {e}", timing=timing)

        # Phase 2: Map JSON → Python types
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

        # Open one connection for both generate (materialize) and execute phases
        with db.get_connection(self.db_params) as conn:

            # Phase 3: Generate SQL
            try:
                t0 = time.monotonic()
                sql = generate_sql(compile_result, self.space_id,
                                   conn_params=self.db_params, conn=conn,
                                   graph_uri=self.graph_uri,
                                   optimize=self.optimize)
                timing["generate_ms"] = (time.monotonic() - t0) * 1000
                if hasattr(generate_sql, 'last_timing'):
                    timing["generate_detail"] = generate_sql.last_timing
            except Exception as e:
                logger.error("SQL generation failed: %s", e)
                return QueryResult(
                    ok=False, error=f"SQL generation error: {e}",
                    sparql_form=sparql_form, query_type=query_type, timing=timing,
                )

            # sql_only: return generated SQL without executing
            if sql_only:
                return QueryResult(
                    ok=True, sql=sql,
                    sparql_form=sparql_form, query_type=query_type, timing=timing,
                )

            # Phase 4: Execute SQL
            try:
                t0 = time.monotonic()
                if sparql_form == "UPDATE":
                    self._execute_update(sql)
                    timing["execute_ms"] = (time.monotonic() - t0) * 1000
                    return QueryResult(
                        ok=True,
                        sparql_form=sparql_form, query_type=query_type,
                        sql=sql if include_sql else None,
                        timing=timing,
                    )
                else:
                    rows = db.execute_query(sql, conn_params=self.db_params, conn=conn)
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
                    )
            except Exception as e:
                logger.error("SQL execution failed: %s\nSQL: %s", e, sql[:500])
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

    def _execute_update(self, sql: str):
        """Execute one or more SQL update statements in a transaction."""
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        with db.get_connection(self.db_params) as conn:
            with conn.cursor() as cur:
                for stmt in statements:
                    cur.execute(stmt)
            conn.commit()
