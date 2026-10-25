/*-------------------------------------------------------------------------
 *
 * advice_rules.c
 *	  What the advice does at the two insertion points of the copied join
 *	  search (pg18_joinsearch.c).
 *
 * For one bgp with steps o0..on, S is the set of its relations present in
 * this join problem and prefix[k] = {o0..ok}. For a join relation J, A is
 * J's relids intersected with S.
 *
 * POINT 1, after build_join_rel (J exists and is sized, no path yet):
 *	  rows   Every join relation carries, per bgp, the correction factor c its
 *	         estimate includes (base relations: 1). PostgreSQL sizes J from
 *	         its first input pair, whose estimates already include their own
 *	         factors c1, c2. The target factor for J is:
 *	           A == prefix[k], rows given for step k:  model rows(k) / raw(k),
 *	             raw(k) being PostgreSQL's estimate for prefix[k] with no
 *	             correction at all (recorded when prefix[k] is built);
 *	           anything else: c1 * c2, the inputs' corrections, unchanged.
 *	         J.rows = PostgreSQL's estimate * target / (c1 * c2), so a
 *	         correction is never applied twice, and prefix[k] itself comes
 *	         out at exactly the model's rows.
 *	  order  (only with `order`) A not empty, not a single step and not a
 *	         prefix: J is marked, and every path for it is generated
 *	         disabled. Other relations may still join anywhere.
 *
 * POINT 2, around each add_paths_to_joinrel(J, outer, inner):
 *	  join   A == prefix[k] and step k has method m:
 *	           outer & S == prefix[k-1] and inner & S == {ok}: only m is
 *	           enabled for this call;
 *	           any other split of prefix[k]: every join method disabled.
 *	         (A method describes "the join that adds ok onto the prefix", so
 *	         advising one also fixes how that join is formed.)
 *
 * Disabling never removes a path in PostgreSQL 18: it counts disabled nodes,
 * so a legal plan always exists. Whether the final plan complies is checked
 * after planning (advice_check.c), not assumed.
 *
 *-------------------------------------------------------------------------
 */
#include "postgres.h"

#include "optimizer/cost.h"
#include "optimizer/optimizer.h"
#include "optimizer/pathnode.h"
#include "optimizer/paths.h"
#include "utils/hsearch.h"

#include "vg_planner.h"

#define MARK_SIZED		0x1
#define MARK_DISABLED	0x2

static double
factor_of(VgpProblem *p, RelOptInfo *rel, int b)
{
	SeenEntry  *e = hash_search(p->seen, &rel, HASH_FIND, NULL);

	return (e && e->factor) ? e->factor[b] : 1.0;
}

/* The k with A == prefix[k], k >= 1; -1 if A is not such a prefix. */
static int
prefix_index(VgpProblemBgp *pb, Relids a)
{
	int			n = bms_num_members(a);

	if (n < 2)
		return -1;
	for (int k = 1; k < pb->bgp->nsteps; k++)
	{
		if (pb->prefix[k] == NULL)
			break;
		if (bms_num_members(pb->prefix[k]) == n)
			return bms_equal(pb->prefix[k], a) ? k : -1;
	}
	return -1;
}

void
vgp_joinrel_built(PlannerInfo *root, RelOptInfo *joinrel,
				  RelOptInfo *rel1, RelOptInfo *rel2)
{
	VgpProblem *p = vgp_problem_for(root);
	SeenEntry  *e;
	bool		found;
	double		pg_rows,
				scale = 1.0;
	Relids		base;

	if (p == NULL)
		return;
	e = hash_search(p->seen, &joinrel, HASH_ENTER, &found);
	if (found)
		return;					/* sized when first built */
	e->marks = 0;
	/*
	 * Base relations only: since PG 16 a join relation that completes an
	 * outer join also carries that join's own RT index in its relids.
	 */
	base = bms_difference(bms_difference(joinrel->relids, root->outer_join_rels), p->transparent);
	e->factor = palloc(sizeof(double) * Max(p->nbgps, 1));
	for (int b = 0; b < p->nbgps; b++)
		e->factor[b] = 1.0;
	pg_rows = joinrel->rows;

	for (int b = 0; b < p->nbgps; b++)
	{
		VgpProblemBgp *pb = &p->pbgps[b];
		double		inherited = factor_of(p, rel1, b) * factor_of(p, rel2, b);
		double		target = inherited;
		Relids		a = bms_intersect(joinrel->relids, pb->all);
		int			k;

		if (bms_num_members(a) >= 2)
		{
			k = prefix_index(pb, a);
			if (k < 0)
			{
				if (pb->bgp->enforce_order)
				{
					e->marks |= MARK_DISABLED;
					if (vgp_debug)
						elog(NOTICE, "vg_planner: %s: joinrel of %d relations is out of order, disabled",
							 pb->bgp->name, bms_num_members(joinrel->relids));
				}
			}
			else
			{
				VgpStep    *st = &pb->bgp->steps[k];

				if (st->has_rows)
				{
					if (bms_equal(base, pb->prefix[k]))
					{
						/* raw: PostgreSQL's estimate with no correction in it */
						st->pg_rows = pg_rows / inherited;
						st->rows_status = VGP_ST_APPLIED;
					}
					if (st->pg_rows > 0)
					{
						target = clamp_row_est(st->rows) / st->pg_rows;
						e->marks |= MARK_SIZED;
					}
				}
			}
		}
		e->factor[b] = target;
		scale *= target / inherited;
	}
	if (scale != 1.0)
	{
		joinrel->rows = clamp_row_est(pg_rows * scale);
		if (vgp_debug)
			elog(NOTICE, "vg_planner: joinrel of %d relations sized %.0f (PostgreSQL %.0f)",
				 bms_num_members(joinrel->relids), joinrel->rows, pg_rows);
	}

	/*
	 * size items: an exact join relation gets the stated rows. The per-bgp
	 * factors stay as they were, so what is built on it is sized by
	 * PostgreSQL from these rows, with no ratio applied again.
	 */
	for (int z = 0; z < p->nsizes; z++)
	{
		VgpProblemSize *ps = &p->psizes[z];

		if (ps->relids && bms_equal(base, ps->relids))
		{
			ps->size->pg_rows = pg_rows;
			joinrel->rows = clamp_row_est(ps->size->rows);
			ps->size->status = VGP_ST_APPLIED;
			if (vgp_debug)
				elog(NOTICE, "vg_planner: size %s: %.0f rows (PostgreSQL %.0f)",
					 ps->size->name, joinrel->rows, pg_rows);
		}
	}
}

/* Which join methods one add_paths_to_joinrel call may generate. */
#define ALLOW_NL		0x1
#define ALLOW_MEMO		0x2
#define ALLOW_HASH		0x4
#define ALLOW_MERGE		0x8
#define ALLOW_ALL		(ALLOW_NL | ALLOW_MEMO | ALLOW_HASH | ALLOW_MERGE)

static int
allow_for(VgpMethod m)
{
	switch (m)
	{
		case VGP_M_NL:
			return ALLOW_NL;
		case VGP_M_NLMEMO:
			return ALLOW_NL | ALLOW_MEMO;
		case VGP_M_HASH:
			return ALLOW_HASH;
		case VGP_M_MERGE:
			return ALLOW_MERGE;
		default:
			return ALLOW_ALL;
	}
}

static int
pair_allowance(VgpProblem *p, RelOptInfo *joinrel,
			   RelOptInfo *outerrel, RelOptInfo *innerrel)
{
	int			allow = ALLOW_ALL;
	SeenEntry  *e = hash_search(p->seen, &joinrel, HASH_FIND, NULL);

	if (e && (e->marks & MARK_DISABLED))
		return 0;

	/* method items: the planner's choice for exactly this join relation */
	if (p->nmethods > 0)
	{
		Relids		base = bms_difference(bms_difference(joinrel->relids, p->root->outer_join_rels),
										  p->transparent);

		for (int z = 0; z < p->nmethods; z++)
		{
			VgpProblemMethod *pm = &p->pmethods[z];

			if (pm->relids && bms_equal(base, pm->relids))
				allow &= pm->item->set_based ? (ALLOW_HASH | ALLOW_MERGE) : (ALLOW_NL | ALLOW_MEMO);
		}
	}

	for (int b = 0; b < p->nbgps; b++)
	{
		VgpProblemBgp *pb = &p->pbgps[b];
		Relids		a = bms_intersect(joinrel->relids, pb->all);
		int			k = prefix_index(pb, a);
		VgpStep    *st;
		Relids		ao,
					ai;

		if (k < 0)
			continue;
		st = &pb->bgp->steps[k];
		if (st->method == VGP_M_NONE && !pb->bgp->enforce_order)
			continue;
		ao = bms_intersect(outerrel->relids, pb->all);
		ai = bms_intersect(innerrel->relids, pb->all);

		/*
		 * One side has no step: this join adds only other relations onto a
		 * relation that already holds the prefix. Not the advised join, and
		 * not a reordering; unconstrained.
		 */
		if (bms_is_empty(ao) || bms_is_empty(ai))
			continue;
		if (bms_equal(ao, pb->prefix[k - 1]) &&
			bms_membership(ai) == BMS_SINGLETON &&
			bms_singleton_member(ai) == pb->relid[k])
			allow &= allow_for(st->method);
		else
		{
			/*
			 * Another split of the same prefix: with a method advised it is
			 * not the advised join, and under `order` it reorders the steps.
			 */
			allow = 0;
		}
	}
	return allow;
}

void
vgp_add_paths_to_joinrel(PlannerInfo *root, RelOptInfo *joinrel,
						 RelOptInfo *outerrel, RelOptInfo *innerrel,
						 JoinType jointype, SpecialJoinInfo *sjinfo,
						 List *restrictlist)
{
	VgpProblem *p = vgp_problem_for(root);
	int			allow = p ? pair_allowance(p, joinrel, outerrel, innerrel) : ALLOW_ALL;
	bool		save_nl = enable_nestloop,
				save_memo = enable_memoize,
				save_hash = enable_hashjoin,
				save_merge = enable_mergejoin;

	if (allow == ALLOW_ALL)
	{
		add_paths_to_joinrel(root, joinrel, outerrel, innerrel, jointype,
							 sjinfo, restrictlist);
		return;
	}

	/* Narrow, never widen: a method the session turned off stays off. */
	enable_nestloop = save_nl && (allow & ALLOW_NL);
	enable_memoize = save_memo && (allow & ALLOW_MEMO);
	enable_hashjoin = save_hash && (allow & ALLOW_HASH);
	enable_mergejoin = save_merge && (allow & ALLOW_MERGE);
	PG_TRY();
	{
		add_paths_to_joinrel(root, joinrel, outerrel, innerrel, jointype,
							 sjinfo, restrictlist);
	}
	PG_FINALLY();
	{
		enable_nestloop = save_nl;
		enable_memoize = save_memo;
		enable_hashjoin = save_hash;
		enable_mergejoin = save_merge;
	}
	PG_END_TRY();
}


/*
 * A one-alias `size` item: the base relation's scan. Called from
 * set_rel_pathlist_hook, after the scan paths are built and before any join
 * reads them. Sets rel->rows and rescales the rows of every path that is not
 * parameterised (a parameterised path's rows are per outer row and stay
 * PostgreSQL's), partial paths by the same ratio.
 *
 * This is the estimate every join above it is built on. Measured
 * (planning_planner/results/calibration.md): a decision scan estimated at 1 row
 * (actual 1,159) put a hash join on the inner side of a nested loop, rebuilt
 * 2,318 times, 87.6M index rows, 8.5 s instead of 0.1 s.
 */
void
vgp_size_base_rel(PlannerInfo *root, RelOptInfo *rel, Index rti, RangeTblEntry *rte)
{
	VgpAdvice  *adv = vgp_statement_advice();
	ListCell   *lc;

	if (adv == NULL || !VGP_NAMEABLE_RTE(rte))
		return;
	for (int z = 0; z < adv->nsizes; z++)
	{
		VgpSize    *sz = &adv->sizes[z];
		double		old,
					ratio;

		if (sz->naliases != 1 || strcmp(sz->aliases[0], rte->eref->aliasname) != 0)
			continue;
		old = rel->rows;
		sz->pg_rows = old;
		rel->rows = clamp_row_est(sz->rows);
		ratio = old > 0 ? rel->rows / old : 1.0;
		/*
		 * Rows AND run cost, by the same ratio. Rows alone made a 966-row scan
		 * cost what PostgreSQL computed for 1 row, so re-running a subtree per
		 * outer row looked free: a nested loop rescanned an OPTIONAL star 2,319
		 * times (results/calibration.md). A scan's run cost is close to
		 * proportional to the rows it returns; the startup cost stays.
		 */
		foreach(lc, rel->pathlist)
		{
			Path	   *path = (Path *) lfirst(lc);

			if (path->param_info == NULL)
			{
				path->rows = rel->rows;
				path->total_cost = path->startup_cost +
					(path->total_cost - path->startup_cost) * ratio;
			}
		}
		foreach(lc, rel->partial_pathlist)
		{
			Path	   *path = (Path *) lfirst(lc);

			if (path->param_info == NULL)
			{
				path->rows = clamp_row_est(path->rows * ratio);
				path->total_cost = path->startup_cost +
					(path->total_cost - path->startup_cost) * ratio;
			}
		}
		/* the cheapest-path pointers were chosen on the old costs */
		set_cheapest(rel);
		sz->status = VGP_ST_APPLIED;
		if (vgp_debug)
			elog(NOTICE, "vg_planner: size %s: scan of %s %.0f rows (PostgreSQL %.0f)",
				 sz->name, rte->eref->aliasname, rel->rows, old);
	}
}
