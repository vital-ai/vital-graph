"""Shared helpers for emit handler unit tests.

Provides _make_ctx, _leaf_bgp, _var, _lit, _func, etc. for building
minimal EmitContext and PlanV2 inputs without a database or sidecar.
"""
# pyright: reportOperatorIssue=false, reportArgumentType=false

from __future__ import annotations

from typing import Optional

import pytest

try:
    import pglast
    HAS_PGLAST = True
except ImportError:
    HAS_PGLAST = False

from vitalgraph.db.jena_sparql.jena_types import (
    ExprVar, ExprValue, ExprFunction,
    LiteralNode,
)
from vitalgraph.db.sparql_sql.ir import (
    AliasGenerator, PlanV2,
    KIND_BGP, KIND_NULL,
)
from vitalgraph.db.sparql_sql.emit_context import EmitContext, ProcessingTrace
from vitalgraph.db.sparql_sql.sql_type_generation import ColumnInfo, TypeRegistry


def _make_ctx(
    vars_config: Optional[dict] = None,
    text_needed: Optional[set] = None,
) -> EmitContext:
    """Build a minimal EmitContext with registered variables.

    vars_config: dict of sparql_name → "text" | "numeric" | "full"
    """
    aliases = AliasGenerator()
    types = TypeRegistry(aliases=aliases)
    ctx = EmitContext(
        space_id="test_space",
        aliases=aliases,
        types=types,
        trace=ProcessingTrace(),
        base_uri="http://example.org/",
        text_needed_vars=text_needed,
    )

    if vars_config:
        for i, (var_name, kind) in enumerate(vars_config.items()):
            sql_name = f"v{i}"
            if kind == "numeric":
                info = ColumnInfo(
                    sparql_name=var_name,
                    sql_name=sql_name,
                    text_col=sql_name,
                    type_col=f"{sql_name}__type",
                    uuid_col=f"{sql_name}__uuid",
                    lang_col=f"{sql_name}__lang",
                    dt_col=f"{sql_name}__datatype",
                    num_col=f"{sql_name}__num",
                    from_triple=True,
                    typed_lane="num",
                )
            elif kind == "full":
                info = ColumnInfo.simple_output(var_name, sql_name, from_triple=True)
            else:  # "text"
                info = ColumnInfo(
                    sparql_name=var_name,
                    sql_name=sql_name,
                    text_col=sql_name,
                    type_col=f"{sql_name}__type",
                    uuid_col=f"{sql_name}__uuid",
                    lang_col=f"{sql_name}__lang",
                    dt_col=f"{sql_name}__datatype",
                    num_col=f"{sql_name}__num",
                    from_triple=True,
                )
            types.register(info)

    return ctx


def _leaf_bgp() -> PlanV2:
    """Create a minimal leaf BGP node."""
    return PlanV2(kind=KIND_BGP)


def _leaf_null() -> PlanV2:
    """Create a NULL leaf node."""
    return PlanV2(kind=KIND_NULL)


def _var(name: str):
    return ExprVar(var=name)


def _lit(value: str, datatype: str = None, lang: str = None):
    return ExprValue(node=LiteralNode(value=value, datatype=datatype, lang=lang))


def _func(name: str, *args, function_iri: str = None):
    return ExprFunction(name=name, args=list(args), function_iri=function_iri)


def _assert_valid_sql(sql: str):
    """Validate full SQL statement via pglast."""
    if not HAS_PGLAST:
        return
    try:
        pglast.parse_sql(sql)
    except pglast.parser.ParseError as e:
        pytest.fail(f"Invalid SQL: {sql[:200]}\nError: {e}")
