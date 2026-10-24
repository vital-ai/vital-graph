/*-------------------------------------------------------------------------
 *
 * vg_planner.h
 *	  Shared declarations for the vg_planner extension.
 *
 * Layout:
 *	  vg_planner.c       module entry, settings, planner/join-search hooks
 *	  advice_parse.c     the advice comment -> VgpAdvice
 *	  advice_state.c     per-statement state; alias -> relid per join problem
 *	  advice_rules.c     what happens at the two insertion points
 *	  advice_check.c     post-plan verification and the report
 *	  pg18_joinsearch.c  GENERATED copy of PostgreSQL 18.4's join search
 *
 * Only pg18_joinsearch.c knows how the hooks are wired into core; everything
 * else is written against the declarations here.
 *
 *-------------------------------------------------------------------------
 */
#ifndef VG_PLANNER_H
#define VG_PLANNER_H

#include "nodes/pathnodes.h"
#include "nodes/plannodes.h"

#define VG_PLANNER_VERSION "0.2.0"

/* The advice comment format version (vg:plan N) this build understands. */
#define VG_ADVICE_FORMAT_VERSION 1

typedef enum VgpMismatch
{
	VGP_MISMATCH_ERROR,
	VGP_MISMATCH_WARNING
} VgpMismatch;

extern bool vgp_enabled;
extern int	vgp_on_mismatch;
extern bool vgp_debug;
extern bool vgp_force_own_search;

/* ---------- advice ---------- */

typedef enum VgpMethod
{
	VGP_M_NONE = 0,
	VGP_M_NL,					/* plain nested loop */
	VGP_M_NLMEMO,				/* nested loop with Memoize on the inner side */
	VGP_M_HASH,
	VGP_M_MERGE
} VgpMethod;

typedef enum VgpStatus
{
	VGP_ST_UNSEEN = 0,			/* never reached (alias or prefix not planned) */
	VGP_ST_APPLIED,
	VGP_ST_VIOLATED
} VgpStatus;

typedef struct VgpStep
{
	char	   *alias;
	bool		has_rows;
	double		rows;			/* rows after joining this step onto the prefix */
	VgpMethod	method;

	/* accounting, filled in while planning */
	VgpStatus	rows_status;
	double		pg_rows;		/* PostgreSQL's raw estimate for the prefix (no correction in it); <0 unknown */
	VgpStatus	method_status;
	VgpStatus	order_status;
} VgpStep;

typedef struct VgpBgp
{
	char	   *name;
	int			nsteps;
	VgpStep    *steps;
	bool		enforce_order;
} VgpBgp;

/* `size NAME ROWS alias ...`: the rows of the join relation made of exactly these relations. */
typedef struct VgpSize
{
	char	   *name;
	double		rows;
	int			naliases;
	char	  **aliases;
	VgpStatus	status;
	double		pg_rows;		/* PostgreSQL's estimate it replaced; <0 unknown */
} VgpSize;

/* `method NAME hash|nl alias ...`: how the join relation made of exactly these
 * relations is formed. hash = two independently built sides (hash or merge
 * join, never a parameterised nested loop); nl = nested loop (an index probe). */
typedef struct VgpMethodItem
{
	char	   *name;
	bool		set_based;		/* hash (or merge) vs nested loop */
	int			naliases;
	char	  **aliases;
	VgpStatus	status;
	VgpMethod	seen;			/* the plan's method for that join, if found */
} VgpMethodItem;

typedef struct VgpAdvice
{
	int			version;
	int			nbgps;
	VgpBgp	   *bgps;
	int			nsizes;
	VgpSize    *sizes;
	int			nmethods;
	VgpMethodItem *methods;
	/*
	 * Join relations seen at insertion point 1, for the whole statement: a
	 * join relation built in one join problem is an input to the next (a
	 * written JOIN tree under join_collapse_limit, a pulled-up subquery), and
	 * its correction factors must travel with it.
	 */
	struct HTAB *seen;
	/*
	 * Aliases of the relations PostgreSQL pulled up from a sub-select into a
	 * SEMI-join, collected during join search (VgpProblem.transparent); the
	 * post-plan check ignores them as join search does. Allocated in `cxt`,
	 * the context the advice was parsed in, which outlives planning.
	 */
	List	   *transparent_names;
	MemoryContext cxt;
} VgpAdvice;

/* advice_parse.c */
extern const char *vgp_find_advice(const char *query_string);
extern VgpAdvice *vgp_parse_advice(const char *text);
extern const char *vgp_method_name(VgpMethod m);

/* advice_state.c */
typedef struct VgpProblemBgp
{
	VgpBgp	   *bgp;
	int		   *relid;			/* per step: relid in this PlannerInfo, 0 = absent */
	Relids		all;			/* every present step's relid */
	Relids	   *prefix;			/* prefix[k] = {relid of steps 0..k}, NULL past a gap */
} VgpProblemBgp;

typedef struct VgpProblemSize
{
	VgpSize    *size;
	Relids		relids;			/* NULL unless every alias is in this problem */
} VgpProblemSize;

typedef struct VgpProblemMethod
{
	VgpMethodItem *item;
	Relids		relids;
} VgpProblemMethod;

/* One join relation seen at insertion point 1 (VgpProblem.seen). */
typedef struct SeenEntry
{
	RelOptInfo *rel;			/* key */
	int			marks;
	double	   *factor;			/* per bgp: correction included in rel->rows */
} SeenEntry;

typedef struct VgpProblem
{
	PlannerInfo *root;
	int			nbgps;
	VgpProblemBgp *pbgps;
	int			nsizes;
	VgpProblemSize *psizes;
	int			nmethods;
	VgpProblemMethod *pmethods;
	struct HTAB *seen;			/* joinrels already handled at point 1 */
	/*
	 * The inner side of every SEMI-join, minus anything the advice names. A
	 * join relation is matched against an advice item on its base relids
	 * WITHOUT these: a sub-select PostgreSQL pulled up into a semi-join (the
	 * generator's range criteria, `o IN (SELECT term_uuid ... WHERE num_val
	 * >= 65)`) only filters its leaf, a filter the advice's rows already
	 * include; without this, every join above such a leaf matched nothing.
	 * ONLY semi-joins: an ordinary join to a relation the advice does not
	 * name changes the row count, and stays visible.
	 */
	Relids		transparent;
} VgpProblem;

extern void vgp_statement_push(VgpAdvice *advice);
extern void vgp_statement_pop(void);
extern VgpAdvice *vgp_statement_advice(void);
extern void vgp_check_statement_aliases(Query *parse, VgpAdvice *advice);

extern VgpProblem *vgp_problem_begin(PlannerInfo *root, List *initial_rels,
									 VgpAdvice *advice);
extern void vgp_problem_push(VgpProblem *p);
extern void vgp_problem_pop(void);
extern VgpProblem *vgp_problem_for(PlannerInfo *root);

/* advice_rules.c: the two insertion points */
extern void vgp_joinrel_built(PlannerInfo *root, RelOptInfo *joinrel,
							  RelOptInfo *rel1, RelOptInfo *rel2);
extern void vgp_add_paths_to_joinrel(PlannerInfo *root, RelOptInfo *joinrel,
									 RelOptInfo *outerrel, RelOptInfo *innerrel,
									 JoinType jointype, SpecialJoinInfo *sjinfo,
									 List *restrictlist);

#define VGP_ADD_PATHS_TO_JOINREL vgp_add_paths_to_joinrel

/* advice_rules.c: base-relation sizes (one-alias size items) */
extern void vgp_size_base_rel(PlannerInfo *root, RelOptInfo *rel, Index rti,
							  RangeTblEntry *rte);

/* advice_check.c */
extern void vgp_check_plan(PlannedStmt *pstmt, VgpAdvice *advice);
extern void vgp_set_report(const char *report);

/* pg18_joinsearch.c */
extern RelOptInfo *vgp_standard_join_search(PlannerInfo *root, int levels_needed,
											List *initial_rels);

#endif							/* VG_PLANNER_H */
