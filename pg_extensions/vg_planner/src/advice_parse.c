/*-------------------------------------------------------------------------
 *
 * advice_parse.c
 *	  The advice comment the SQL generator writes, parsed into VgpAdvice.
 *
 *	  (slash-star)vg:plan 1
 *	  bgp b0 steps(q3 q1 q2) rows(q1:1159 q2:4200) join(q1:nl q2:hash) order
 *	  (star-slash)
 *
 * steps(...)   the model's left-deep order; defines the prefixes the other
 *              clauses refer to. Required, at least two.
 * rows(x:n)    rows after joining x onto the steps before it. Not allowed on
 *              the first step (a base relation's estimate is PostgreSQL's).
 * join(x:m)    the method of the join that adds x: nl | nlmemo | hash | merge.
 *              Not allowed on the first step.
 * order        enforce the relative order of the steps (other relations may
 *              still join anywhere).
 *
 * size NAME N alias ...   (a line of its own) the join relation made of
 *              exactly these relations has N rows. For joins the bgp lines do
 *              not cover: between stars, OPTIONAL left joins, the key set
 *              under an ORDER BY / LIMIT. With ONE alias it sizes that base
 *              relation's scan (set_rel_pathlist_hook), the estimate a join
 *              plan is built on first.
 *
 * method NAME hash|nl alias ...   (a line of its own) the join relation made of
 *              exactly these relations is formed by a set-based join (hash or
 *              merge: both sides built independently) or by a nested loop (an
 *              index probe). The planner's choice of join, not a hint.
 *
 * Everything that does not fit this grammar is an error, never skipped: a
 * malformed comment is a generator bug, and ignoring it would measure the
 * wrong plan without saying so.
 *
 *-------------------------------------------------------------------------
 */
#include "postgres.h"

#include <ctype.h>
#include <math.h>

#include "vg_planner.h"

#define ADVICE_MARK "/*vg:plan"

/*
 * Locate the advice comment: at the start of the statement, or right after an
 * EXPLAIN prefix (EXPLAIN [ ( ... ) ] [ ANALYZE ] [ VERBOSE ]), so the advised
 * statement can be EXPLAINed as it is. Returns a pointer to the mark, or NULL.
 */
const char *
vgp_find_advice(const char *s)
{
	if (s == NULL)
		return NULL;
	while (isspace((unsigned char) *s))
		s++;
	if (pg_strncasecmp(s, "explain", 7) == 0 && !isalnum((unsigned char) s[7]))
	{
		s += 7;
		for (;;)
		{
			while (isspace((unsigned char) *s))
				s++;
			if (*s == '(')
			{
				int			depth = 0;

				do
				{
					if (*s == '(')
						depth++;
					else if (*s == ')')
						depth--;
					else if (*s == '\0')
						return NULL;
					s++;
				} while (depth > 0);
				continue;
			}
			if (pg_strncasecmp(s, "analyze", 7) == 0 && !isalnum((unsigned char) s[7]))
			{
				s += 7;
				continue;
			}
			if (pg_strncasecmp(s, "verbose", 7) == 0 && !isalnum((unsigned char) s[7]))
			{
				s += 7;
				continue;
			}
			break;
		}
	}
	if (strncmp(s, ADVICE_MARK, strlen(ADVICE_MARK)) == 0)
		return s;
	return NULL;
}

const char *
vgp_method_name(VgpMethod m)
{
	switch (m)
	{
		case VGP_M_NL:
			return "nl";
		case VGP_M_NLMEMO:
			return "nlmemo";
		case VGP_M_HASH:
			return "hash";
		case VGP_M_MERGE:
			return "merge";
		default:
			return "none";
	}
}

typedef struct Lexer
{
	const char *p;
	const char *end;
} Lexer;

pg_noreturn static void
parse_error(const char *what, const Lexer *lx)
{
	int			n = (int) Min(lx->end - lx->p, 40);

	ereport(ERROR,
			(errcode(ERRCODE_SYNTAX_ERROR),
			 errmsg("vg_planner: malformed advice: %s", what),
			 errdetail("At: \"%.*s\"", n, lx->p)));
}

static void
skip_ws(Lexer *lx)
{
	while (lx->p < lx->end && isspace((unsigned char) *lx->p))
		lx->p++;
}

static bool
is_ident_char(char c)
{
	return (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_';
}

/* An identifier [a-z0-9_]+, palloc'd. */
static char *
read_ident(Lexer *lx, const char *what)
{
	const char *start;

	skip_ws(lx);
	start = lx->p;
	while (lx->p < lx->end && is_ident_char(*lx->p))
		lx->p++;
	if (lx->p == start)
		parse_error(what, lx);
	if (lx->p - start > NAMEDATALEN - 1)
		parse_error("identifier too long", lx);
	return pnstrdup(start, lx->p - start);
}

static bool
accept(Lexer *lx, char c)
{
	skip_ws(lx);
	if (lx->p < lx->end && *lx->p == c)
	{
		lx->p++;
		return true;
	}
	return false;
}

static void
expect(Lexer *lx, char c, const char *what)
{
	if (!accept(lx, c))
		parse_error(what, lx);
}

static double
read_number(Lexer *lx)
{
	char		buf[64];
	int			n = 0;
	char	   *endp;
	double		v;

	skip_ws(lx);
	while (lx->p < lx->end && n < (int) sizeof(buf) - 1 &&
		   (isdigit((unsigned char) *lx->p) || *lx->p == '.' ||
			*lx->p == 'e' || *lx->p == 'E' ||
			((*lx->p == '+' || *lx->p == '-') && n > 0 &&
			 (buf[n - 1] == 'e' || buf[n - 1] == 'E'))))
		buf[n++] = *lx->p++;
	buf[n] = '\0';
	if (n == 0 || !isdigit((unsigned char) buf[0]))
		parse_error("expected a number", lx);
	errno = 0;
	v = strtod(buf, &endp);
	if (*endp != '\0' || errno != 0 || !isfinite(v) || v < 0)
		parse_error("bad number", lx);
	return v;
}

static int
step_index(VgpBgp *b, const char *alias)
{
	for (int i = 0; i < b->nsteps; i++)
		if (strcmp(b->steps[i].alias, alias) == 0)
			return i;
	return -1;
}

static void
parse_steps(Lexer *lx, VgpBgp *b)
{
	List	   *names = NIL;
	ListCell   *lc;
	int			i = 0;

	expect(lx, '(', "expected '(' after steps");
	while (!accept(lx, ')'))
		names = lappend(names, read_ident(lx, "expected an alias in steps(...)"));
	if (list_length(names) < 2)
		parse_error("steps(...) needs at least two aliases", lx);
	b->nsteps = list_length(names);
	b->steps = palloc0(sizeof(VgpStep) * b->nsteps);
	foreach(lc, names)
	{
		b->steps[i].alias = lfirst(lc);
		b->steps[i].pg_rows = -1;
		for (int j = 0; j < i; j++)
			if (strcmp(b->steps[j].alias, b->steps[i].alias) == 0)
				parse_error("alias repeated in steps(...)", lx);
		i++;
	}
}

static VgpStep *
step_for(Lexer *lx, VgpBgp *b, const char *alias, const char *clause)
{
	int			k = step_index(b, alias);

	if (k < 0)
		parse_error(psprintf("%s(...) names \"%s\", which is not in steps(...)",
							 clause, alias), lx);
	if (k == 0)
		parse_error(psprintf("%s(...) cannot apply to the first step \"%s\"",
							 clause, alias), lx);
	return &b->steps[k];
}

static void
parse_rows(Lexer *lx, VgpBgp *b)
{
	expect(lx, '(', "expected '(' after rows");
	while (!accept(lx, ')'))
	{
		char	   *alias = read_ident(lx, "expected alias:rows");
		VgpStep    *st = step_for(lx, b, alias, "rows");

		expect(lx, ':', "expected ':' in rows(alias:n)");
		if (st->has_rows)
			parse_error("rows given twice for one step", lx);
		st->rows = read_number(lx);
		st->has_rows = true;
	}
}

static void
parse_join(Lexer *lx, VgpBgp *b)
{
	expect(lx, '(', "expected '(' after join");
	while (!accept(lx, ')'))
	{
		char	   *alias = read_ident(lx, "expected alias:method");
		VgpStep    *st = step_for(lx, b, alias, "join");
		char	   *m;

		expect(lx, ':', "expected ':' in join(alias:method)");
		m = read_ident(lx, "expected a join method");
		if (st->method != VGP_M_NONE)
			parse_error("join method given twice for one step", lx);
		if (strcmp(m, "nl") == 0)
			st->method = VGP_M_NL;
		else if (strcmp(m, "nlmemo") == 0)
			st->method = VGP_M_NLMEMO;
		else if (strcmp(m, "hash") == 0)
			st->method = VGP_M_HASH;
		else if (strcmp(m, "merge") == 0)
			st->method = VGP_M_MERGE;
		else
			parse_error("unknown join method (nl, nlmemo, hash, merge)", lx);
	}
}

/*
 * Parse the comment that starts at `text` (which must begin with the mark).
 * Allocates in CurrentMemoryContext; errors out on anything malformed.
 */
VgpAdvice *
vgp_parse_advice(const char *text)
{
	Lexer		lx;
	const char *close;
	VgpAdvice  *adv = palloc0(sizeof(VgpAdvice));
	List	   *bgps = NIL;
	List	   *sizes = NIL;
	List	   *methods = NIL;
	ListCell   *lc;
	int			i = 0;

	adv->cxt = CurrentMemoryContext;

	close = strstr(text, "*/");
	lx.p = text + strlen(ADVICE_MARK);
	lx.end = close ? close : text + strlen(text);
	if (close == NULL)
		parse_error("comment is not closed", &lx);

	adv->version = (int) read_number(&lx);
	if (adv->version != VG_ADVICE_FORMAT_VERSION)
		ereport(ERROR,
				(errcode(ERRCODE_FEATURE_NOT_SUPPORTED),
				 errmsg("vg_planner: advice format %d is not supported (this build reads %d)",
						adv->version, VG_ADVICE_FORMAT_VERSION)));

	for (;;)
	{
		char	   *kw;
		VgpBgp	   *b;

		skip_ws(&lx);
		if (lx.p >= lx.end)
			break;
		kw = read_ident(&lx, "expected 'bgp' or 'size'");
		if (strcmp(kw, "method") == 0)
		{
			VgpMethodItem *m = palloc0(sizeof(VgpMethodItem));
			List	   *names = NIL;
			ListCell   *lc2;
			char	   *how;
			int			j = 0;

			m->name = read_ident(&lx, "expected a method item name");
			how = read_ident(&lx, "expected hash or nl");
			if (strcmp(how, "hash") == 0)
				m->set_based = true;
			else if (strcmp(how, "nl") == 0)
				m->set_based = false;
			else
				parse_error("method must be hash or nl", &lx);
			for (;;)
			{
				const char *save;
				char	   *a;

				skip_ws(&lx);
				if (lx.p >= lx.end)
					break;
				save = lx.p;
				a = read_ident(&lx, "expected an alias");
				if (strcmp(a, "bgp") == 0 || strcmp(a, "size") == 0 || strcmp(a, "method") == 0)
				{
					lx.p = save;
					break;
				}
				names = lappend(names, a);
			}
			if (list_length(names) < 2)
				parse_error("method needs at least two aliases", &lx);
			m->naliases = list_length(names);
			m->aliases = palloc(sizeof(char *) * m->naliases);
			foreach(lc2, names)
				m->aliases[j++] = lfirst(lc2);
			methods = lappend(methods, m);
			continue;
		}
		if (strcmp(kw, "size") == 0)
		{
			VgpSize    *z = palloc0(sizeof(VgpSize));
			List	   *names = NIL;
			ListCell   *lc2;
			int			j = 0;

			z->name = read_ident(&lx, "expected a size name");
			z->rows = read_number(&lx);
			z->pg_rows = -1;
			for (;;)
			{
				const char *save;
				char	   *a;

				skip_ws(&lx);
				if (lx.p >= lx.end)
					break;
				save = lx.p;
				a = read_ident(&lx, "expected an alias");
				if (strcmp(a, "bgp") == 0 || strcmp(a, "size") == 0 || strcmp(a, "method") == 0)
				{
					lx.p = save;
					break;
				}
				names = lappend(names, a);
			}
			if (list_length(names) < 1)
				parse_error("size needs at least one alias", &lx);
			z->naliases = list_length(names);
			z->aliases = palloc(sizeof(char *) * z->naliases);
			foreach(lc2, names)
				z->aliases[j++] = lfirst(lc2);
			sizes = lappend(sizes, z);
			continue;
		}
		if (strcmp(kw, "bgp") != 0)
			parse_error("expected 'bgp' or 'size'", &lx);
		b = palloc0(sizeof(VgpBgp));
		b->name = read_ident(&lx, "expected a bgp name");
		for (;;)
		{
			const char *save;
			char	   *clause;

			skip_ws(&lx);
			if (lx.p >= lx.end)
				break;
			save = lx.p;
			clause = read_ident(&lx, "expected a clause");
			if (strcmp(clause, "bgp") == 0 || strcmp(clause, "size") == 0 ||
				strcmp(clause, "method") == 0)
			{
				lx.p = save;
				break;
			}
			if (strcmp(clause, "steps") == 0)
			{
				if (b->steps)
					parse_error("steps(...) given twice", &lx);
				parse_steps(&lx, b);
			}
			else if (b->steps == NULL)
				parse_error("steps(...) must come first", &lx);
			else if (strcmp(clause, "rows") == 0)
				parse_rows(&lx, b);
			else if (strcmp(clause, "join") == 0)
				parse_join(&lx, b);
			else if (strcmp(clause, "order") == 0)
				b->enforce_order = true;
			else
				parse_error("unknown clause (steps, rows, join, order)", &lx);
		}
		if (b->steps == NULL)
			parse_error("bgp without steps(...)", &lx);
		bgps = lappend(bgps, b);
	}

	adv->nbgps = list_length(bgps);
	adv->bgps = palloc0(sizeof(VgpBgp) * Max(adv->nbgps, 1));
	foreach(lc, bgps)
	{
		VgpBgp	   *b = lfirst(lc);

		for (int j = 0; j < i; j++)
		{
			if (strcmp(adv->bgps[j].name, b->name) == 0)
				parse_error("bgp name repeated", &lx);
			for (int s = 0; s < b->nsteps; s++)
				if (step_index(&adv->bgps[j], b->steps[s].alias) >= 0)
					ereport(ERROR,
							(errcode(ERRCODE_SYNTAX_ERROR),
							 errmsg("vg_planner: malformed advice: alias \"%s\" is in two bgps",
									b->steps[s].alias)));
		}
		adv->bgps[i++] = *b;
	}
	adv->nsizes = list_length(sizes);
	adv->sizes = palloc0(sizeof(VgpSize) * Max(adv->nsizes, 1));
	i = 0;
	foreach(lc, sizes)
		adv->sizes[i++] = *(VgpSize *) lfirst(lc);
	adv->nmethods = list_length(methods);
	adv->methods = palloc0(sizeof(VgpMethodItem) * Max(adv->nmethods, 1));
	i = 0;
	foreach(lc, methods)
		adv->methods[i++] = *(VgpMethodItem *) lfirst(lc);
	return adv;
}
