/*-------------------------------------------------------------------------
 *
 * advice_check.c
 *	  After planning: did the final plan follow the advice?
 *
 * Applying advice during the join search does not guarantee the plan that
 * comes out uses it: a disabled path can still win when nothing else is
 * legal, and a relation can be removed or planned somewhere the advice did
 * not reach. So compliance is read off the finished PlannedStmt:
 *
 *	  join(x:m)  some join node has, among the bgp's relations, exactly the
 *	             steps before x on its outer side and exactly x on its inner
 *	             side, and that node is method m;
 *	  order      such a node exists for every step after the first;
 *	  rows(x:n)  the prefix through x was built and given n (recorded during
 *	             planning; the plan tree does not carry join-relation sizes).
 *
 * Every item ends as applied or not applied, and anything not applied is a
 * mismatch: an ERROR or a WARNING by vg_planner.on_mismatch. The per-item
 * result is kept as the backend's last report, vg_planner_last_report().
 *
 *-------------------------------------------------------------------------
 */
#include "postgres.h"

#include "fmgr.h"
#include "lib/stringinfo.h"
#include "nodes/pathnodes.h"
#include "nodes/plannodes.h"
#include "optimizer/optimizer.h"
#include "parser/parsetree.h"
#include "utils/builtins.h"
#include "utils/memutils.h"

#include "vg_planner.h"

static char *last_report = NULL;

void
vgp_set_report(const char *report)
{
	if (last_report)
		pfree(last_report);
	last_report = report ? MemoryContextStrdup(TopMemoryContext, report) : NULL;
}

PG_FUNCTION_INFO_V1(vg_planner_last_report);

Datum
vg_planner_last_report(PG_FUNCTION_ARGS)
{
	if (last_report == NULL)
		PG_RETURN_NULL();
	PG_RETURN_TEXT_P(cstring_to_text(last_report));
}

/*
 * Record a sub-query relation's own range table (VgpAdvice.subqueries), so
 * the check can find its scans after PostgreSQL removes the SubqueryScan.
 */
void
vgp_note_subquery(RelOptInfo *rel, RangeTblEntry *rte)
{
	VgpAdvice  *adv = vgp_statement_advice();
	MemoryContext old;
	VgpSubquery *sq;
	ListCell   *lc;

	if (adv == NULL || rte->rtekind != RTE_SUBQUERY || rte->eref == NULL ||
		rel->subroot == NULL)
		return;
	old = MemoryContextSwitchTo(adv->cxt);
	sq = palloc0(sizeof(VgpSubquery));
	sq->eref = rte->eref;
	foreach(lc, rel->subroot->parse->rtable)
		sq->inner_erefs = lappend(sq->inner_erefs,
								  lfirst_node(RangeTblEntry, lc)->eref);
	adv->subqueries = lappend(adv->subqueries, sq);
	MemoryContextSwitchTo(old);
}

/*
 * A UNION ALL sub-query PostgreSQL pulled up into an append relation: its
 * branches are child sub-query relations of their own, planned separately, and
 * the parent has no sub-plan. Record the children as the parent's relations,
 * so a branch's scans map to the parent (the UNION) a join of the outer query
 * is advised with.
 */
void
vgp_note_appendrel(PlannerInfo *root, Index rti, RangeTblEntry *rte)
{
	VgpAdvice  *adv = vgp_statement_advice();
	MemoryContext old;
	VgpSubquery *sq = NULL;
	ListCell   *lc;

	if (adv == NULL || rte->rtekind != RTE_SUBQUERY || !rte->inh || rte->eref == NULL)
		return;
	old = MemoryContextSwitchTo(adv->cxt);
	foreach(lc, root->append_rel_list)
	{
		AppendRelInfo *ai = lfirst_node(AppendRelInfo, lc);

		if (ai->parent_relid != rti)
			continue;
		if (sq == NULL)
		{
			sq = palloc0(sizeof(VgpSubquery));
			sq->eref = rte->eref;
		}
		sq->inner_erefs = lappend(sq->inner_erefs, planner_rt_fetch(ai->child_relid, root)->eref);
	}
	if (sq != NULL)
		adv->subqueries = lappend(adv->subqueries, sq);
	MemoryContextSwitchTo(old);
}

/*
 * Per range-table index of the finished plan, the index of the sub-query
 * relation whose plan it belongs to, 0 at the top level.
 */
static int *
scope_parents(PlannedStmt *pstmt, VgpAdvice *advice)
{
	int			n = list_length(pstmt->rtable);
	int		   *parent = palloc0(sizeof(int) * (n + 1));
	ListCell   *lc,
			   *lq;

	foreach(lq, advice->subqueries)
	{
		VgpSubquery *sq = (VgpSubquery *) lfirst(lq);
		int			owner = 0,
					i = 0;

		foreach(lc, pstmt->rtable)
		{
			i++;
			if (lfirst_node(RangeTblEntry, lc)->eref == sq->eref)
				owner = i;
		}
		if (owner == 0)
			continue;
		i = 0;
		foreach(lc, pstmt->rtable)
		{
			Alias	   *eref = lfirst_node(RangeTblEntry, lc)->eref;

			i++;
			/*
			 * The innermost owner wins. A pulled-up UNION's branches are in its
			 * enclosing sub-query's range table too; sub-queries are noted inner
			 * first (a sub-query's relations are planned before it), so the
			 * UNION, noted earlier, is kept.
			 */
			if (i != owner && eref != NULL && parent[i] == 0 &&
				list_member_ptr(sq->inner_erefs, eref))
				parent[i] = owner;
		}
	}
	return parent;
}

/* `rti` and its enclosing sub-query relations, outermost first; returns the length. */
static int
scope_chain(int *parent, int rti, int *chain, int max)
{
	int			len = 0;

	for (int x = rti; x > 0 && len < max; x = parent[x])
		chain[len++] = x;
	for (int i = 0; i < len / 2; i++)
	{
		int			t = chain[i];

		chain[i] = chain[len - 1 - i];
		chain[len - 1 - i] = t;
	}
	return len;
}

#define VGP_MAX_SCOPE 16

/*
 * `part` (a subset of `all`, both scanned under one join node) as the
 * relations that join is between: each index replaced by its enclosing
 * sub-query relation at the level just below the deepest one holding all of
 * `all`. A join of `a` with sub-query `g`'s scans is a join of a and g; a join
 * inside g stays a join of g's own relations.
 */
static Bitmapset *
in_scope(int *parent, Bitmapset *all, Bitmapset *part)
{
	int			common = VGP_MAX_SCOPE;
	int			first[VGP_MAX_SCOPE],
				nfirst = -1,
				chain[VGP_MAX_SCOPE],
				len,
				x = -1;
	Bitmapset  *out = NULL;

	while ((x = bms_next_member(all, x)) >= 0)
	{
		len = scope_chain(parent, x, chain, VGP_MAX_SCOPE);
		if (nfirst < 0)
		{
			memcpy(first, chain, sizeof(int) * len);
			nfirst = len;
			common = len - 1;
			continue;
		}
		for (int i = 0; i < common; i++)
			if (i >= len - 1 || chain[i] != first[i])
			{
				common = i;
				break;
			}
	}
	x = -1;
	while ((x = bms_next_member(part, x)) >= 0)
	{
		len = scope_chain(parent, x, chain, VGP_MAX_SCOPE);
		out = bms_add_member(out, chain[Min(common, len - 1)]);
	}
	return out;
}

/* scanrelid of a scan node, 0 for anything else */
static Index
scan_rti(Plan *plan)
{
	switch (nodeTag(plan))
	{
		case T_SeqScan:
		case T_SampleScan:
		case T_IndexScan:
		case T_IndexOnlyScan:
		case T_BitmapIndexScan:
		case T_BitmapHeapScan:
		case T_TidScan:
		case T_TidRangeScan:
		case T_SubqueryScan:
		case T_FunctionScan:
		case T_TableFuncScan:
		case T_ValuesScan:
		case T_CteScan:
		case T_NamedTuplestoreScan:
		case T_WorkTableScan:
		case T_ForeignScan:
		case T_CustomScan:
			return ((Scan *) plan)->scanrelid;
		default:
			return 0;
	}
}

static List *
child_plans(Plan *plan)
{
	List	   *kids = NIL;

	if (plan->lefttree)
		kids = lappend(kids, plan->lefttree);
	if (plan->righttree)
		kids = lappend(kids, plan->righttree);
	switch (nodeTag(plan))
	{
		case T_Append:
			kids = list_concat(kids, ((Append *) plan)->appendplans);
			break;
		case T_MergeAppend:
			kids = list_concat(kids, ((MergeAppend *) plan)->mergeplans);
			break;
		case T_SubqueryScan:
			kids = lappend(kids, ((SubqueryScan *) plan)->subplan);
			break;
		case T_CustomScan:
			kids = list_concat(kids, ((CustomScan *) plan)->custom_plans);
			break;
		case T_BitmapAnd:
			kids = list_concat(kids, ((BitmapAnd *) plan)->bitmapplans);
			break;
		case T_BitmapOr:
			kids = list_concat(kids, ((BitmapOr *) plan)->bitmapplans);
			break;
		default:
			break;
	}
	return kids;
}

/* Range-table indexes scanned anywhere under `plan`. */
static Bitmapset *
scanned(Plan *plan)
{
	Bitmapset  *out = NULL;
	ListCell   *lc;
	Index		rti;

	if (plan == NULL)
		return NULL;
	rti = scan_rti(plan);
	if (rti > 0)
		out = bms_add_member(out, (int) rti);
	foreach(lc, child_plans(plan))
		out = bms_add_members(out, scanned((Plan *) lfirst(lc)));
	return out;
}

typedef struct CheckBgp
{
	VgpBgp	   *bgp;
	int		   *rti;			/* per step, 0 = not in the plan's range table */
	Bitmapset  *all;
	Bitmapset **prefix;			/* NULL past a missing step */
	VgpMethod  *found;			/* method of the join adding step k, NONE = not found */
} CheckBgp;

static VgpMethod
node_method(Plan *plan)
{
	switch (nodeTag(plan))
	{
		case T_NestLoop:
			if (plan->righttree && IsA(plan->righttree, Memoize))
				return VGP_M_NLMEMO;
			return VGP_M_NL;
		case T_HashJoin:
			return VGP_M_HASH;
		case T_MergeJoin:
			return VGP_M_MERGE;
		default:
			return VGP_M_NONE;
	}
}

static void
visit(Plan *plan, CheckBgp *cb, int ncb, int *parent)
{
	ListCell   *lc;
	VgpMethod	m;

	if (plan == NULL)
		return;
	m = node_method(plan);
	if (m != VGP_M_NONE)
	{
		Bitmapset  *l = scanned(plan->lefttree);
		Bitmapset  *r = scanned(plan->righttree);
		Bitmapset  *lr = bms_union(l, r);

		l = in_scope(parent, lr, l);
		r = in_scope(parent, lr, r);

		for (int b = 0; b < ncb; b++)
		{
			Bitmapset  *sl = bms_intersect(l, cb[b].all);
			Bitmapset  *sr = bms_intersect(r, cb[b].all);

			if (bms_membership(sr) != BMS_SINGLETON)
				continue;
			for (int k = 1; k < cb[b].bgp->nsteps; k++)
				if (cb[b].prefix[k - 1] && cb[b].rti[k] &&
					bms_singleton_member(sr) == cb[b].rti[k] &&
					bms_equal(sl, cb[b].prefix[k - 1]))
					cb[b].found[k] = m;
		}
	}
	foreach(lc, child_plans(plan))
		visit((Plan *) lfirst(lc), cb, ncb, parent);
}

/* Was `name` the inner side of a semi-join during join search (VgpProblem.transparent)? */
static bool
is_transparent(VgpAdvice *advice, const char *name)
{
	ListCell   *lc;

	foreach(lc, advice->transparent_names)
		if (strcmp((const char *) lfirst(lc), name) == 0)
			return true;
	return false;
}

/*
 * The RTE_RELATION aliases scanned under a join node (`rtis`) equal method item
 * m's, ignoring the relations join search found on the inner side of a
 * semi-join (VgpProblem.transparent), as join search itself does.
 */
static bool
alias_set_equals(PlannedStmt *pstmt, Bitmapset *rtis, VgpMethodItem *m, VgpAdvice *advice)
{
	int			n = 0,
				x = -1;

	while ((x = bms_next_member(rtis, x)) >= 0)
	{
		RangeTblEntry *rte = rt_fetch(x, pstmt->rtable);
		bool		hit = false;

		if (!VGP_NAMEABLE_RTE(rte))
			continue;
		if (rte->eref && is_transparent(advice, rte->eref->aliasname))
			continue;
		n++;
		for (int i = 0; i < m->naliases && !hit; i++)
			hit = rte->eref && strcmp(rte->eref->aliasname, m->aliases[i]) == 0;
		if (!hit)
			return false;
	}
	return n == m->naliases;
}

/*
 * Every relation scanned under `sub` is a decode relation (alias `vgd_`, a term
 * row LEFT JOINed by key, transparent): a join with such a side is a lookup above
 * the advised join, not the join (VgpProblem.decode, as join search skips it).
 */
static bool
only_decode(PlannedStmt *pstmt, Plan *sub, VgpAdvice *advice)
{
	Bitmapset  *rtis = sub ? scanned(sub) : NULL;
	int			n = 0,
				x = -1;

	while ((x = bms_next_member(rtis, x)) >= 0)
	{
		RangeTblEntry *rte = rt_fetch(x, pstmt->rtable);

		if (!VGP_NAMEABLE_RTE(rte))
			continue;
		if (!(rte->eref && strncmp(rte->eref->aliasname, "vgd_", 4) == 0 &&
			  is_transparent(advice, rte->eref->aliasname)))
			return false;
		n++;
	}
	return n > 0;
}

static void
check_methods(PlannedStmt *pstmt, Plan *plan, VgpAdvice *advice, int *parent)
{
	ListCell   *lc;
	VgpMethod	m;

	if (plan == NULL)
		return;
	m = node_method(plan);
	if (m != VGP_M_NONE && (only_decode(pstmt, plan->lefttree, advice) ||
							only_decode(pstmt, plan->righttree, advice)))
		m = VGP_M_NONE;
	if (m != VGP_M_NONE)
	{
		Bitmapset  *all = scanned(plan);

		all = in_scope(parent, all, all);

		for (int z = 0; z < advice->nmethods; z++)
		{
			VgpMethodItem *it = &advice->methods[z];

			if (it->seen == VGP_M_NONE && alias_set_equals(pstmt, all, it, advice))
			{
				it->seen = m;
				it->status = (it->set_based == (m == VGP_M_HASH || m == VGP_M_MERGE))
					? VGP_ST_APPLIED : VGP_ST_VIOLATED;
			}
		}
	}
	foreach(lc, child_plans(plan))
		check_methods(pstmt, (Plan *) lfirst(lc), advice, parent);
}

static const char *
status_name(VgpStatus s)
{
	return s == VGP_ST_APPLIED ? "applied" : "NOT APPLIED";
}

void
vgp_check_plan(PlannedStmt *pstmt, VgpAdvice *advice)
{
	CheckBgp   *cb = palloc0(sizeof(CheckBgp) * Max(advice->nbgps, 1));
	int		   *parent;
	ListCell   *lc;
	StringInfoData rep;
	StringInfoData bad;

	for (int b = 0; b < advice->nbgps; b++)
	{
		VgpBgp	   *bgp = &advice->bgps[b];
		Bitmapset  *acc = NULL;
		bool		gap = false;

		cb[b].bgp = bgp;
		cb[b].rti = palloc0(sizeof(int) * bgp->nsteps);
		cb[b].prefix = palloc0(sizeof(Bitmapset *) * bgp->nsteps);
		cb[b].found = palloc0(sizeof(VgpMethod) * bgp->nsteps);
		for (int s = 0; s < bgp->nsteps; s++)
		{
			int			i = 0;

			foreach(lc, pstmt->rtable)
			{
				RangeTblEntry *rte = lfirst_node(RangeTblEntry, lc);

				i++;
				if (VGP_NAMEABLE_RTE(rte) &&
					strcmp(rte->eref->aliasname, bgp->steps[s].alias) == 0)
				{
					cb[b].rti[s] = i;
					break;
				}
			}
			if (cb[b].rti[s] == 0)
			{
				gap = true;
				continue;
			}
			cb[b].all = bms_add_member(cb[b].all, cb[b].rti[s]);
			if (!gap)
			{
				acc = bms_add_member(bms_copy(acc), cb[b].rti[s]);
				cb[b].prefix[s] = acc;
			}
		}
	}

	parent = scope_parents(pstmt, advice);
	visit(pstmt->planTree, cb, advice->nbgps, parent);
	foreach(lc, pstmt->subplans)
		visit((Plan *) lfirst(lc), cb, advice->nbgps, parent);
	if (advice->nmethods > 0)
	{
		check_methods(pstmt, pstmt->planTree, advice, parent);
		foreach(lc, pstmt->subplans)
			check_methods(pstmt, (Plan *) lfirst(lc), advice, parent);
	}

	initStringInfo(&rep);
	initStringInfo(&bad);
	for (int b = 0; b < advice->nbgps; b++)
	{
		VgpBgp	   *bgp = &advice->bgps[b];

		appendStringInfo(&rep, "%sbgp %s", b ? "\n" : "", bgp->name);
		for (int k = 1; k < bgp->nsteps; k++)
		{
			VgpStep    *st = &bgp->steps[k];
			VgpMethod	got = cb[b].found[k];

			if (st->method != VGP_M_NONE)
				st->method_status = got == st->method ? VGP_ST_APPLIED : VGP_ST_VIOLATED;
			if (bgp->enforce_order)
				st->order_status = got != VGP_M_NONE ? VGP_ST_APPLIED : VGP_ST_VIOLATED;

			appendStringInfo(&rep, "\n  %s:", st->alias);
			if (st->has_rows)
			{
				appendStringInfo(&rep, " rows %.0f %s", st->rows, status_name(st->rows_status));
				if (st->pg_rows >= 0)
					appendStringInfo(&rep, " (PostgreSQL %.0f)", st->pg_rows);
				if (st->rows_status != VGP_ST_APPLIED)
					appendStringInfo(&bad, "%s%s.%s rows", bad.len ? ", " : "", bgp->name, st->alias);
			}
			if (st->method != VGP_M_NONE)
			{
				appendStringInfo(&rep, " join %s %s", vgp_method_name(st->method),
								 status_name(st->method_status));
				if (st->method_status != VGP_ST_APPLIED)
				{
					appendStringInfo(&rep, " (plan: %s)",
									 got == VGP_M_NONE ? "no such join" : vgp_method_name(got));
					appendStringInfo(&bad, "%s%s.%s join", bad.len ? ", " : "", bgp->name, st->alias);
				}
			}
			if (bgp->enforce_order)
			{
				appendStringInfo(&rep, " order %s", status_name(st->order_status));
				if (st->order_status != VGP_ST_APPLIED)
					appendStringInfo(&bad, "%s%s.%s order", bad.len ? ", " : "", bgp->name, st->alias);
			}
		}
	}
	for (int z = 0; z < advice->nsizes; z++)
	{
		VgpSize    *sz = &advice->sizes[z];

		appendStringInfo(&rep, "%ssize %s: %.0f %s", rep.len ? "\n" : "", sz->name, sz->rows,
						 status_name(sz->status));
		if (sz->pg_rows >= 0)
			appendStringInfo(&rep, " (PostgreSQL %.0f)", sz->pg_rows);
		if (sz->status != VGP_ST_APPLIED)
			appendStringInfo(&bad, "%ssize %s", bad.len ? ", " : "", sz->name);
	}
	for (int z = 0; z < advice->nmethods; z++)
	{
		VgpMethodItem *it = &advice->methods[z];

		appendStringInfo(&rep, "%smethod %s: %s %s", rep.len ? "\n" : "", it->name,
						 it->set_based ? "hash" : "nl", status_name(it->status));
		if (it->status != VGP_ST_APPLIED)
		{
			appendStringInfo(&rep, " (plan: %s)",
							 it->seen == VGP_M_NONE ? "no such join" : vgp_method_name(it->seen));
			appendStringInfo(&bad, "%smethod %s", bad.len ? ", " : "", it->name);
		}
	}
	vgp_set_report(rep.data);
	if (vgp_debug)
		elog(NOTICE, "vg_planner report:\n%s", rep.data);
	if (bad.len)
		ereport(vgp_on_mismatch == VGP_MISMATCH_ERROR ? ERROR : WARNING,
				(errcode(ERRCODE_INVALID_PARAMETER_VALUE),
				 errmsg("vg_planner: advice not applied: %s", bad.data),
				 errdetail("%s", rep.data)));
}
