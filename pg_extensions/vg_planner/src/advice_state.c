/*-------------------------------------------------------------------------
 *
 * advice_state.c
 *	  Per-statement advice, and per-join-problem alias resolution.
 *
 * A statement's advice is pushed by the planner hook and popped when
 * planning ends (or errors). Subqueries and SubPlans are planned inside the
 * same planner() call, so they see the same advice. A nested planner() call
 * (SPI from a function evaluated at plan time) pushes its own entry, usually
 * with no advice.
 *
 * Aliases are unique across the statement (the generator guarantees it, and
 * vgp_check_statement_aliases errors if not), so an advised alias identifies
 * one range-table entry wherever it is planned. Within a join problem it is
 * resolved to that PlannerInfo's relid.
 *
 *-------------------------------------------------------------------------
 */
#include "postgres.h"

#include "nodes/nodeFuncs.h"
#include "parser/parsetree.h"
#include "utils/hsearch.h"
#include "utils/memutils.h"

#include "vg_planner.h"

static List *statement_stack = NIL; /* of VgpAdvice * (NULL entries allowed) */
static List *problem_stack = NIL;	/* of VgpProblem * */

void
vgp_statement_push(VgpAdvice *advice)
{
	MemoryContext old = MemoryContextSwitchTo(TopMemoryContext);

	statement_stack = lcons(advice, statement_stack);
	MemoryContextSwitchTo(old);
}

void
vgp_statement_pop(void)
{
	Assert(statement_stack != NIL);
	statement_stack = list_delete_first(statement_stack);
}

VgpAdvice *
vgp_statement_advice(void)
{
	return statement_stack ? (VgpAdvice *) linitial(statement_stack) : NULL;
}

/* ---------- the statement-wide alias check ---------- */

typedef struct AliasCount
{
	VgpAdvice  *advice;
	int		  **counts;			/* [bgp][step] */
	int		  **scounts;		/* [size][alias] */
	int		  **mcounts;		/* [method][alias] */
} AliasCount;

static void
count_rte(RangeTblEntry *rte, AliasCount *ac)
{
	const char *name;

	if (!VGP_NAMEABLE_RTE(rte))
		return;
	name = rte->eref->aliasname;
	for (int b = 0; b < ac->advice->nbgps; b++)
		for (int s = 0; s < ac->advice->bgps[b].nsteps; s++)
			if (strcmp(ac->advice->bgps[b].steps[s].alias, name) == 0)
				ac->counts[b][s]++;
	for (int z = 0; z < ac->advice->nsizes; z++)
		for (int s = 0; s < ac->advice->sizes[z].naliases; s++)
			if (strcmp(ac->advice->sizes[z].aliases[s], name) == 0)
				ac->scounts[z][s]++;
	for (int z = 0; z < ac->advice->nmethods; z++)
		for (int s = 0; s < ac->advice->methods[z].naliases; s++)
			if (strcmp(ac->advice->methods[z].aliases[s], name) == 0)
				ac->mcounts[z][s]++;
}

static bool count_walker(Node *node, AliasCount *ac);

static bool
count_query(Query *q, AliasCount *ac)
{
	ListCell   *lc;

	foreach(lc, q->rtable)
		count_rte(lfirst_node(RangeTblEntry, lc), ac);
	return query_tree_walker(q, count_walker, ac, 0);
}

static bool
count_walker(Node *node, AliasCount *ac)
{
	if (node == NULL)
		return false;
	if (IsA(node, Query))
		return count_query((Query *) node, ac);
	return expression_tree_walker(node, count_walker, ac);
}

/*
 * Every advised alias must name exactly one relation in the statement.
 * More than one is always an error: the uniqueness the advice relies on is
 * broken. None is a mismatch (the generator advised a relation the statement
 * does not have), handled by on_mismatch.
 */
void
vgp_check_statement_aliases(Query *parse, VgpAdvice *advice)
{
	AliasCount	ac;
	StringInfoData missing;

	ac.advice = advice;
	ac.counts = palloc(sizeof(int *) * Max(advice->nbgps, 1));
	for (int b = 0; b < advice->nbgps; b++)
		ac.counts[b] = palloc0(sizeof(int) * advice->bgps[b].nsteps);
	ac.scounts = palloc(sizeof(int *) * Max(advice->nsizes, 1));
	for (int z = 0; z < advice->nsizes; z++)
		ac.scounts[z] = palloc0(sizeof(int) * advice->sizes[z].naliases);
	ac.mcounts = palloc(sizeof(int *) * Max(advice->nmethods, 1));
	for (int z = 0; z < advice->nmethods; z++)
		ac.mcounts[z] = palloc0(sizeof(int) * advice->methods[z].naliases);
	count_query(parse, &ac);

	initStringInfo(&missing);
	for (int b = 0; b < advice->nbgps; b++)
		for (int s = 0; s < advice->bgps[b].nsteps; s++)
		{
			const char *alias = advice->bgps[b].steps[s].alias;

			if (ac.counts[b][s] > 1)
				ereport(ERROR,
						(errcode(ERRCODE_DUPLICATE_ALIAS),
						 errmsg("vg_planner: advised alias \"%s\" names %d relations in the statement",
								alias, ac.counts[b][s]),
						 errhint("Advice requires aliases unique across the whole statement.")));
			if (ac.counts[b][s] == 0)
				appendStringInfo(&missing, "%s%s.%s", missing.len ? ", " : "",
								 advice->bgps[b].name, alias);
		}
	for (int z = 0; z < advice->nsizes; z++)
		for (int s = 0; s < advice->sizes[z].naliases; s++)
		{
			const char *alias = advice->sizes[z].aliases[s];

			if (ac.scounts[z][s] > 1)
				ereport(ERROR,
						(errcode(ERRCODE_DUPLICATE_ALIAS),
						 errmsg("vg_planner: advised alias \"%s\" names %d relations in the statement",
								alias, ac.scounts[z][s]),
						 errhint("Advice requires aliases unique across the whole statement.")));
			if (ac.scounts[z][s] == 0)
				appendStringInfo(&missing, "%s%s.%s", missing.len ? ", " : "",
								 advice->sizes[z].name, alias);
		}
	for (int z = 0; z < advice->nmethods; z++)
		for (int s = 0; s < advice->methods[z].naliases; s++)
			if (ac.mcounts[z][s] == 0)
				appendStringInfo(&missing, "%s%s.%s", missing.len ? ", " : "",
								 advice->methods[z].name, advice->methods[z].aliases[s]);
	if (missing.len)
		ereport(vgp_on_mismatch == VGP_MISMATCH_ERROR ? ERROR : WARNING,
				(errcode(ERRCODE_UNDEFINED_TABLE),
				 errmsg("vg_planner: advised alias not in the statement: %s", missing.data)));
}

/* ---------- join problems ---------- */

static int
find_relid(PlannerInfo *root, Relids problem_relids, const char *alias)
{
	int			relid = -1;

	while ((relid = bms_next_member(problem_relids, relid)) >= 0)
	{
		RangeTblEntry *rte;

		if (relid >= root->simple_rel_array_size)
			break;
		rte = root->simple_rte_array[relid];
		if (VGP_NAMEABLE_RTE(rte) && strcmp(rte->eref->aliasname, alias) == 0)
			return relid;
	}
	return 0;
}

/*
 * Resolve the advice against one join problem. Returns NULL when no bgp has
 * at least two of its steps in this problem (nothing to do here: the caller
 * then uses core's join search, untouched).
 */
VgpProblem *
vgp_problem_begin(PlannerInfo *root, List *initial_rels, VgpAdvice *advice)
{
	Relids		problem_relids = NULL;
	ListCell   *lc;
	VgpProblem *p;
	int			useful = 0;
	HASHCTL		ctl;

	foreach(lc, initial_rels)
		problem_relids = bms_add_members(problem_relids,
										 ((RelOptInfo *) lfirst(lc))->relids);

	p = palloc0(sizeof(VgpProblem));
	p->root = root;
	p->nbgps = advice->nbgps;
	p->pbgps = palloc0(sizeof(VgpProblemBgp) * Max(advice->nbgps, 1));
	for (int b = 0; b < advice->nbgps; b++)
	{
		VgpProblemBgp *pb = &p->pbgps[b];
		VgpBgp	   *bgp = &advice->bgps[b];
		int			present = 0;
		Relids		acc = NULL;
		bool		gap = false;

		pb->bgp = bgp;
		pb->relid = palloc0(sizeof(int) * bgp->nsteps);
		pb->prefix = palloc0(sizeof(Relids) * bgp->nsteps);
		for (int s = 0; s < bgp->nsteps; s++)
		{
			pb->relid[s] = find_relid(root, problem_relids, bgp->steps[s].alias);
			if (pb->relid[s] == 0)
			{
				gap = true;
				continue;
			}
			present++;
			pb->all = bms_add_member(pb->all, pb->relid[s]);
			if (!gap)
			{
				acc = bms_add_member(bms_copy(acc), pb->relid[s]);
				pb->prefix[s] = acc;
			}
		}
		if (present >= 2)
			useful++;
	}
	p->nsizes = advice->nsizes;
	p->psizes = palloc0(sizeof(VgpProblemSize) * Max(advice->nsizes, 1));
	for (int z = 0; z < advice->nsizes; z++)
	{
		Relids		r = NULL;
		bool		all = true;

		p->psizes[z].size = &advice->sizes[z];
		for (int s = 0; s < advice->sizes[z].naliases && all; s++)
		{
			int			relid = find_relid(root, problem_relids, advice->sizes[z].aliases[s]);

			if (relid == 0)
				all = false;
			else
				r = bms_add_member(r, relid);
		}
		if (all)
		{
			p->psizes[z].relids = r;
			useful++;
		}
	}
	p->nmethods = advice->nmethods;
	p->pmethods = palloc0(sizeof(VgpProblemMethod) * Max(advice->nmethods, 1));
	for (int z = 0; z < advice->nmethods; z++)
	{
		Relids		r = NULL;
		bool		all = true;

		p->pmethods[z].item = &advice->methods[z];
		for (int s = 0; s < advice->methods[z].naliases && all; s++)
		{
			int			relid = find_relid(root, problem_relids, advice->methods[z].aliases[s]);

			if (relid == 0)
				all = false;
			else
				r = bms_add_member(r, relid);
		}
		if (all)
		{
			p->pmethods[z].relids = r;
			useful++;
		}
	}
	if (useful == 0)
		return NULL;

	{
		Relids		named = NULL;
		int			x = -1;

		for (int b = 0; b < p->nbgps; b++)
			named = bms_add_members(named, p->pbgps[b].all);
		for (int z = 0; z < p->nsizes; z++)
			named = bms_add_members(named, p->psizes[z].relids);
		for (int z = 0; z < p->nmethods; z++)
			named = bms_add_members(named, p->pmethods[z].relids);
		foreach(lc, root->join_info_list)
		{
			SpecialJoinInfo *sj = (SpecialJoinInfo *) lfirst(lc);

			if (sj->jointype == JOIN_SEMI)
				p->transparent = bms_add_members(p->transparent, sj->syn_righthand);
		}
		/*
		 * An early decode's term row (alias `vgd_<var>`, qplan's render): LEFT
		 * JOINed inside the unit that binds the variable, it is in every join
		 * above it, which the advice names without it.
		 */
		for (int rti = 1; rti < root->simple_rel_array_size; rti++)
		{
			RangeTblEntry *rte = root->simple_rte_array[rti];

			if (rte && rte->rtekind == RTE_RELATION && rte->eref &&
				strncmp(rte->eref->aliasname, "vgd_", 4) == 0)
				p->transparent = bms_add_member(p->transparent, rti);
		}
		p->transparent = bms_del_members(p->transparent, named);
		while ((x = bms_next_member(p->transparent, x)) >= 0)
		{
			RangeTblEntry *rte = root->simple_rte_array[x];

			if (rte && rte->rtekind == RTE_RELATION && rte->eref)
			{
				MemoryContext old = MemoryContextSwitchTo(advice->cxt);

				advice->transparent_names = lappend(advice->transparent_names,
													pstrdup(rte->eref->aliasname));
				MemoryContextSwitchTo(old);
			}
		}
	}

	if (advice->seen == NULL)
	{
		memset(&ctl, 0, sizeof(ctl));
		ctl.keysize = sizeof(RelOptInfo *);
		ctl.entrysize = sizeof(SeenEntry);
		ctl.hcxt = CurrentMemoryContext;
		advice->seen = hash_create("vg_planner joinrels", 256, &ctl,
								   HASH_ELEM | HASH_BLOBS | HASH_CONTEXT);
	}
	p->seen = advice->seen;
	return p;
}

void
vgp_problem_push(VgpProblem *p)
{
	MemoryContext old = MemoryContextSwitchTo(TopMemoryContext);

	problem_stack = lcons(p, problem_stack);
	MemoryContextSwitchTo(old);
}

void
vgp_problem_pop(void)
{
	Assert(problem_stack != NIL);
	problem_stack = list_delete_first(problem_stack);
}

VgpProblem *
vgp_problem_for(PlannerInfo *root)
{
	if (problem_stack == NIL)
		return NULL;
	if (((VgpProblem *) linitial(problem_stack))->root != root)
		return NULL;
	return (VgpProblem *) linitial(problem_stack);
}
