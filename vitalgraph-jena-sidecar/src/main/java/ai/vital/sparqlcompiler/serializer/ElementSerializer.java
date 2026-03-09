package ai.vital.sparqlcompiler.serializer;

import org.apache.jena.graph.Triple;
import org.apache.jena.sparql.syntax.*;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class ElementSerializer {

    public static Map<String, Object> serialize(Element element) {
        if (element == null) {
            return null;
        }

        Map<String, Object> result = new LinkedHashMap<>();

        if (element instanceof ElementGroup group) {
            result.put("type", "ElementGroup");
            List<Map<String, Object>> elements = new ArrayList<>();
            for (Element e : group.getElements()) {
                elements.add(serialize(e));
            }
            result.put("elements", elements);

        } else if (element instanceof ElementTriplesBlock block) {
            result.put("type", "ElementTriplesBlock");
            List<Map<String, Object>> triples = new ArrayList<>();
            for (Triple t : block.getPattern().getList()) {
                triples.add(serializeTriple(t));
            }
            result.put("triples", triples);

        } else if (element instanceof ElementPathBlock pathBlock) {
            result.put("type", "ElementPathBlock");
            List<Map<String, Object>> patterns = new ArrayList<>();
            pathBlock.patternElts().forEachRemaining(tp -> {
                Map<String, Object> tripleMap = new LinkedHashMap<>();
                tripleMap.put("subject", NodeSerializer.serialize(tp.getSubject()));
                if (tp.isTriple()) {
                    tripleMap.put("predicate", NodeSerializer.serialize(tp.getPredicate()));
                } else {
                    Map<String, Object> pathMap = new LinkedHashMap<>();
                    pathMap.put("type", "path");
                    pathMap.put("value", tp.getPath().toString());
                    tripleMap.put("predicate", pathMap);
                }
                tripleMap.put("object", NodeSerializer.serialize(tp.getObject()));
                patterns.add(tripleMap);
            });
            result.put("triples", patterns);

        } else if (element instanceof ElementOptional optional) {
            result.put("type", "ElementOptional");
            result.put("sub", serialize(optional.getOptionalElement()));

        } else if (element instanceof ElementUnion union) {
            result.put("type", "ElementUnion");
            List<Map<String, Object>> elements = new ArrayList<>();
            for (Element e : union.getElements()) {
                elements.add(serialize(e));
            }
            result.put("elements", elements);

        } else if (element instanceof ElementFilter filter) {
            result.put("type", "ElementFilter");
            result.put("expr", ExprSerializer.serialize(filter.getExpr()));

        } else if (element instanceof ElementBind bind) {
            result.put("type", "ElementBind");
            result.put("var", bind.getVar().getVarName());
            result.put("expr", ExprSerializer.serialize(bind.getExpr()));

        } else if (element instanceof ElementSubQuery subQuery) {
            result.put("type", "ElementSubQuery");
            result.put("query", serializeSubQuery(subQuery.getQuery()));

        } else if (element instanceof ElementNamedGraph namedGraph) {
            result.put("type", "ElementNamedGraph");
            result.put("graphNode", NodeSerializer.serialize(namedGraph.getGraphNameNode()));
            result.put("sub", serialize(namedGraph.getElement()));

        } else if (element instanceof ElementMinus minus) {
            result.put("type", "ElementMinus");
            result.put("sub", serialize(minus.getMinusElement()));

        } else if (element instanceof ElementService service) {
            result.put("type", "ElementService");
            result.put("serviceURI", NodeSerializer.serialize(service.getServiceNode()));
            result.put("silent", service.getSilent());
            result.put("sub", serialize(service.getElement()));

        } else if (element instanceof ElementData data) {
            result.put("type", "ElementValues");
            List<String> vars = new ArrayList<>();
            data.getVars().forEach(v -> vars.add(v.getVarName()));
            result.put("vars", vars);
            List<List<Map<String, Object>>> rows = new ArrayList<>();
            data.getRows().forEach(binding -> {
                List<Map<String, Object>> row = new ArrayList<>();
                data.getVars().forEach(v -> {
                    row.add(binding.get(v) != null ? NodeSerializer.serialize(binding.get(v)) : null);
                });
                rows.add(row);
            });
            result.put("rows", rows);

        } else if (element instanceof ElementNotExists notExists) {
            result.put("type", "ElementNotExists");
            result.put("sub", serialize(notExists.getElement()));

        } else if (element instanceof ElementExists exists) {
            result.put("type", "ElementExists");
            result.put("sub", serialize(exists.getElement()));

        } else {
            result.put("type", element.getClass().getSimpleName());
            result.put("string", element.toString());
        }

        return result;
    }

    private static Map<String, Object> serializeTriple(Triple t) {
        Map<String, Object> triple = new LinkedHashMap<>();
        triple.put("subject", NodeSerializer.serialize(t.getSubject()));
        triple.put("predicate", NodeSerializer.serialize(t.getPredicate()));
        triple.put("object", NodeSerializer.serialize(t.getObject()));
        return triple;
    }

    private static Map<String, Object> serializeSubQuery(org.apache.jena.query.Query query) {
        Map<String, Object> q = new LinkedHashMap<>();
        q.put("queryType", query.queryType().toString());

        // Project vars (names only, for backward compat)
        List<String> vars = new ArrayList<>();
        query.getProjectVars().forEach(v -> vars.add(v.getVarName()));
        q.put("projectVars", vars);

        // Project expressions — maps var name to its expression (e.g. COUNT(*))
        // This captures SELECT (expr AS ?var) bindings that projectVars alone misses.
        org.apache.jena.sparql.core.VarExprList project = query.getProject();
        List<Map<String, Object>> projectExprs = new ArrayList<>();
        for (org.apache.jena.sparql.core.Var v : project.getVars()) {
            org.apache.jena.sparql.expr.Expr expr = project.getExpr(v);
            if (expr != null) {
                Map<String, Object> pe = new LinkedHashMap<>();
                pe.put("var", v.getVarName());
                pe.put("expr", ExprSerializer.serialize(expr));
                projectExprs.add(pe);
            }
        }
        if (!projectExprs.isEmpty()) {
            q.put("projectExprs", projectExprs);
        }

        // GROUP BY
        if (query.hasGroupBy()) {
            org.apache.jena.sparql.core.VarExprList groupBy = query.getGroupBy();
            List<Map<String, Object>> groupVars = new ArrayList<>();
            for (org.apache.jena.sparql.core.Var v : groupBy.getVars()) {
                Map<String, Object> entry = new LinkedHashMap<>();
                entry.put("var", v.getVarName());
                org.apache.jena.sparql.expr.Expr gExpr = groupBy.getExpr(v);
                entry.put("expr", gExpr != null ? ExprSerializer.serialize(gExpr) : null);
                groupVars.add(entry);
            }
            q.put("groupBy", groupVars);
        }

        // Aggregators
        if (query.getAggregators() != null && !query.getAggregators().isEmpty()) {
            List<Map<String, Object>> aggregators = new ArrayList<>();
            for (org.apache.jena.sparql.expr.ExprAggregator ea : query.getAggregators()) {
                Map<String, Object> agg = new LinkedHashMap<>();
                agg.put("var", ea.getVar().getVarName());
                agg.put("aggregator", ExprSerializer.serialize(ea));
                aggregators.add(agg);
            }
            q.put("aggregators", aggregators);
        }

        // HAVING
        if (query.hasHaving()) {
            List<Map<String, Object>> having = new ArrayList<>();
            for (org.apache.jena.sparql.expr.Expr expr : query.getHavingExprs()) {
                having.add(ExprSerializer.serialize(expr));
            }
            q.put("having", having);
        }

        // DISTINCT / REDUCED
        if (query.isDistinct()) {
            q.put("distinct", true);
        }

        // ORDER BY
        if (query.hasOrderBy()) {
            List<Map<String, Object>> orderBy = new ArrayList<>();
            for (org.apache.jena.query.SortCondition sc : query.getOrderBy()) {
                Map<String, Object> cond = new LinkedHashMap<>();
                cond.put("direction", sc.getDirection() == -1 ? "DESC" : "ASC");
                cond.put("expr", ExprSerializer.serialize(sc.getExpression()));
                orderBy.add(cond);
            }
            q.put("orderBy", orderBy);
        }

        // LIMIT / OFFSET
        if (query.hasLimit()) {
            q.put("limit", query.getLimit());
        }
        if (query.hasOffset()) {
            q.put("offset", query.getOffset());
        }

        q.put("wherePattern", serialize(query.getQueryPattern()));
        return q;
    }
}
