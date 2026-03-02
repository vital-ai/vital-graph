package ai.vital.sparqlcompiler.serializer;

import org.apache.jena.graph.Node;
import org.apache.jena.sparql.core.Quad;
import org.apache.jena.sparql.modify.request.*;
import org.apache.jena.sparql.syntax.Element;
import org.apache.jena.update.Update;
import org.apache.jena.update.UpdateRequest;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class UpdateSerializer {

    public static List<Map<String, Object>> serialize(UpdateRequest updateRequest, boolean includePretty) {
        List<Map<String, Object>> operations = new ArrayList<>();

        for (Update update : updateRequest.getOperations()) {
            operations.add(serializeUpdate(update, includePretty));
        }

        return operations;
    }

    private static Map<String, Object> serializeUpdate(Update update, boolean includePretty) {
        Map<String, Object> result = new LinkedHashMap<>();

        if (update instanceof UpdateDataInsert ins) {
            result.put("type", "UpdateDataInsert");
            result.put("quads", serializeQuads(ins.getQuads()));

        } else if (update instanceof UpdateDataDelete del) {
            result.put("type", "UpdateDataDelete");
            result.put("quads", serializeQuads(del.getQuads()));

        } else if (update instanceof UpdateModify modify) {
            result.put("type", "UpdateModify");

            Node withGraph = modify.getWithIRI();
            result.put("withGraph", withGraph != null ? NodeSerializer.serialize(withGraph) : null);

            result.put("deleteQuads", serializeQuads(modify.getDeleteQuads()));
            result.put("insertQuads", serializeQuads(modify.getInsertQuads()));

            List<String> usingGraphs = new ArrayList<>();
            for (Node n : modify.getUsing()) {
                usingGraphs.add(n.getURI());
            }
            result.put("usingGraphs", usingGraphs);

            List<String> usingNamedGraphs = new ArrayList<>();
            for (Node n : modify.getUsingNamed()) {
                usingNamedGraphs.add(n.getURI());
            }
            result.put("usingNamedGraphs", usingNamedGraphs);

            Element wherePattern = modify.getWherePattern();
            result.put("wherePattern", wherePattern != null ? ElementSerializer.serialize(wherePattern) : null);

        } else if (update instanceof UpdateLoad load) {
            result.put("type", "UpdateLoad");
            result.put("source", load.getSource());
            result.put("destGraph", load.getDest() != null ? load.getDest().getURI() : null);
            result.put("silent", load.isSilent());

        } else if (update instanceof UpdateClear clear) {
            result.put("type", "UpdateClear");
            result.put("target", serializeTarget(clear.getTarget()));
            result.put("silent", clear.isSilent());

        } else if (update instanceof UpdateDrop drop) {
            result.put("type", "UpdateDrop");
            result.put("target", serializeTarget(drop.getTarget()));
            result.put("silent", drop.isSilent());

        } else if (update instanceof UpdateCreate create) {
            result.put("type", "UpdateCreate");
            result.put("graph", create.getGraph() != null ? create.getGraph().getURI() : null);
            result.put("silent", create.isSilent());

        } else if (update instanceof UpdateCopy copy) {
            result.put("type", "UpdateCopy");
            result.put("source", serializeTarget(copy.getSrc()));
            result.put("dest", serializeTarget(copy.getDest()));
            result.put("silent", copy.isSilent());

        } else if (update instanceof UpdateMove move) {
            result.put("type", "UpdateMove");
            result.put("source", serializeTarget(move.getSrc()));
            result.put("dest", serializeTarget(move.getDest()));
            result.put("silent", move.isSilent());

        } else if (update instanceof UpdateAdd add) {
            result.put("type", "UpdateAdd");
            result.put("source", serializeTarget(add.getSrc()));
            result.put("dest", serializeTarget(add.getDest()));
            result.put("silent", add.isSilent());

        } else {
            result.put("type", update.getClass().getSimpleName());
            result.put("string", update.toString());
        }

        if (includePretty) {
            result.put("pretty", update.toString());
        }

        return result;
    }

    private static List<Map<String, Object>> serializeQuads(List<Quad> quads) {
        List<Map<String, Object>> result = new ArrayList<>();
        for (Quad q : quads) {
            Map<String, Object> quad = new LinkedHashMap<>();
            Node graph = q.getGraph();
            if (graph != null && !Quad.isDefaultGraph(graph)) {
                quad.put("graph", NodeSerializer.serialize(graph));
            } else {
                quad.put("graph", null);
            }
            quad.put("subject", NodeSerializer.serialize(q.getSubject()));
            quad.put("predicate", NodeSerializer.serialize(q.getPredicate()));
            quad.put("object", NodeSerializer.serialize(q.getObject()));
            result.add(quad);
        }
        return result;
    }

    private static Map<String, Object> serializeTarget(Target target) {
        Map<String, Object> result = new LinkedHashMap<>();
        if (target.isDefault()) {
            result.put("scope", "DEFAULT");
        } else if (target.isAll()) {
            result.put("scope", "ALL");
        } else if (target.isAllNamed()) {
            result.put("scope", "NAMED");
        } else if (target.isOneNamedGraph()) {
            result.put("scope", "GRAPH");
            result.put("graph", target.getGraph().getURI());
        }
        return result;
    }
}
