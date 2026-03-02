package ai.vital.sparqlcompiler.util;

import org.apache.jena.query.Query;
import org.apache.jena.query.SortCondition;
import org.apache.jena.sparql.core.Var;
import org.apache.jena.sparql.core.VarExprList;
import org.apache.jena.sparql.expr.Expr;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class QueryMetadataExtractor {

    public static Map<String, Object> extract(Query query) {
        Map<String, Object> meta = new LinkedHashMap<>();

        meta.put("queryType", queryTypeString(query));

        // Project vars
        List<String> projectVars = new ArrayList<>();
        if (query.isSelectType()) {
            if (query.isQueryResultStar()) {
                projectVars.add("*");
            } else {
                for (Var v : query.getProjectVars()) {
                    projectVars.add(v.getVarName());
                }
            }
        }
        meta.put("projectVars", projectVars);

        // Flags
        meta.put("distinct", query.isDistinct());
        meta.put("reduced", query.isReduced());

        // Limit / Offset
        meta.put("limit", query.hasLimit() ? query.getLimit() : -1);
        meta.put("offset", query.hasOffset() ? query.getOffset() : 0);

        // ORDER BY
        List<Map<String, Object>> orderBy = new ArrayList<>();
        if (query.getOrderBy() != null) {
            for (SortCondition sc : query.getOrderBy()) {
                Map<String, Object> cond = new LinkedHashMap<>();
                cond.put("direction", sc.getDirection() == -1 ? "DESC" : "ASC");
                Expr expr = sc.getExpression();
                cond.put("expr", expr != null ? expr.toString() : null);
                orderBy.add(cond);
            }
        }
        meta.put("orderBy", orderBy);

        // GROUP BY
        List<String> groupBy = new ArrayList<>();
        VarExprList groupVars = query.getGroupBy();
        if (groupVars != null) {
            for (Var v : groupVars.getVars()) {
                groupBy.add(v.getVarName());
            }
        }
        meta.put("groupBy", groupBy);

        // HAVING
        List<String> having = new ArrayList<>();
        if (query.getHavingExprs() != null) {
            for (Expr expr : query.getHavingExprs()) {
                having.add(expr.toString());
            }
        }
        meta.put("having", having);

        // Dataset clauses
        List<String> defaultGraphs = new ArrayList<>();
        if (query.getGraphURIs() != null) {
            defaultGraphs.addAll(query.getGraphURIs());
        }
        meta.put("datasetDefaultGraphs", defaultGraphs);

        List<String> namedGraphs = new ArrayList<>();
        if (query.getNamedGraphURIs() != null) {
            namedGraphs.addAll(query.getNamedGraphURIs());
        }
        meta.put("datasetNamedGraphs", namedGraphs);

        // CONSTRUCT template
        if (query.isConstructType()) {
            List<Map<String, Object>> template = new ArrayList<>();
            if (query.getConstructTemplate() != null) {
                query.getConstructTemplate().getTriples().forEach(t -> {
                    Map<String, Object> triple = new LinkedHashMap<>();
                    triple.put("subject", ai.vital.sparqlcompiler.serializer.NodeSerializer.serialize(t.getSubject()));
                    triple.put("predicate", ai.vital.sparqlcompiler.serializer.NodeSerializer.serialize(t.getPredicate()));
                    triple.put("object", ai.vital.sparqlcompiler.serializer.NodeSerializer.serialize(t.getObject()));
                    template.add(triple);
                });
            }
            meta.put("constructTemplate", template);
        }

        // DESCRIBE URIs
        if (query.isDescribeType()) {
            List<Map<String, Object>> describeNodes = new ArrayList<>();
            if (query.getResultURIs() != null) {
                query.getResultURIs().forEach(n ->
                        describeNodes.add(ai.vital.sparqlcompiler.serializer.NodeSerializer.serialize(n)));
            }
            if (query.getResultVars() != null) {
                query.getResultVars().forEach(v -> {
                    Map<String, Object> varNode = new LinkedHashMap<>();
                    varNode.put("type", "var");
                    varNode.put("name", v);
                    describeNodes.add(varNode);
                });
            }
            meta.put("describeNodes", describeNodes);
        }

        return meta;
    }

    private static String queryTypeString(Query query) {
        if (query.isSelectType()) return "SELECT";
        if (query.isConstructType()) return "CONSTRUCT";
        if (query.isAskType()) return "ASK";
        if (query.isDescribeType()) return "DESCRIBE";
        return "UNKNOWN";
    }
}
