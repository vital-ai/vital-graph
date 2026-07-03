"""SPARQL query corpus for fixture generation.

Each entry is (name, sparql_string). The name becomes the fixture filename.
Add new queries here to expand test coverage.
"""

QUERIES = [
    # --- Basic patterns ---
    ("simple_select", """
        SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10
    """),

    ("select_with_filter_contains", """
        SELECT ?s ?name WHERE {
            ?s <http://example.org/hasName> ?name .
            FILTER(CONTAINS(?name, "hello"))
        }
    """),

    ("select_with_filter_regex", """
        SELECT ?s ?name WHERE {
            ?s <http://example.org/hasName> ?name .
            FILTER(REGEX(?name, "^foo.*bar$", "i"))
        }
    """),

    # --- OPTIONAL / LEFT JOIN ---
    ("optional_pattern", """
        SELECT ?s ?name ?email WHERE {
            ?s <http://example.org/hasName> ?name .
            OPTIONAL { ?s <http://example.org/hasEmail> ?email }
        }
    """),

    # --- UNION ---
    ("union_two_branches", """
        SELECT ?s ?type WHERE {
            {
                ?s a <http://example.org/TypeA> .
                BIND("A" AS ?type)
            } UNION {
                ?s a <http://example.org/TypeB> .
                BIND("B" AS ?type)
            }
        }
    """),

    # --- GROUP BY + aggregates ---
    ("group_by_count", """
        SELECT ?type (COUNT(?s) AS ?count) WHERE {
            ?s a ?type .
        } GROUP BY ?type
    """),

    ("group_by_having", """
        SELECT ?type (COUNT(?s) AS ?count) WHERE {
            ?s a ?type .
        } GROUP BY ?type HAVING (COUNT(?s) > 5)
    """),

    # --- ORDER / LIMIT / OFFSET ---
    ("order_limit_offset", """
        SELECT ?s ?name WHERE {
            ?s <http://example.org/hasName> ?name .
        } ORDER BY ?name LIMIT 20 OFFSET 10
    """),

    # --- DISTINCT ---
    ("distinct_select", """
        SELECT DISTINCT ?type WHERE {
            ?s a ?type .
        }
    """),

    # --- Multi-pattern join (realistic entity query) ---
    ("multi_pattern_entity", """
        SELECT ?entity ?name ?desc WHERE {
            ?entity a <http://vital.ai/ontology/vital#KGEntity> .
            ?entity <http://vital.ai/ontology/vital#hasName> ?name .
            OPTIONAL { ?entity <http://vital.ai/ontology/vital#hasDescription> ?desc }
        }
    """),

    # --- BIND / EXTEND ---
    ("bind_expression", """
        SELECT ?s ?name ?upper WHERE {
            ?s <http://example.org/hasName> ?name .
            BIND(UCASE(?name) AS ?upper)
        }
    """),

    # --- MINUS ---
    ("minus_pattern", """
        SELECT ?s WHERE {
            ?s a <http://example.org/TypeA> .
            MINUS { ?s <http://example.org/deleted> "true" }
        }
    """),

    # --- Subquery ---
    ("subquery", """
        SELECT ?s ?name WHERE {
            {
                SELECT ?s WHERE {
                    ?s a <http://example.org/TypeA> .
                } LIMIT 100
            }
            ?s <http://example.org/hasName> ?name .
        }
    """),

    # --- VALUES / inline data ---
    ("values_inline", """
        SELECT ?s ?name WHERE {
            VALUES ?type { <http://example.org/TypeA> <http://example.org/TypeB> }
            ?s a ?type .
            ?s <http://example.org/hasName> ?name .
        }
    """),

    # --- Multiple filters (pushdown test) ---
    ("multiple_text_filters", """
        SELECT ?s ?name ?desc WHERE {
            ?s <http://example.org/hasName> ?name .
            ?s <http://example.org/hasDescription> ?desc .
            FILTER(CONTAINS(?name, "foo"))
            FILTER(STRSTARTS(?desc, "bar"))
        }
    """),

    # --- Complex: entity list with type union (realistic KG query) ---
    ("entity_list_type_union", """
        SELECT ?entity ?name ?type WHERE {
            {
                ?entity a <http://vital.ai/ontology/vital#KGEntity> .
                BIND(<http://vital.ai/ontology/vital#KGEntity> AS ?type)
            } UNION {
                ?entity a <http://vital.ai/ontology/vital#KGNewsEntity> .
                BIND(<http://vital.ai/ontology/vital#KGNewsEntity> AS ?type)
            } UNION {
                ?entity a <http://vital.ai/ontology/vital#KGProductEntity> .
                BIND(<http://vital.ai/ontology/vital#KGProductEntity> AS ?type)
            }
            ?entity <http://vital.ai/ontology/vital#hasName> ?name .
        } ORDER BY ?name LIMIT 50
    """),

    # --- XSD cast ---
    ("xsd_cast_integer", """
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT ?s (xsd:integer(?val) AS ?intval) WHERE {
            ?s <http://example.org/hasValue> ?val .
        }
    """),

    # --- Property paths ---
    ("property_path_sequence", """
        SELECT ?s ?grandchild WHERE {
            ?s <http://example.org/hasChild>/<http://example.org/hasChild> ?grandchild .
        }
    """),

    ("property_path_alternative", """
        SELECT ?s ?name WHERE {
            ?s (<http://example.org/hasName>|<http://example.org/hasLabel>) ?name .
        }
    """),

    ("property_path_star", """
        SELECT ?s ?ancestor WHERE {
            ?s <http://example.org/subClassOf>* ?ancestor .
        }
    """),

    ("property_path_plus", """
        SELECT ?s ?descendant WHERE {
            ?s <http://example.org/hasChild>+ ?descendant .
        }
    """),

    ("property_path_inverse", """
        SELECT ?child ?parent WHERE {
            ?child ^<http://example.org/hasChild> ?parent .
        }
    """),

    # --- CONSTRUCT ---
    ("construct_basic", """
        CONSTRUCT {
            ?s <http://example.org/label> ?name .
        } WHERE {
            ?s <http://example.org/hasName> ?name .
        } LIMIT 10
    """),

    ("construct_with_optional", """
        CONSTRUCT {
            ?s a <http://example.org/Person> .
            ?s <http://example.org/name> ?name .
            ?s <http://example.org/email> ?email .
        } WHERE {
            ?s a <http://example.org/Person> .
            ?s <http://example.org/hasName> ?name .
            OPTIONAL { ?s <http://example.org/hasEmail> ?email }
        }
    """),

    # --- ASK ---
    ("ask_basic", """
        ASK WHERE {
            <http://example.org/entity1> a <http://example.org/TypeA> .
        }
    """),

    ("ask_with_filter", """
        ASK WHERE {
            ?s <http://example.org/hasAge> ?age .
            FILTER(?age > 18)
        }
    """),

    # --- DESCRIBE ---
    ("describe_uri", """
        DESCRIBE <http://example.org/entity1>
    """),

    ("describe_variable", """
        DESCRIBE ?s WHERE {
            ?s a <http://example.org/TypeA> .
        } LIMIT 5
    """),

    # --- Aggregates: GROUP_CONCAT, SUM, AVG ---
    ("aggregate_group_concat", """
        SELECT ?type (GROUP_CONCAT(?name; separator=", ") AS ?names) WHERE {
            ?s a ?type .
            ?s <http://example.org/hasName> ?name .
        } GROUP BY ?type
    """),

    ("aggregate_sum_avg", """
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT ?type (SUM(xsd:integer(?val)) AS ?total) (AVG(xsd:integer(?val)) AS ?average) WHERE {
            ?s a ?type .
            ?s <http://example.org/hasValue> ?val .
        } GROUP BY ?type
    """),

    # --- NOT EXISTS / EXISTS ---
    ("filter_not_exists", """
        SELECT ?s ?name WHERE {
            ?s <http://example.org/hasName> ?name .
            FILTER NOT EXISTS { ?s <http://example.org/deleted> "true" }
        }
    """),

    ("filter_exists", """
        SELECT ?s ?name WHERE {
            ?s <http://example.org/hasName> ?name .
            FILTER EXISTS { ?s a <http://example.org/TypeA> }
        }
    """),

    # --- Nested OPTIONAL ---
    ("nested_optional", """
        SELECT ?s ?name ?email ?phone WHERE {
            ?s <http://example.org/hasName> ?name .
            OPTIONAL {
                ?s <http://example.org/hasEmail> ?email .
                OPTIONAL { ?s <http://example.org/hasPhone> ?phone }
            }
        }
    """),

    # --- SPARQL expressions in SELECT ---
    ("computed_select_expressions", """
        SELECT ?s ?name (STRLEN(?name) AS ?nameLen) (UCASE(?name) AS ?upper) WHERE {
            ?s <http://example.org/hasName> ?name .
        }
    """),
]
