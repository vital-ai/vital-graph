#!/usr/bin/env python3
"""Inspect KG type-level edge annotations from the OWL ontology via VitalSigns."""

from vital_ai_vitalsigns.vitalsigns import VitalSigns

vs = VitalSigns()
ont_manager = vs.get_ontology_manager()
domain_graph = ont_manager.get_domain_graph()

KG_NS = "http://vital.ai/ontology/haley-ai-kg#"

edges = [
    'Edge_hasEntityTypePartOfKGFrameType',
    'Edge_hasSubKGEntityType',
    'Edge_hasSubKGFrameType',
    'Edge_hasSubKGType',
    'Edge_hasSameAsKGType',
    'Edge_hasOutgoingKGRelationType',
    'Edge_hasIncomingKGRelationType',
    'Edge_hasPartOfKGFrameType',
]


def get_edge_info(domain_graph, edge_class_uri):
    """Get source domains, destination domains, and rdfs:comment for an edge class."""
    query = f"""
    PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

    SELECT ?annotation ?value
    WHERE {{
        {{
            <{edge_class_uri}> vital-core:hasEdgeSrcDomain ?value .
            BIND("src" AS ?annotation)
        }}
        UNION
        {{
            <{edge_class_uri}> vital-core:hasEdgeDestDomain ?value .
            BIND("dest" AS ?annotation)
        }}
        UNION
        {{
            <{edge_class_uri}> rdfs:comment ?value .
            BIND("comment" AS ?annotation)
        }}
    }}
    """
    results = domain_graph.query(query)

    src = []
    dest = []
    comment = None
    for row in results:
        ann = str(row['annotation'])
        val = str(row['value'])
        if ann == "src":
            src.append(val.split('#')[-1] if '#' in val else val)
        elif ann == "dest":
            dest.append(val.split('#')[-1] if '#' in val else val)
        elif ann == "comment":
            comment = val
    return src, dest, comment


for edge_name in edges:
    edge_uri = f"{KG_NS}{edge_name}"
    src, dest, comment = get_edge_info(domain_graph, edge_uri)
    print(f"{edge_name}:")
    print(f"  Source:      {', '.join(src) if src else '(not annotated)'}")
    print(f"  Destination: {', '.join(dest) if dest else '(not annotated)'}")
    if comment:
        print(f"  Comment:     {comment}")
    print()
