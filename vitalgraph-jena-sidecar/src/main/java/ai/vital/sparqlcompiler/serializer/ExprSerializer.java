package ai.vital.sparqlcompiler.serializer;

import org.apache.jena.sparql.expr.*;
import org.apache.jena.sparql.expr.aggregate.Aggregator;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class ExprSerializer {

    public static Map<String, Object> serialize(Expr expr) {
        if (expr == null) {
            return null;
        }

        Map<String, Object> result = new LinkedHashMap<>();

        if (expr instanceof ExprVar exprVar) {
            result.put("type", "ExprVar");
            result.put("var", exprVar.getVarName());

        } else if (expr instanceof NodeValue nodeValue) {
            result.put("type", "NodeValue");
            result.put("node", NodeSerializer.serialize(nodeValue.asNode()));

        } else if (expr instanceof ExprAggregator exprAgg) {
            result.put("type", "ExprAggregator");
            Aggregator agg = exprAgg.getAggregator();
            result.put("name", agg.getName());
            result.put("distinct", agg.toString().contains("DISTINCT"));
            ExprList aggExprs = agg.getExprList();
            if (aggExprs != null && !aggExprs.isEmpty()) {
                result.put("expr", serialize(aggExprs.get(0)));
            } else {
                result.put("expr", null);
            }

        } else if (expr instanceof ExprFunction1 f1) {
            result.put("type", "ExprFunction1");
            result.put("name", f1.getFunctionSymbol().getSymbol());
            result.put("arg", serialize(f1.getArg()));

        } else if (expr instanceof ExprFunction2 f2) {
            result.put("type", "ExprFunction2");
            result.put("name", f2.getFunctionSymbol().getSymbol());
            List<Map<String, Object>> args = new ArrayList<>();
            args.add(serialize(f2.getArg1()));
            args.add(serialize(f2.getArg2()));
            result.put("args", args);

        } else if (expr instanceof ExprFunction3 f3) {
            result.put("type", "ExprFunction3");
            result.put("name", f3.getFunctionSymbol().getSymbol());
            List<Map<String, Object>> args = new ArrayList<>();
            args.add(serialize(f3.getArg1()));
            args.add(serialize(f3.getArg2()));
            args.add(serialize(f3.getArg3()));
            result.put("args", args);

        } else if (expr instanceof ExprFunctionN fn) {
            result.put("type", "ExprFunctionN");
            result.put("name", fn.getFunctionSymbol().getSymbol());
            List<Map<String, Object>> args = new ArrayList<>();
            for (Expr arg : fn.getArgs()) {
                args.add(serialize(arg));
            }
            result.put("args", args);

        } else if (expr instanceof ExprFunctionOp exprFnOp) {
            result.put("type", "ExprFunctionOp");
            result.put("name", exprFnOp.getFunctionSymbol().getSymbol());
            result.put("graphPattern", OpSerializer.serialize(exprFnOp.getGraphPattern()));

        } else {
            result.put("type", expr.getClass().getSimpleName());
            result.put("string", expr.toString());
        }

        return result;
    }

    public static List<Map<String, Object>> serializeList(ExprList exprList) {
        if (exprList == null || exprList.isEmpty()) {
            return List.of();
        }
        List<Map<String, Object>> result = new ArrayList<>();
        for (Expr expr : exprList) {
            result.add(serialize(expr));
        }
        return result;
    }
}
