package ai.vital.sparqlcompiler.serializer;

import org.apache.jena.datatypes.RDFDatatype;
import org.apache.jena.graph.Node;
import org.apache.jena.sparql.core.Var;

import java.util.LinkedHashMap;
import java.util.Map;

public class NodeSerializer {

    public static Map<String, Object> serialize(Node node) {
        if (node == null) {
            return null;
        }

        Map<String, Object> result = new LinkedHashMap<>();

        if (node.isVariable() || Var.isVar(node)) {
            result.put("type", "var");
            result.put("name", Var.isVar(node) ? Var.alloc(node).getVarName() : node.getName());
        } else if (node.isURI()) {
            result.put("type", "uri");
            result.put("value", node.getURI());
        } else if (node.isLiteral()) {
            result.put("type", "literal");
            result.put("value", node.getLiteralLexicalForm());
            String lang = node.getLiteralLanguage();
            if (lang != null && !lang.isEmpty()) {
                result.put("lang", lang);
            }
            RDFDatatype dt = node.getLiteralDatatype();
            if (dt != null) {
                String dtUri = dt.getURI();
                // Omit xsd:string as it's the default
                if (!"http://www.w3.org/2001/XMLSchema#string".equals(dtUri)) {
                    result.put("datatype", dtUri);
                }
            }
        } else if (node.isBlank()) {
            result.put("type", "bnode");
            result.put("label", node.getBlankNodeLabel());
        } else {
            result.put("type", "unknown");
            result.put("value", node.toString());
        }

        return result;
    }
}
