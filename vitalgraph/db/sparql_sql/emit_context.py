"""
EmitContext + Processing Trace — the v2 pipeline's state and debugging backbone.

EmitContext carries all mutable state through the recursive emit pass:
  - TypeRegistry for companion column management
  - AliasGenerator for SQL naming
  - ProcessingTrace for structured pipeline logging

ProcessingTrace records every step the pipeline takes, enabling:
  - Structural testing (assert on trace without SQL execution)
  - Debugging (print_tree() shows full processing history)
  - JSON export for test comparison across runs
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .ir import AliasGenerator
from .sql_type_generation import TypeRegistry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TraceStep — one step in the processing history
# ---------------------------------------------------------------------------

@dataclass
class TraceStep:
    """A single step in the pipeline's processing trace."""
    depth: int              # Nesting depth (0 = outermost)
    phase: str              # "collect", "emit", "resolve", etc.
    plan_kind: str          # The PlanV2.kind being processed
    message: str            # Human-readable description
    details: Optional[Dict[str, Any]] = None  # Structured data
    timestamp: float = field(default_factory=time.monotonic)
    sql_fragment: Optional[str] = None  # SQL generated at this step
    column_map: Optional[Dict[str, str]] = None  # var → sql_col at this step

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "depth": self.depth,
            "phase": self.phase,
            "plan_kind": self.plan_kind,
            "message": self.message,
        }
        if self.details:
            d["details"] = self.details
        if self.sql_fragment:
            d["sql"] = self.sql_fragment
        if self.column_map:
            d["columns"] = self.column_map
        return d


# ---------------------------------------------------------------------------
# ProcessingTrace — the full processing history
# ---------------------------------------------------------------------------

class ProcessingTrace:
    """Records the pipeline's processing steps for debugging and testing."""

    def __init__(self, sparql_query: str = ""):
        self.steps: List[TraceStep] = []
        self.sparql_query: str = sparql_query
        self._start_time: float = time.monotonic()

    def add(self, depth: int, phase: str, plan_kind: str,
            message: str, **kwargs) -> TraceStep:
        """Record a processing step."""
        step = TraceStep(
            depth=depth, phase=phase, plan_kind=plan_kind,
            message=message, **kwargs,
        )
        self.steps.append(step)
        return step

    def log_step(self, depth: int, phase: str, plan_kind: str,
                 message: str, **kwargs) -> TraceStep:
        """Record and log a processing step."""
        step = self.add(depth, phase, plan_kind, message, **kwargs)
        indent = "  " * depth
        logger.debug("%s[%s] %s: %s", indent, phase, plan_kind, message)
        return step

    def log_sql(self, depth: int, plan_kind: str, sql: str) -> TraceStep:
        """Record a SQL fragment produced at a step."""
        step = self.add(depth, "emit", plan_kind,
                        f"SQL ({len(sql)} chars)",
                        sql_fragment=sql[:500])
        indent = "  " * depth
        logger.debug("%sSQL: %s", indent, sql[:200])
        return step

    def log_column_map(self, depth: int, plan_kind: str,
                        columns: Dict[str, str]) -> TraceStep:
        """Record the column map at a step."""
        return self.add(depth, "emit", plan_kind,
                        f"columns: {list(columns.keys())}",
                        column_map=columns)

    def log_scope(self, depth: int, plan_kind: str,
                   visible_vars: List[str]) -> TraceStep:
        """Record variable visibility at a step."""
        return self.add(depth, "emit", plan_kind,
                        f"scope: {visible_vars}",
                        details={"visible_vars": visible_vars})

    def summary(self) -> str:
        """One-line summary of the trace."""
        elapsed = (time.monotonic() - self._start_time) * 1000
        return (f"{len(self.steps)} steps, "
                f"{elapsed:.1f}ms, "
                f"max depth {self.max_depth()}")

    def max_depth(self) -> int:
        """Maximum nesting depth recorded."""
        if not self.steps:
            return 0
        return max(s.depth for s in self.steps)

    def steps_at_depth(self, depth: int) -> List[TraceStep]:
        """Return steps at a specific depth."""
        return [s for s in self.steps if s.depth == depth]

    def steps_for_kind(self, plan_kind: str) -> List[TraceStep]:
        """Return steps for a specific plan kind."""
        return [s for s in self.steps if s.plan_kind == plan_kind]

    def steps_for_phase(self, phase: str) -> List[TraceStep]:
        """Return steps for a specific phase (e.g., 'dispatch', 'columns')."""
        return [s for s in self.steps if s.phase == phase]

    def find_step(self, phase: Optional[str] = None,
                  plan_kind: Optional[str] = None) -> Optional[TraceStep]:
        """Find the first step matching the given criteria."""
        for s in self.steps:
            if phase and s.phase != phase:
                continue
            if plan_kind and s.plan_kind != plan_kind:
                continue
            return s
        return None

    def final_column_map(self) -> Dict[str, Any]:
        """Return the column map from the last 'columns' phase step.

        This is the primary API for §8.4 structural testing — inspect
        the final variable→column mapping without executing SQL.
        """
        for s in reversed(self.steps):
            if s.phase == "columns" and s.column_map:
                return dict(s.column_map)
        return {}

    def print_tree(self) -> str:
        """Pretty-print the processing trace as a tree.

        Format matches §8.3 example:
          [0] DISPATCH project
          [1]   BGP: quad=q0, vars={s,o}
          [1]   COLUMNS: s→v0 (U, uuid), o→v1 (L, dt=xsd:integer)
          [0] FINAL var_map: {v0: "s", v2: "z"}
        """
        lines = []
        if self.sparql_query:
            lines.append(f"SPARQL: {self.sparql_query.strip()[:120]}")
        for step in self.steps:
            indent = "  " * step.depth
            tag = step.phase.upper()
            lines.append(f"[{step.depth}]{indent} {tag} {step.plan_kind}: {step.message}")
            if step.sql_fragment:
                sql_preview = step.sql_fragment[:120].replace("\n", " ")
                lines.append(f"[{step.depth}]{indent}   sql: {sql_preview}")
        return "\n".join(lines)

    def to_json(self) -> str:
        """Serialize the trace to JSON for test comparison."""
        return json.dumps(
            {"steps": [s.to_dict() for s in self.steps]},
            indent=2,
        )

    def column_map_at(self, step_index: int) -> Optional[Dict[str, str]]:
        """Return the column map at a specific step, or None."""
        if 0 <= step_index < len(self.steps):
            return self.steps[step_index].column_map
        return None


# ---------------------------------------------------------------------------
# EmitContext — the v2 pipeline's mutable state
# ---------------------------------------------------------------------------

class EmitContext:
    """Carries all state through the recursive v2 emit pass.

    This is the central coordination point. Handlers receive an EmitContext
    and use it to:
      - Manage companion columns (types)
      - Generate SQL aliases (aliases)
      - Record processing steps (trace)
      - Track variable visibility (var_map)
    """

    def __init__(
        self,
        space_id: str,
        aliases: Optional[AliasGenerator] = None,
        types: Optional[TypeRegistry] = None,
        trace: Optional[ProcessingTrace] = None,
        graph_lock_uri: Optional[str] = None,
        base_uri: Optional[str] = None,
        trace_enabled: bool = True,
        datatype_cache: Optional[Dict[int, str]] = None,
        text_needed_vars: Optional[set] = None,
    ):
        self.space_id = space_id
        self.aliases = aliases or AliasGenerator()
        self.types = types or TypeRegistry(aliases=self.aliases)
        self.trace = trace or ProcessingTrace()
        self.graph_lock_uri = graph_lock_uri
        self.base_uri = base_uri
        self.trace_enabled = trace_enabled
        self._depth: int = 0
        # datatype_id (bigint) → datatype_uri (text) mapping, loaded once
        # from {space}_datatype table at generation time.
        self.datatype_cache: Dict[int, str] = datatype_cache or {}
        # Pre-built reverse map: datatype_uri → datatype_id
        self._dt_uri_to_id: Dict[str, int] = (
            {uri: did for did, uri in self.datatype_cache.items()}
            if self.datatype_cache else {}
        )
        # Variables that need term-table text resolution (projected,
        # filtered, ordered, grouped, etc.).  None = resolve all (safe
        # fallback).  Empty set = resolve none.
        self.text_needed_vars: Optional[set] = text_needed_vars

    @property
    def depth(self) -> int:
        return self._depth

    @property
    def quad_table(self) -> str:
        return f"{self.space_id}_rdf_quad"

    @property
    def term_table(self) -> str:
        return f"{self.space_id}_term"

    @property
    def datatype_table(self) -> str:
        return f"{self.space_id}_datatype"

    def dt_case_expr(self, t_alias: str) -> str:
        """Build a SQL CASE expression resolving datatype_id → URI text.

        DEPRECATED: Prefer the _dt CTE approach (build_dt_cte + LEFT JOIN).
        Kept for backward compatibility with emit_path.
        Returns 'NULL' if the cache is empty.
        """
        if not self.datatype_cache:
            return "NULL"
        whens = " ".join(
            f"WHEN {did} THEN '{uri}'"
            for did, uri in sorted(self.datatype_cache.items())
        )
        return f"CASE {t_alias}.datatype_id {whens} END"

    def build_dt_cte(self) -> str:
        """Build a _dt CTE with datatype_id → URI + type flags.

        Returns empty string if the cache is empty.  The CTE is:
            _dt(id, uri, is_num, is_bool, is_dt) AS (VALUES ...)
        PG materializes this as a tiny in-memory hash table (~2KB for
        36 rows), so LEFT JOINs against it are essentially free.
        """
        if not self.datatype_cache:
            return ""
        from .emit_bgp import _NUMERIC_DATATYPES, _BOOLEAN_DT, _DATETIME_DATATYPES
        num_set = set(_NUMERIC_DATATYPES)
        bool_set = {_BOOLEAN_DT}
        dt_set = set(_DATETIME_DATATYPES)
        rows = []
        for did, uri in sorted(self.datatype_cache.items()):
            is_num = "TRUE" if uri in num_set else "FALSE"
            is_bool = "TRUE" if uri in bool_set else "FALSE"
            is_dt = "TRUE" if uri in dt_set else "FALSE"
            rows.append(
                f"({did}::bigint, '{uri}'::text, {is_num}, {is_bool}, {is_dt})"
            )
        return (
            "_dt(id, uri, is_num, is_bool, is_dt) AS NOT MATERIALIZED (VALUES\n  "
            + ",\n  ".join(rows)
            + "\n)"
        )

    def dt_ids_for_uris(self, uris: List[str]) -> str:
        """Return a comma-separated list of datatype_id ints for a set of URIs.

        Used to replace `t.datatype IN ('uri1', 'uri2')` with
        `t.datatype_id IN (1, 2)` for numeric/boolean/datetime detection.
        Returns 'NULL' if none resolve (makes the IN clause always false).
        """
        ids = [str(self._dt_uri_to_id[u]) for u in uris if u in self._dt_uri_to_id]
        return ", ".join(ids) if ids else "NULL"

    def child(self, types: Optional[TypeRegistry] = None) -> EmitContext:
        """Create a child context for nested emission.

        Shares aliases and trace (global), but can have its own TypeRegistry
        for scope isolation (e.g., inside a subquery or UNION branch).
        """
        ctx = EmitContext(
            space_id=self.space_id,
            aliases=self.aliases,
            types=types or self.types.child_registry(),
            trace=self.trace,
            graph_lock_uri=self.graph_lock_uri,
            trace_enabled=self.trace_enabled,
            datatype_cache=self.datatype_cache,
            text_needed_vars=self.text_needed_vars,
        )
        ctx._depth = self._depth + 1
        return ctx

    def log(self, plan_kind: str, message: str, **kwargs) -> Optional[TraceStep]:
        """Log a processing step at the current depth."""
        if not self.trace_enabled:
            return None
        return self.trace.log_step(self._depth, "emit", plan_kind,
                                    message, **kwargs)

    def log_sql(self, plan_kind: str, sql: str) -> Optional[TraceStep]:
        """Log a SQL fragment at the current depth."""
        if not self.trace_enabled:
            return None
        return self.trace.log_sql(self._depth, plan_kind, sql)

    def log_columns(self, plan_kind: str, columns: Dict[str, str]) -> Optional[TraceStep]:
        """Log the column map at the current depth."""
        if not self.trace_enabled:
            return None
        return self.trace.log_column_map(self._depth, plan_kind, columns)

    def log_column_map(self, plan_kind: str) -> Optional[TraceStep]:
        """Log the full column map with companion detail for all registered vars.

        Produces the §8.3 rich format:
          COLUMNS: s→v0 (U, uuid=q0.sub_uuid), o→v1 (L, dt=xsd:integer, lane=num)
        """
        if not self.trace_enabled:
            return None
        col_details = {}
        for var in sorted(self.types.all_vars()):
            info = self.types.get(var)
            if not info:
                continue
            parts = [info.sql_name]
            if info.type_col:
                t = info.type_col
                if t == "'U'":
                    parts.append("U")
                elif t == "'L'":
                    parts.append("L")
                elif t == "'B'":
                    parts.append("B")
                else:
                    parts.append(f"type={t}")
            if info.uuid_col:
                parts.append("uuid")
            if info.dt_col and info.dt_col != "NULL":
                dt = info.dt_col
                if dt.startswith("'") and dt.endswith("'"):
                    dt = dt[1:-1].rsplit('#', 1)[-1]  # xsd:integer → integer
                parts.append(f"dt={dt}")
            if info.lang_col and info.lang_col != "NULL":
                parts.append(f"lang={info.lang_col}")
            if info.typed_lane:
                parts.append(f"lane={info.typed_lane}")
            if info.from_triple:
                parts.append("triple")
            col_details[var] = f"({', '.join(parts)})"

        msg = ", ".join(f"{v}→{col_details[v]}" for v in sorted(col_details))
        step = self.trace.log_step(self._depth, "columns", plan_kind, msg,
                                    column_map=col_details)
        return step

    def log_scope(self, plan_kind: str,
                  defined: Optional[set] = None,
                  optional: Optional[set] = None,
                  visible: Optional[set] = None) -> Optional[TraceStep]:
        """Log variable scope at the current depth."""
        if not self.trace_enabled:
            return None
        parts = []
        if defined:
            parts.append(f"defined={sorted(defined)}")
        if optional:
            parts.append(f"optional={sorted(optional)}")
        if visible:
            parts.append(f"visible={sorted(visible)}")
        msg = ", ".join(parts) if parts else "(empty)"
        return self.trace.log_step(self._depth, "scope", plan_kind, msg,
                                    details={"defined": sorted(defined or []),
                                             "optional": sorted(optional or []),
                                             "visible": sorted(visible or [])})
