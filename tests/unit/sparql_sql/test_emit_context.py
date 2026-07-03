"""Unit tests for emit_context.py — EmitContext + ProcessingTrace."""
# pyright: reportOperatorIssue=false, reportArgumentType=false

from __future__ import annotations

import json

from vitalgraph.db.sparql_sql.ir import AliasGenerator
from vitalgraph.db.sparql_sql.emit_context import EmitContext, ProcessingTrace, TraceStep
from vitalgraph.db.sparql_sql.sql_type_generation import ColumnInfo, TypeRegistry


# ---------------------------------------------------------------------------
# TraceStep
# ---------------------------------------------------------------------------


class TestTraceStep:

    def test_to_dict_minimal(self):
        """Minimal step → only required fields."""
        step = TraceStep(depth=0, phase="emit", plan_kind="BGP", message="test")
        d = step.to_dict()
        assert d["depth"] == 0
        assert d["phase"] == "emit"
        assert d["plan_kind"] == "BGP"
        assert d["message"] == "test"
        assert "details" not in d
        assert "sql" not in d
        assert "columns" not in d

    def test_to_dict_with_details(self):
        """Step with details, sql, columns."""
        step = TraceStep(
            depth=1, phase="collect", plan_kind="JOIN",
            message="joining",
            details={"vars": ["s", "o"]},
            sql_fragment="SELECT 1",
            column_map={"s": "v0"},
        )
        d = step.to_dict()
        assert d["details"] == {"vars": ["s", "o"]}
        assert d["sql"] == "SELECT 1"
        assert d["columns"] == {"s": "v0"}


# ---------------------------------------------------------------------------
# ProcessingTrace
# ---------------------------------------------------------------------------


class TestProcessingTrace:

    def test_add_and_steps(self):
        """add() appends steps."""
        trace = ProcessingTrace()
        trace.add(0, "emit", "BGP", "step 1")
        trace.add(1, "emit", "JOIN", "step 2")
        assert len(trace.steps) == 2

    def test_log_step(self):
        """log_step() appends and returns step."""
        trace = ProcessingTrace()
        step = trace.log_step(0, "emit", "BGP", "hello")
        assert step.message == "hello"
        assert len(trace.steps) == 1

    def test_log_sql(self):
        """log_sql() records SQL fragment."""
        trace = ProcessingTrace()
        step = trace.log_sql(0, "BGP", "SELECT * FROM foo")
        assert step.sql_fragment == "SELECT * FROM foo"

    def test_log_column_map(self):
        """log_column_map() records column mapping."""
        trace = ProcessingTrace()
        step = trace.log_column_map(0, "BGP", {"s": "v0", "o": "v1"})
        assert step.column_map == {"s": "v0", "o": "v1"}

    def test_log_scope(self):
        """log_scope() records visible vars."""
        trace = ProcessingTrace()
        step = trace.log_scope(0, "BGP", ["s", "o"])
        assert "scope" in step.message

    def test_summary(self):
        """summary() returns step count and max depth."""
        trace = ProcessingTrace()
        trace.add(0, "emit", "BGP", "a")
        trace.add(2, "emit", "JOIN", "b")
        s = trace.summary()
        assert "2 steps" in s
        assert "max depth 2" in s

    def test_max_depth_empty(self):
        """Empty trace → max depth 0."""
        trace = ProcessingTrace()
        assert trace.max_depth() == 0

    def test_max_depth(self):
        trace = ProcessingTrace()
        trace.add(0, "emit", "BGP", "a")
        trace.add(3, "emit", "JOIN", "b")
        assert trace.max_depth() == 3

    def test_steps_at_depth(self):
        trace = ProcessingTrace()
        trace.add(0, "emit", "BGP", "a")
        trace.add(1, "emit", "JOIN", "b")
        trace.add(0, "emit", "PROJECT", "c")
        result = trace.steps_at_depth(0)
        assert len(result) == 2

    def test_steps_for_kind(self):
        trace = ProcessingTrace()
        trace.add(0, "emit", "BGP", "a")
        trace.add(1, "emit", "JOIN", "b")
        result = trace.steps_for_kind("BGP")
        assert len(result) == 1

    def test_steps_for_phase(self):
        trace = ProcessingTrace()
        trace.add(0, "emit", "BGP", "a")
        trace.add(0, "columns", "BGP", "b")
        result = trace.steps_for_phase("columns")
        assert len(result) == 1

    def test_find_step_match(self):
        trace = ProcessingTrace()
        trace.add(0, "emit", "BGP", "a")
        trace.add(0, "columns", "JOIN", "b")
        step = trace.find_step(phase="columns", plan_kind="JOIN")
        assert step is not None
        assert step.message == "b"

    def test_find_step_no_match(self):
        trace = ProcessingTrace()
        trace.add(0, "emit", "BGP", "a")
        step = trace.find_step(phase="columns", plan_kind="JOIN")
        assert step is None

    def test_final_column_map(self):
        trace = ProcessingTrace()
        trace.add(0, "columns", "BGP", "a", column_map={"s": "v0"})
        trace.add(0, "columns", "PROJECT", "b", column_map={"s": "v0", "o": "v1"})
        result = trace.final_column_map()
        assert result == {"s": "v0", "o": "v1"}

    def test_final_column_map_empty(self):
        trace = ProcessingTrace()
        assert trace.final_column_map() == {}

    def test_print_tree_empty(self):
        trace = ProcessingTrace()
        result = trace.print_tree()
        assert result == ""

    def test_print_tree_with_query(self):
        trace = ProcessingTrace(sparql_query="SELECT ?s WHERE { ?s ?p ?o }")
        trace.add(0, "emit", "BGP", "scan")
        result = trace.print_tree()
        assert "SPARQL:" in result
        assert "SELECT ?s" in result
        assert "EMIT" in result

    def test_print_tree_with_sql(self):
        trace = ProcessingTrace()
        trace.add(0, "emit", "BGP", "scan", sql_fragment="SELECT v0 FROM quad")
        result = trace.print_tree()
        assert "sql:" in result

    def test_to_json(self):
        trace = ProcessingTrace()
        trace.add(0, "emit", "BGP", "test")
        result = json.loads(trace.to_json())
        assert "steps" in result
        assert len(result["steps"]) == 1
        assert result["steps"][0]["plan_kind"] == "BGP"

    def test_column_map_at_valid(self):
        trace = ProcessingTrace()
        trace.add(0, "columns", "BGP", "a", column_map={"s": "v0"})
        assert trace.column_map_at(0) == {"s": "v0"}

    def test_column_map_at_out_of_range(self):
        trace = ProcessingTrace()
        assert trace.column_map_at(5) is None

    def test_column_map_at_no_map(self):
        trace = ProcessingTrace()
        trace.add(0, "emit", "BGP", "a")
        assert trace.column_map_at(0) is None


# ---------------------------------------------------------------------------
# EmitContext
# ---------------------------------------------------------------------------


class TestEmitContext:

    def _ctx(self, **kwargs) -> EmitContext:
        aliases = AliasGenerator()
        types = TypeRegistry(aliases=aliases)
        return EmitContext(
            space_id="test_space",
            aliases=aliases,
            types=types,
            trace=ProcessingTrace(),
            **kwargs,
        )

    def test_defaults(self):
        ctx = self._ctx()
        assert ctx.space_id == "test_space"
        assert ctx.depth == 0
        assert ctx.quad_table == "test_space_rdf_quad"
        assert ctx.term_table == "test_space_term"
        assert ctx.datatype_table == "test_space_datatype"

    def test_dt_case_expr_empty(self):
        """No datatype cache → NULL."""
        ctx = self._ctx()
        assert ctx.dt_case_expr("t0") == "NULL"

    def test_dt_case_expr_with_cache(self):
        """Datatype cache → CASE expression."""
        ctx = self._ctx(datatype_cache={
            1: "http://www.w3.org/2001/XMLSchema#integer",
            2: "http://www.w3.org/2001/XMLSchema#string",
        })
        result = ctx.dt_case_expr("t0")
        assert "CASE t0.datatype_id" in result
        assert "WHEN 1 THEN" in result
        assert "WHEN 2 THEN" in result

    def test_build_dt_cte_empty(self):
        """No datatype cache → empty string."""
        ctx = self._ctx()
        assert ctx.build_dt_cte() == ""

    def test_build_dt_cte_with_cache(self):
        """Datatype cache → _dt CTE with type flags."""
        ctx = self._ctx(datatype_cache={
            1: "http://www.w3.org/2001/XMLSchema#integer",
            2: "http://www.w3.org/2001/XMLSchema#boolean",
            3: "http://www.w3.org/2001/XMLSchema#dateTime",
            4: "http://www.w3.org/2001/XMLSchema#string",
        })
        result = ctx.build_dt_cte()
        assert "_dt(id, uri, is_num, is_bool, is_dt)" in result
        assert "VALUES" in result
        # integer should be numeric
        assert "TRUE" in result

    def test_dt_ids_for_uris_found(self):
        """Known URIs → comma-separated IDs."""
        ctx = self._ctx(datatype_cache={
            1: "http://www.w3.org/2001/XMLSchema#integer",
            2: "http://www.w3.org/2001/XMLSchema#decimal",
        })
        result = ctx.dt_ids_for_uris([
            "http://www.w3.org/2001/XMLSchema#integer",
            "http://www.w3.org/2001/XMLSchema#decimal",
        ])
        assert "1" in result
        assert "2" in result

    def test_dt_ids_for_uris_none_found(self):
        """Unknown URIs → NULL."""
        ctx = self._ctx()
        result = ctx.dt_ids_for_uris(["http://example.org/unknown"])
        assert result == "NULL"

    def test_add_vector_request(self):
        from vitalgraph.db.sparql_sql.vg_functions import VectorRequest
        ctx = self._ctx()
        vr = VectorRequest(placeholder="__VG__", search_text="cat",
                           index_name="idx", space_id="test_space")
        ctx.add_vector_request(vr)
        assert len(ctx.vector_requests) == 1
        assert ctx.vector_requests[0].search_text == "cat"

    def test_add_fuzzy_request(self):
        from vitalgraph.db.sparql_sql.vg_functions import FuzzyRequest
        ctx = self._ctx()
        fr = FuzzyRequest(
            filter_placeholder="__VG_FUZZY_FILTER_0__",
            score_placeholder="__VG_FUZZY_SCORE_0__",
            search_text="hello",
            min_score=80.0,
            entity_var="s",
            uuid_col="v0__uuid",
            space_id="test_space",
        )
        ctx.add_fuzzy_request(fr)
        assert len(ctx.fuzzy_requests) == 1
        assert ctx.fuzzy_requests[0].search_text == "hello"

    def test_child_shares_trace_and_aliases(self):
        ctx = self._ctx()
        child = ctx.child()
        assert child.trace is ctx.trace
        assert child.aliases is ctx.aliases
        assert child.depth == 1
        assert child.space_id == ctx.space_id

    def test_child_shares_vector_requests(self):
        from vitalgraph.db.sparql_sql.vg_functions import VectorRequest
        ctx = self._ctx()
        child = ctx.child()
        vr = VectorRequest(placeholder="__VG__", search_text="dog",
                           index_name="idx", space_id="test_space")
        child.add_vector_request(vr)
        assert len(ctx.vector_requests) == 1  # shared list

    def test_child_has_own_type_registry(self):
        ctx = self._ctx()
        child = ctx.child()
        assert child.types is not ctx.types

    def test_log_disabled(self):
        ctx = self._ctx(trace_enabled=False)
        result = ctx.log("BGP", "test")
        assert result is None

    def test_log_enabled(self):
        ctx = self._ctx(trace_enabled=True)
        result = ctx.log("BGP", "test")
        assert result is not None
        assert len(ctx.trace.steps) == 1

    def test_log_sql_disabled(self):
        ctx = self._ctx(trace_enabled=False)
        result = ctx.log_sql("BGP", "SELECT 1")
        assert result is None

    def test_log_sql_enabled(self):
        ctx = self._ctx(trace_enabled=True)
        result = ctx.log_sql("BGP", "SELECT 1")
        assert result is not None

    def test_log_columns_disabled(self):
        ctx = self._ctx(trace_enabled=False)
        result = ctx.log_columns("BGP", {"s": "v0"})
        assert result is None

    def test_log_columns_enabled(self):
        ctx = self._ctx(trace_enabled=True)
        result = ctx.log_columns("BGP", {"s": "v0"})
        assert result is not None

    def test_log_column_map_disabled(self):
        ctx = self._ctx(trace_enabled=False)
        result = ctx.log_column_map("BGP")
        assert result is None

    def test_log_column_map_with_vars(self):
        """log_column_map produces rich column details."""
        ctx = self._ctx()
        info = ColumnInfo(
            sparql_name="s", sql_name="v0", text_col="v0",
            type_col="'U'", uuid_col="v0__uuid",
            dt_col="'http://www.w3.org/2001/XMLSchema#integer'",
            lang_col="NULL", num_col="v0__num",
            from_triple=True, typed_lane="num",
        )
        ctx.types.register(info)
        step = ctx.log_column_map("BGP")
        assert step is not None
        assert step.column_map is not None
        assert "s" in step.column_map
        detail = step.column_map["s"]
        assert "U" in detail
        assert "uuid" in detail
        assert "lane=num" in detail
        assert "triple" in detail

    def test_log_column_map_literal_type(self):
        """Type col 'L' → shows L."""
        ctx = self._ctx()
        info = ColumnInfo(
            sparql_name="o", sql_name="v1", text_col="v1",
            type_col="'L'", uuid_col=None,
            lang_col="'en'", dt_col="NULL",
        )
        ctx.types.register(info)
        step = ctx.log_column_map("BGP")
        assert step is not None
        assert step.column_map is not None
        detail = step.column_map["o"]
        assert "L" in detail
        assert "lang=" in detail

    def test_log_column_map_bnode_type(self):
        """Type col 'B' → shows B."""
        ctx = self._ctx()
        info = ColumnInfo(
            sparql_name="b", sql_name="v2", text_col="v2",
            type_col="'B'",
        )
        ctx.types.register(info)
        step = ctx.log_column_map("BGP")
        assert step is not None
        assert step.column_map is not None
        assert "B" in step.column_map["b"]

    def test_log_column_map_dynamic_type(self):
        """Non-constant type col → shows type=..."""
        ctx = self._ctx()
        info = ColumnInfo(
            sparql_name="x", sql_name="v3", text_col="v3",
            type_col="t0.term_type",
        )
        ctx.types.register(info)
        step = ctx.log_column_map("BGP")
        assert step is not None
        assert step.column_map is not None
        assert "type=t0.term_type" in step.column_map["x"]

    def test_log_column_map_datatype_short(self):
        """Datatype with quotes → shortened (e.g., integer)."""
        ctx = self._ctx()
        info = ColumnInfo(
            sparql_name="n", sql_name="v4", text_col="v4",
            dt_col="'http://www.w3.org/2001/XMLSchema#integer'",
        )
        ctx.types.register(info)
        step = ctx.log_column_map("BGP")
        assert step is not None
        assert step.column_map is not None
        assert "dt=integer" in step.column_map["n"]

    def test_log_scope_disabled(self):
        ctx = self._ctx(trace_enabled=False)
        result = ctx.log_scope("BGP")
        assert result is None

    def test_log_scope_enabled(self):
        ctx = self._ctx(trace_enabled=True)
        result = ctx.log_scope("BGP", defined={"s", "o"}, optional={"p"},
                                visible={"s", "o", "p"})
        assert result is not None  # type: ignore[union-attr]
        assert "defined=" in result.message
        assert "optional=" in result.message
        assert "visible=" in result.message

    def test_log_scope_empty(self):
        ctx = self._ctx(trace_enabled=True)
        result = ctx.log_scope("BGP")
        assert result is not None
        assert "(empty)" in result.message
