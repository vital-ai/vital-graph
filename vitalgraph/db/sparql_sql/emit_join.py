"""Handlers for KIND_JOIN and KIND_LEFT_JOIN."""

from __future__ import annotations

import logging
from typing import Set

from ..jena_sparql.jena_types import VarNode
from .ir import KIND_BGP, PlanV2, KIND_TABLE, KIND_PATH
from .emit_context import EmitContext
from .var_scope import compute_scope

logger = logging.getLogger(__name__)


def _all_required(node, depth: int = 0) -> bool:
    """True if every variable this subtree binds is necessarily bound.

    Only holds when the subtree contains nothing that can produce an unbound
    variable: a LEFT JOIN (OPTIONAL), a UNION branch that omits a variable, or
    a VALUES table carrying UNDEF. Used to drop the SPARQL compatible-mapping
    disjuncts from a join condition, which is what turns it back into an
    equijoin PostgreSQL can hash or merge on.
    """
    from .ir import KIND_LEFT_JOIN, KIND_UNION, KIND_TABLE, KIND_MINUS
    if node is None or depth > 12:
        return False
    if node.kind in (KIND_LEFT_JOIN, KIND_UNION, KIND_TABLE, KIND_MINUS):
        return False
    return all(_all_required(c, depth + 1) for c in (node.children or []))


def _boundness_col(alias: str, sql_name: str, info) -> str:
    """Column whose NULL-ness actually means "this variable is unbound".

    Not simply the text column: when the term JOIN is deferred the text is
    NULL for a variable that is bound, so testing it reports unbound and
    SPARQL's "unbound is compatible with anything" rule then admits rows it
    should not (issue 030).

    A variable with a term identity is tested on ``__uuid``. One without —
    a VALUES/BIND/aggregate value — is tested on its text, which is always
    materialised for exactly the reason it has no term identity: the value was
    synthesized rather than read from a term row, so there is nothing to defer.
    """
    if info is not None and info.has_term_identity():
        return f"{alias}.{sql_name}__uuid"
    return f"{alias}.{sql_name}"


def emit_join(plan: PlanV2, ctx: EmitContext) -> str:
    """Emit SQL for an inner JOIN."""
    return _emit_join_impl(plan, ctx, is_left=False)


def emit_left_join(plan: PlanV2, ctx: EmitContext) -> str:
    """Emit SQL for a LEFT JOIN (OPTIONAL)."""
    return _emit_join_impl(plan, ctx, is_left=True)


def _emit_join_impl(plan: PlanV2, ctx: EmitContext, is_left: bool) -> str:
    """Common implementation for JOIN and LEFT JOIN."""
    from .emit import emit

    left_child = plan.children[0]
    right_child = plan.children[1]

    # Create child contexts with isolated type registries
    left_ctx = ctx.child()
    right_ctx = ctx.child()

    left_sql = emit(left_child, left_ctx)

    l_alias = ctx.aliases.next("j")
    r_alias = ctx.aliases.next("j")

    # Compute variable sets from scopes
    left_scope = compute_scope(left_child)
    right_scope = compute_scope(right_child)
    left_vars = left_scope.all_visible
    right_vars = right_scope.all_visible
    shared = left_vars & right_vars
    all_vars = left_vars | right_vars



    ctx.log("join", f"left_vars={sorted(left_vars)}, right_vars={sorted(right_vars)}, "
            f"shared={sorted(shared)}, is_left={is_left}")

    from .sql_type_generation import TypeRegistry, ColumnInfo

    # Resolve child sql_names for each variable
    def _child_sn(v, child_ctx):
        info = child_ctx.types.get(v)
        return info.sql_name if info else v

    # VALUES (KIND_TABLE) uses UNDEF → NULL; joins must be NULL-tolerant
    left_is_table = left_child.kind == KIND_TABLE
    right_is_table = right_child.kind == KIND_TABLE

    # Semi-join: emit the right side as a flat existence probe correlated on the
    # shared variable. Requires the left side emitted first, for its alias.
    # --- Seed a right-hand property path from the left's output (issues/124) ---
    #
    # A recursive path seeds its base term only when its start is a URI written
    # literally in the query. Reached through a sibling it is a variable, and an
    # unseeded recursion closes over the whole graph before filtering: measured
    # at 67 s against 26 ms on `sp_lead_synth_100k` for the same 53 results.
    #
    # The left is already emitted, so its rows are exactly the starts the path
    # will be joined to. Handing that SQL down restricts the recursion's base
    # term to them. The outer join still applies the same constraint, so this is
    # redundant rather than semantically load-bearing — the same argument
    # `emit_path` makes for the pinned case.
    #
    # Conditions, all necessary: the path's start must be the shared variable,
    # and the LEFT must actually produce it with term identity, or there is no
    # uuid column to seed from.
    if right_child.kind == KIND_PATH:
        _meta = right_child.path_meta or {}
        _subj = _meta.get("subject")
        if isinstance(_subj, VarNode) and _subj.name in shared:
            _linfo = left_ctx.types.get(_subj.name)
            if _linfo is not None and _linfo.has_term_identity():
                # No NULL filter: `= ANY (...)` never matches NULL, so one is
                # redundant — and testing a __uuid column for NULL is the
                # boundness-inference mistake `issue 026` and
                # `test_null_provenance_lint` exist to prevent. The
                # has_term_identity() guard above is what makes this column
                # meaningful; a per-row NULL simply contributes no seed.
                right_child.hints["path_start_seed"] = (
                    f"SELECT _seed.{_linfo.sql_name}__uuid "
                    f"FROM ({left_sql}) AS _seed")
                ctx.log("join", f"seeding right-hand path on ?{_subj.name} "
                                f"from the left (issues/124)")

    exists_sql = None
    if (not is_left) and plan.hints.get('semijoin') and len(shared) == 1:
        from .emit_bgp import emit_bgp_exists, find_bgp
        v = next(iter(shared))
        l_info = left_ctx.types.get(v)
        rbgp = find_bgp(right_child)
        if rbgp is not None and l_info and l_info.has_term_identity():
            exists_sql = emit_bgp_exists(
                rbgp, right_ctx, (v, f"{l_alias}.{l_info.sql_name}__uuid"))

    if exists_sql is not None:
        # Only variables the LEFT CHILD ACTUALLY PRODUCED. A missing registry
        # entry means the child does not emit that column, and `_child_sn` falls
        # back to the raw SPARQL name — so the projection asked for
        # `j2._seg_idx`, a column nothing had created, and PostgreSQL rejected
        # the whole query with `column j2._seg_idx does not exist`.
        #
        # The comment below already names this failure for ORDER BY. It is the
        # same fabrication one step earlier, and it only surfaces where the
        # semi-join gate fires, so it is data-dependent: the same document query
        # is fine on a space whose statistics do not select this path.
        semi_vars = [v2 for v2 in sorted(left_vars) if left_ctx.types.get(v2)]
        missing = sorted(set(left_vars) - set(semi_vars))
        if missing:
            ctx.log("join", f"SEMI JOIN: left child does not produce {missing}; "
                            f"not projected")
        semi_cols = []
        for v2 in semi_vars:
            semi_cols.extend(
                TypeRegistry.passthrough_columns(_child_sn(v2, left_ctx), l_alias))
        if semi_cols:
            # Only the left side survives. Register its variables as this node's
            # output — without this an ORDER BY above cannot resolve them and
            # emits the raw SPARQL name as a column. Drop the probed side's
            # private variables for the same reason, in reverse.
            for v2 in semi_vars:
                ci = left_ctx.types.get(v2)
                ctx.types.register(ColumnInfo.simple_output(
                    v2, ci.sql_name if ci else v2,
                    typed_lane=ci.typed_lane if ci else None,
                    from_triple=ci.from_triple if ci else False,
                    text_materialized=ci.text_materialized if ci else True))
            for v2 in sorted(right_vars - left_vars):
                ctx.types.drop(v2)
            ctx.log("join", f"SEMI JOIN via flat probe; dropped "
                            f"{sorted(right_vars - left_vars)}")
            return (f"SELECT {', '.join(semi_cols)}\n"
                    f"FROM ({left_sql}) AS {l_alias}\n"
                    f"WHERE EXISTS (\n{exists_sql}\n)")

    right_sql = emit(right_child, right_ctx)

    # ON clause: shared variables joined by UUID, typed lane, or text
    if shared:
        on_parts = []
        for v in sorted(shared):
            left_info = left_ctx.types.get(v)
            right_info = right_ctx.types.get(v)
            l_sn = left_info.sql_name if left_info else v
            r_sn = right_info.sql_name if right_info else v
            left_has_uuid = bool(left_info and left_info.has_term_identity())
            right_has_uuid = bool(right_info and right_info.has_term_identity())
            if left_has_uuid and right_has_uuid:
                cond = f"{l_alias}.{l_sn}__uuid = {r_alias}.{r_sn}__uuid"
            elif (left_info and right_info
                  and left_info.typed_lane and left_info.typed_lane == right_info.typed_lane):
                lane = left_info.typed_lane
                cond = f"{l_alias}.{l_sn}__{lane} = {r_alias}.{r_sn}__{lane}"
            elif (left_info and left_info.typed_lane
                  and right_info and not right_info.typed_lane and right_info.from_triple):
                lane = left_info.typed_lane
                cond = f"{l_alias}.{l_sn}__{lane} = {r_alias}.{r_sn}__{lane}"
            elif (right_info and right_info.typed_lane
                  and left_info and not left_info.typed_lane and left_info.from_triple):
                lane = right_info.typed_lane
                cond = f"{l_alias}.{l_sn}__{lane} = {r_alias}.{r_sn}__{lane}"
            else:
                cond = (
                    f"CAST({l_alias}.{l_sn} AS TEXT) = CAST({r_alias}.{r_sn} AS TEXT)"
                )
            # Rule 2: 3-part compatibility for joins (§10.5).
            # SPARQL compatible-mapping semantics: unbound (NULL) is
            # compatible with any value.  Apply to VALUES joins AND LEFT
            # JOINs so that sequential OPTIONALs sharing a variable work.
            #
            # The NULL test must use a column that actually signals boundness.
            # The text column does not when the term JOIN was deferred — it is
            # NULL for a variable that IS bound (issue 030 kind D). So prefer
            # __uuid where there is a term identity, and fall back to text
            # only for synthesized values, whose text is always materialised
            # precisely because there is no term row to defer.
            if right_is_table or left_is_table or is_left:
                l_null_col = _boundness_col(l_alias, l_sn, left_info)
                r_null_col = _boundness_col(r_alias, r_sn, right_info)
                # The right-hand disjunct is dead when the right side is a plain
                # BGP and the variable comes from one of its triples: the ON
                # clause is evaluated against real right-hand rows, where such a
                # variable is always bound. A nested OPTIONAL inside the right
                # side could leave it NULL, which is why this requires KIND_BGP
                # rather than trusting from_triple alone.
                #
                # Dropping it matters because `(a IS NULL OR b IS NULL OR a = b)`
                # is not an equijoin: PostgreSQL cannot hash or merge on it and
                # falls back to a nested loop with a join filter. On is_empty —
                # OPTIONAL + FILTER(!BOUND) — that was over 120s against 1.3s
                # for the same query with a plain equality (issues/052).
                def _always_bound(child, info):
                    # "child.kind is a BGP" was too strict: the left side of a
                    # LEFT JOIN is usually a JOIN of BGPs, whose variables are
                    # every bit as bound. What matters is that nothing in the
                    # subtree can leave a variable unbound — no OPTIONAL, no
                    # UNION branch that omits it, no VALUES carrying UNDEF.
                    #
                    # `uuid_materialized` counts alongside `from_triple`: a
                    # VALUES block only sets it when EVERY row bound the
                    # variable to a constant that resolved, so there is no
                    # UNDEF to protect against (`issues/087`).
                    if info is None:
                        return False
                    if info.uuid_materialized:
                        # Per-VARIABLE evidence, which is stronger than the
                        # per-NODE rule in `_all_required`. That rule rejects
                        # every VALUES table because one MIGHT carry UNDEF;
                        # this flag is set only when every row of this block
                        # bound THIS variable to a constant that resolved, so
                        # for this variable there is no UNDEF to protect
                        # against. Other variables of the same block are
                        # judged independently.
                        return True
                    return info.from_triple and _all_required(child)

                plain_left_join = (is_left and not right_is_table
                                   and not left_is_table)
                # An INNER join may drop the guards on the same evidence. SPARQL
                # joins compatible mappings; when both sides always bind the
                # variable, compatible means equal, and the guards only stop
                # PostgreSQL recognising an equijoin. Measured on a two-URI
                # VALUES: 6,219 ms with them, 4.6 ms without, same rows.
                #
                # LEFT joins keep the existing, narrower rule — an unmatched
                # left row must still survive with NULLs.
                inner_join = not is_left
                may_drop = plain_left_join or inner_join
                disjuncts = []
                if not (may_drop and _always_bound(left_child, left_info)):
                    disjuncts.append(f"{l_null_col} IS NULL")
                if not (may_drop and _always_bound(right_child, right_info)):
                    disjuncts.append(f"{r_null_col} IS NULL")
                if disjuncts:
                    cond = "(" + " OR ".join(disjuncts + [cond]) + ")"
            on_parts.append(cond)
        on_clause = " AND ".join(on_parts)
        ctx.log("join", f"ON: {', '.join(on_parts[:3])}{'...' if len(on_parts) > 3 else ''}")
    else:
        on_clause = "TRUE"

    # LEFT JOIN ON expressions (OPTIONAL filter conditions)
    #
    # These must be emitted against a scope that KNOWS the join's operands.
    # `ctx.types` does not yet: the output variables are registered further
    # down, and even then they name the join's OUTPUT columns, while an ON
    # clause has to reference `j0.`/`j1.` — the operands themselves.
    #
    # Emitting against the outer ctx produced
    # `NULL /* vg:unresolved-var ?v1 */` on BOTH sides of the condition, so the
    # whole ON was NULL, the LEFT JOIN matched nothing, the optional variable
    # never bound, and `FILTER(!bound(?v3))` kept every row — DAWG
    # `open-eq-12`, 64 rows where 10 are correct (`issues/129`).
    #
    # A NULL join condition is not an error, it is a join that silently matches
    # nothing, which is why `issues/028`'s unresolved-variable policy did not
    # catch this.
    if is_left and plan.left_join_exprs:
        from .emit_expressions import expr_to_sql
        from .sql_type_generation import ColumnInfo
        on_ctx = ctx.child()
        for v in sorted(all_vars):
            src = (left_ctx.types.get(v) if v in left_vars
                   else right_ctx.types.get(v))
            if src is None or not src.sql_name:
                continue
            # Qualified by the OPERAND's alias, not the join's output name.
            alias = l_alias if v in left_vars else r_alias
            on_ctx.types.register(ColumnInfo.simple_output(
                v, f"{alias}.{src.sql_name}",
                from_triple=src.from_triple,
                typed_lane=src.typed_lane))
        for expr in plan.left_join_exprs:
            sql_expr = expr_to_sql(expr, on_ctx)
            if sql_expr:
                on_clause += f" AND {sql_expr}"

    # Rule 4: COALESCE for shared variable projection (§10.5).
    # Prefer left's sql_name for shared vars (canonical output name).
    # For VALUES joins and LEFT JOINs, use COALESCE so right-side bindings
    # fill in NULLs from the left (SPARQL compatible-mapping semantics).
    select_cols = []
    values_shared = shared if (left_is_table or right_is_table or is_left) else set()
    # A variable NEITHER CHILD REGISTERED is not produced by either side, and
    # `_child_sn` falls back to the raw SPARQL name — so the projection asks for
    # a column nothing created and PostgreSQL rejects the whole query
    # (`column j2._seg_idx does not exist`). Skip it: an absent column cannot be
    # projected, and inventing a name turns a missing variable into a syntax
    # error a long way from its cause.
    producible = [v for v in sorted(all_vars)
                  if (left_ctx.types.get(v) if v in left_vars
                      else right_ctx.types.get(v))]
    dropped = sorted(set(all_vars) - set(producible))
    if dropped:
        ctx.log("join", f"neither child produces {dropped}; not projected")
    for v in producible:
        if v in left_vars:
            sn = _child_sn(v, left_ctx)
            if v in values_shared and v in right_vars:
                r_sn = _child_sn(v, right_ctx)
                select_cols.extend(
                    TypeRegistry.coalesce_columns(sn, l_alias, r_sn, r_alias))
            else:
                select_cols.extend(TypeRegistry.passthrough_columns(sn, l_alias))
        else:
            sn = _child_sn(v, right_ctx)
            select_cols.extend(TypeRegistry.passthrough_columns(sn, r_alias))

    # Register output variables — reuse child sql_names (globally unique)
    # Propagate from_triple so downstream JOINs know the variable has a UUID.
    for v in producible:
        child_info = left_ctx.types.get(v) if v in left_vars else right_ctx.types.get(v)
        sn = child_info.sql_name
        lane = child_info.typed_lane if child_info else None
        ft = child_info.from_triple if child_info else False
        tm = child_info.text_materialized if child_info else True
        ctx.types.register(ColumnInfo.simple_output(
            v, sn, typed_lane=lane, from_triple=ft, text_materialized=tm))

    ctx.log("join", f"output map: {{{', '.join(f'?{v}→{ctx.types.get(v).sql_name}' for v in producible)}}}")
    ctx.log_scope("join", defined=left_vars | right_vars,
                  optional=right_vars - left_vars if is_left else None)

    join_type = "LEFT JOIN" if is_left else "JOIN"

    sql = (
        f"SELECT {', '.join(select_cols)}\n"
        f"FROM ({left_sql}) AS {l_alias}\n"
        f"{join_type} ({right_sql}) AS {r_alias}\n"
        f"ON {on_clause}"
    )
    return sql
