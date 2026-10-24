/*-------------------------------------------------------------------------
 *
 * vg_planner.c
 *	  VitalGraph planner extension: module entry, settings, hooks.
 *
 * The SQL generator plans each basic graph pattern with its own cardinality
 * model and writes the result into the statement as a leading comment
 * (vg:plan, see advice_parse.c). This extension reads that comment and hands
 * the model's numbers to PostgreSQL's planner: join sizes first, and a join
 * method or order only where the advice says so. A statement without the
 * comment is planned exactly as if the extension were not loaded.
 *
 * Planning notes: planning/planning_planner/ (local, not in the repository).
 *
 *-------------------------------------------------------------------------
 */
#include "postgres.h"

#include "fmgr.h"
#include "miscadmin.h"
#include "optimizer/cost.h"
#include "optimizer/geqo.h"
#include "optimizer/paths.h"
#include "optimizer/planner.h"
#include "utils/builtins.h"
#include "utils/guc.h"

#include "vg_planner.h"

PG_MODULE_MAGIC_EXT(.name = "vg_planner", .version = VG_PLANNER_VERSION);

/* Settings */
bool		vgp_enabled = true;
int			vgp_on_mismatch = VGP_MISMATCH_ERROR;
bool		vgp_debug = false;
bool		vgp_force_own_search = false;

static const struct config_enum_entry on_mismatch_options[] = {
	{"error", VGP_MISMATCH_ERROR, false},
	{"warning", VGP_MISMATCH_WARNING, false},
	{NULL, 0, false}
};

static planner_hook_type prev_planner_hook = NULL;
static join_search_hook_type prev_join_search_hook = NULL;
static set_rel_pathlist_hook_type prev_set_rel_pathlist_hook = NULL;

static void
vgp_set_rel_pathlist(PlannerInfo *root, RelOptInfo *rel, Index rti, RangeTblEntry *rte)
{
	if (prev_set_rel_pathlist_hook)
		prev_set_rel_pathlist_hook(root, rel, rti, rte);
	if (vgp_enabled)
		vgp_size_base_rel(root, rel, rti, rte);
}

PG_FUNCTION_INFO_V1(vg_planner_info);

/*
 * The planner entry point: find and parse the advice, check its aliases
 * against the statement, plan, then check the plan against the advice.
 */
static PlannedStmt *
vgp_planner(Query *parse, const char *query_string, int cursorOptions,
			ParamListInfo boundParams)
{
	VgpAdvice  *advice = NULL;
	PlannedStmt *result;

	if (vgp_enabled)
	{
		const char *mark = vgp_find_advice(query_string);

		if (mark)
		{
			advice = vgp_parse_advice(mark);
			vgp_check_statement_aliases(parse, advice);
		}
	}

	vgp_statement_push(advice);
	PG_TRY();
	{
		if (prev_planner_hook)
			result = prev_planner_hook(parse, query_string, cursorOptions,
									   boundParams);
		else
			result = standard_planner(parse, query_string, cursorOptions,
									  boundParams);
	}
	PG_FINALLY();
	{
		vgp_statement_pop();
	}
	PG_END_TRY();

	if (advice)
		vgp_check_plan(result, advice);
	return result;
}

/*
 * The join-search entry point, called for every join problem of every
 * PlannerInfo (the top level, subqueries and SubPlans).
 *
 * Core's own order of precedence is kept for everything we do not handle:
 * the previous hook, then GEQO above its threshold, then the standard search.
 */
static RelOptInfo *
vgp_join_search(PlannerInfo *root, int levels_needed, List *initial_rels)
{
	VgpAdvice  *advice = vgp_enabled ? vgp_statement_advice() : NULL;
	VgpProblem *p = NULL;
	bool		own;
	RelOptInfo *rel;

	if (advice)
		p = vgp_problem_begin(root, initial_rels, advice);
	own = (p != NULL) || vgp_force_own_search;

	/*
	 * The copy omits partitionwise join, and running exhaustive search above
	 * the GEQO threshold would cost what GEQO exists to avoid. Both fall
	 * through to core; any advice for this problem then reports as not
	 * applied.
	 */
	if (own && (enable_partitionwise_join ||
				(enable_geqo && levels_needed >= geqo_threshold)))
	{
		if (vgp_debug && p)
			elog(NOTICE, "vg_planner: join problem of %d relations left to core (%s)",
				 levels_needed,
				 enable_partitionwise_join ? "enable_partitionwise_join" : "GEQO");
		own = false;
		p = NULL;
	}

	if (!own)
	{
		if (prev_join_search_hook)
			return prev_join_search_hook(root, levels_needed, initial_rels);
		if (enable_geqo && levels_needed >= geqo_threshold)
			return geqo(root, levels_needed, initial_rels);
		return standard_join_search(root, levels_needed, initial_rels);
	}

	if (p == NULL)				/* vg_planner.force_own_search, no advice */
		return vgp_standard_join_search(root, levels_needed, initial_rels);

	vgp_problem_push(p);
	PG_TRY();
	{
		rel = vgp_standard_join_search(root, levels_needed, initial_rels);
	}
	PG_FINALLY();
	{
		vgp_problem_pop();
	}
	PG_END_TRY();
	return rel;
}

void
_PG_init(void)
{
	/*
	 * Planner hooks are process-wide, so the library is meant to be preloaded.
	 * A superuser LOAD also works (tests, experiments); the hooks then apply
	 * to that session only.
	 */
	DefineCustomBoolVariable("vg_planner.enabled",
							 "Apply vg:plan advice to statements that carry it.",
							 "When off, every statement is planned as if the extension were absent.",
							 &vgp_enabled,
							 true,
							 PGC_USERSET,
							 0,
							 NULL, NULL, NULL);

	DefineCustomEnumVariable("vg_planner.on_mismatch",
							 "What to do when an advice item was not applied.",
							 "error fails the statement; warning keeps the plan and warns.",
							 &vgp_on_mismatch,
							 VGP_MISMATCH_ERROR,
							 on_mismatch_options,
							 PGC_USERSET,
							 0,
							 NULL, NULL, NULL);

	DefineCustomBoolVariable("vg_planner.debug",
							 "Report each advice decision as a NOTICE.",
							 NULL,
							 &vgp_debug,
							 false,
							 PGC_USERSET,
							 0,
							 NULL, NULL, NULL);

	DefineCustomBoolVariable("vg_planner.force_own_search",
							 "Testing: run every join problem through the copied join search.",
							 "With no advice the copy must plan exactly as core does; this proves it.",
							 &vgp_force_own_search,
							 false,
							 PGC_SUSET,
							 0,
							 NULL, NULL, NULL);

	MarkGUCPrefixReserved("vg_planner");

	prev_planner_hook = planner_hook;
	planner_hook = vgp_planner;
	prev_join_search_hook = join_search_hook;
	join_search_hook = vgp_join_search;
	prev_set_rel_pathlist_hook = set_rel_pathlist_hook;
	set_rel_pathlist_hook = vgp_set_rel_pathlist;
}

/*
 * vg_planner_info() -> text
 *
 * What the executor's detection reads: the library version, the advice
 * format, and whether this backend has the hooks installed.
 */
Datum
vg_planner_info(PG_FUNCTION_ARGS)
{
	char		buf[128];

	snprintf(buf, sizeof(buf), "vg_planner %s advice=%d hooks=%s",
			 VG_PLANNER_VERSION, VG_ADVICE_FORMAT_VERSION,
			 planner_hook == vgp_planner ? "installed" : "chained");
	PG_RETURN_TEXT_P(cstring_to_text(buf));
}
