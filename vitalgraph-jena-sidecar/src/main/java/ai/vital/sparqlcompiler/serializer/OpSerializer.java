package ai.vital.sparqlcompiler.serializer;

import org.apache.jena.graph.Triple;
import org.apache.jena.sparql.algebra.Op;
import org.apache.jena.sparql.algebra.op.*;
import org.apache.jena.sparql.core.BasicPattern;
import org.apache.jena.sparql.core.Quad;
import org.apache.jena.sparql.core.Var;
import org.apache.jena.sparql.core.VarExprList;
import org.apache.jena.sparql.expr.Expr;
import org.apache.jena.sparql.expr.ExprAggregator;
import org.apache.jena.sparql.expr.ExprList;

import java.io.ByteArrayOutputStream;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class OpSerializer {

    public static Map<String, Object> serialize(Op op) {
        if (op == null) {
            return null;
        }

        Map<String, Object> result = new LinkedHashMap<>();

        if (op instanceof OpBGP bgp) {
            result.put("type", "OpBGP");
            List<Map<String, Object>> triples = new ArrayList<>();
            for (Triple t : bgp.getPattern().getList()) {
                triples.add(serializeTriple(t));
            }
            result.put("triples", triples);

        } else if (op instanceof OpJoin join) {
            result.put("type", "OpJoin");
            result.put("left", serialize(join.getLeft()));
            result.put("right", serialize(join.getRight()));

        } else if (op instanceof OpLeftJoin leftJoin) {
            result.put("type", "OpLeftJoin");
            result.put("left", serialize(leftJoin.getLeft()));
            result.put("right", serialize(leftJoin.getRight()));
            ExprList exprs = leftJoin.getExprs();
            result.put("exprs", ExprSerializer.serializeList(exprs));

        } else if (op instanceof OpUnion union) {
            result.put("type", "OpUnion");
            result.put("left", serialize(union.getLeft()));
            result.put("right", serialize(union.getRight()));

        } else if (op instanceof OpFilter filter) {
            result.put("type", "OpFilter");
            result.put("exprs", ExprSerializer.serializeList(filter.getExprs()));
            result.put("subOp", serialize(filter.getSubOp()));

        } else if (op instanceof OpProject project) {
            result.put("type", "OpProject");
            List<String> vars = new ArrayList<>();
            for (Var v : project.getVars()) {
                vars.add(v.getVarName());
            }
            result.put("vars", vars);
            result.put("subOp", serialize(project.getSubOp()));

        } else if (op instanceof OpSlice slice) {
            result.put("type", "OpSlice");
            result.put("start", slice.getStart());
            result.put("length", slice.getLength());
            result.put("subOp", serialize(slice.getSubOp()));

        } else if (op instanceof OpDistinct distinct) {
            result.put("type", "OpDistinct");
            result.put("subOp", serialize(distinct.getSubOp()));

        } else if (op instanceof OpReduced reduced) {
            result.put("type", "OpReduced");
            result.put("subOp", serialize(reduced.getSubOp()));

        } else if (op instanceof OpOrder order) {
            result.put("type", "OpOrder");
            List<Map<String, Object>> conditions = new ArrayList<>();
            for (var sc : order.getConditions()) {
                Map<String, Object> cond = new LinkedHashMap<>();
                cond.put("direction", sc.getDirection() == -1 ? "DESC" : "ASC");
                cond.put("expr", ExprSerializer.serialize(sc.getExpression()));
                conditions.add(cond);
            }
            result.put("conditions", conditions);
            result.put("subOp", serialize(order.getSubOp()));

        } else if (op instanceof OpGroup group) {
            result.put("type", "OpGroup");
            List<String> groupVars = new ArrayList<>();
            for (var ve : group.getGroupVars().getVars()) {
                groupVars.add(ve.getVarName());
            }
            result.put("groupVars", groupVars);

            List<Map<String, Object>> aggregators = new ArrayList<>();
            if (group.getAggregators() != null) {
                for (ExprAggregator ea : group.getAggregators()) {
                    Map<String, Object> agg = new LinkedHashMap<>();
                    agg.put("var", ea.getVar().getVarName());
                    agg.put("aggregator", ExprSerializer.serialize(ea));
                    aggregators.add(agg);
                }
            }
            result.put("aggregators", aggregators);
            result.put("subOp", serialize(group.getSubOp()));

        } else if (op instanceof OpExtend extend) {
            result.put("type", "OpExtend");
            VarExprList vel = extend.getVarExprList();
            List<Map<String, Object>> extensions = new ArrayList<>();
            for (Var v : vel.getVars()) {
                Map<String, Object> ext = new LinkedHashMap<>();
                ext.put("var", v.getVarName());
                ext.put("expr", ExprSerializer.serialize(vel.getExpr(v)));
                extensions.add(ext);
            }
            result.put("extensions", extensions);
            result.put("subOp", serialize(extend.getSubOp()));

        } else if (op instanceof OpTable table) {
            result.put("type", "OpTable");
            List<String> vars = new ArrayList<>();
            for (Var v : table.getTable().getVars()) {
                vars.add(v.getVarName());
            }
            result.put("vars", vars);
            List<Map<String, Object>> rows = new ArrayList<>();
            table.getTable().rows().forEachRemaining(binding -> {
                Map<String, Object> row = new LinkedHashMap<>();
                for (Var v : table.getTable().getVars()) {
                    row.put(v.getVarName(),
                            binding.get(v) != null ? NodeSerializer.serialize(binding.get(v)) : null);
                }
                rows.add(row);
            });
            result.put("rows", rows);

        } else if (op instanceof OpMinus minus) {
            result.put("type", "OpMinus");
            result.put("left", serialize(minus.getLeft()));
            result.put("right", serialize(minus.getRight()));

        } else if (op instanceof OpGraph graph) {
            result.put("type", "OpGraph");
            result.put("graphNode", NodeSerializer.serialize(graph.getNode()));
            result.put("subOp", serialize(graph.getSubOp()));

        } else if (op instanceof OpConditional cond) {
            result.put("type", "OpConditional");
            result.put("left", serialize(cond.getLeft()));
            result.put("right", serialize(cond.getRight()));

        } else if (op instanceof OpSequence seq) {
            result.put("type", "OpSequence");
            List<Map<String, Object>> elements = new ArrayList<>();
            for (Op element : seq.getElements()) {
                elements.add(serialize(element));
            }
            result.put("elements", elements);

        } else if (op instanceof OpLabel label) {
            result.put("type", "OpLabel");
            result.put("label", label.getObject() != null ? label.getObject().toString() : null);
            result.put("subOp", serialize(label.getSubOp()));

        } else if (op instanceof OpQuadPattern quadPattern) {
            result.put("type", "OpQuadPattern");
            result.put("graphNode", NodeSerializer.serialize(quadPattern.getGraphNode()));
            List<Map<String, Object>> quads = new ArrayList<>();
            for (Quad q : quadPattern.getPattern().getList()) {
                Map<String, Object> quad = new LinkedHashMap<>();
                quad.put("graph", NodeSerializer.serialize(q.getGraph()));
                quad.put("subject", NodeSerializer.serialize(q.getSubject()));
                quad.put("predicate", NodeSerializer.serialize(q.getPredicate()));
                quad.put("object", NodeSerializer.serialize(q.getObject()));
                quads.add(quad);
            }
            result.put("quads", quads);

        } else if (op instanceof OpTriple opTriple) {
            result.put("type", "OpTriple");
            result.put("triple", serializeTriple(opTriple.getTriple()));

        } else if (op instanceof OpPath opPath) {
            result.put("type", "OpPath");
            Map<String, Object> path = new LinkedHashMap<>();
            path.put("subject", NodeSerializer.serialize(opPath.getTriplePath().getSubject()));
            Map<String, Object> pathPred = new LinkedHashMap<>();
            pathPred.put("type", "path");
            pathPred.put("value", opPath.getTriplePath().getPath().toString());
            path.put("predicate", pathPred);
            path.put("object", NodeSerializer.serialize(opPath.getTriplePath().getObject()));
            result.put("triplePath", path);

        } else {
            result.put("type", op.getClass().getSimpleName());
            result.put("string", op.toString());
        }

        return result;
    }

    public static String prettyPrint(Op op) {
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        org.apache.jena.sparql.sse.SSE.write(baos, op);
        return baos.toString(StandardCharsets.UTF_8).trim();
    }

    private static Map<String, Object> serializeTriple(Triple t) {
        Map<String, Object> triple = new LinkedHashMap<>();
        triple.put("subject", NodeSerializer.serialize(t.getSubject()));
        triple.put("predicate", NodeSerializer.serialize(t.getPredicate()));
        triple.put("object", NodeSerializer.serialize(t.getObject()));
        return triple;
    }
}
