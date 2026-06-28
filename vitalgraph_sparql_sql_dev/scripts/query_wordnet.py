#!/usr/bin/env python3
"""
query_wordnet.py — Run SPARQL queries against the WordNet KGFrames data
via the SPARQL-to-SQL pipeline and log the generated SQL for optimization analysis.

Requires:
  - Jena sidecar running at localhost:7070
  - PostgreSQL with WordNet data in wordnet_exp_* tables

Usage:
    python -m vitalgraph_sparql_sql.scripts.query_wordnet
    python vitalgraph_sparql_sql/scripts/query_wordnet.py [--space wordnet_exp] [-v]
"""

import argparse
import asyncio
import logging
import os
import sys
import textwrap
import time

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from vitalgraph_sparql_sql.jena_sparql_orchestrator import SparqlOrchestrator

logger = logging.getLogger("query_wordnet")

# ---------------------------------------------------------------------------
# Ontology constants (for readability in queries)
# ---------------------------------------------------------------------------
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
VITAL_NAME = "http://vital.ai/ontology/vital-core#hasName"
VITAL_TYPE = "http://vital.ai/ontology/vital-core#vitaltype"
VITAL_URI = "http://vital.ai/ontology/vital-core#URIProp"
VITAL_EDGE_SRC = "http://vital.ai/ontology/vital-core#hasEdgeSource"
VITAL_EDGE_DST = "http://vital.ai/ontology/vital-core#hasEdgeDestination"
HALEY_KG_ENTITY = "http://vital.ai/ontology/haley-ai-kg#KGEntity"
HALEY_KG_FRAME = "http://vital.ai/ontology/haley-ai-kg#KGFrame"
HALEY_KG_ENTITY_SLOT = "http://vital.ai/ontology/haley-ai-kg#KGEntitySlot"
HALEY_EDGE_HAS_SLOT = "http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot"
HALEY_FRAME_TYPE = "http://vital.ai/ontology/haley-ai-kg#hasKGFrameType"
HALEY_FRAME_TYPE_DESC = "http://vital.ai/ontology/haley-ai-kg#hasKGFrameTypeDescription"
HALEY_ENTITY_TYPE = "http://vital.ai/ontology/haley-ai-kg#hasKGEntityType"
HALEY_ENTITY_TYPE_DESC = "http://vital.ai/ontology/haley-ai-kg#hasKGEntityTypeDescription"
HALEY_SLOT_TYPE = "http://vital.ai/ontology/haley-ai-kg#hasKGSlotType"
HALEY_SLOT_VALUE = "http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue"
HALEY_KG_DESC = "http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription"
HALEY_KG_ID = "http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier"
WORDNET_GRAPH = "http://vital.ai/graph/kgwordnetframes"

# ---------------------------------------------------------------------------
# Query definitions
# ---------------------------------------------------------------------------

QUERIES = [
    # ======================================================================
    # 1. Schema exploration — understand what's in the data
    # ======================================================================
    {
        "label": "1a. Distinct predicates (all properties used)",
        "sparql": f"""
            SELECT DISTINCT ?p WHERE {{
                ?s ?p ?o
            }} ORDER BY ?p
        """,
        "description": "Lists every unique predicate URI in the dataset",
    },
    {
        "label": "1b. Distinct rdf:type values (all classes used)",
        "sparql": f"""
            SELECT ?type (COUNT(?s) AS ?count) WHERE {{
                ?s <{RDF_TYPE}> ?type
            }} GROUP BY ?type ORDER BY DESC(?count)
        """,
        "description": "Count of instances per rdf:type class",
    },
    {
        "label": "1c. Distinct frame types",
        "sparql": f"""
            SELECT ?frameType (COUNT(?frame) AS ?count) WHERE {{
                ?frame <{HALEY_FRAME_TYPE}> ?frameType
            }} GROUP BY ?frameType ORDER BY DESC(?count) LIMIT 20
        """,
        "description": "Distribution of KGFrame types (edge relationship types)",
    },
    {
        "label": "1d. Distinct entity types",
        "sparql": f"""
            SELECT ?entityType (COUNT(?e) AS ?count) WHERE {{
                ?e <{HALEY_ENTITY_TYPE}> ?entityType
            }} GROUP BY ?entityType ORDER BY DESC(?count) LIMIT 20
        """,
        "description": "Distribution of KGEntity types (node types)",
    },
    {
        "label": "1e. Distinct slot types",
        "sparql": f"""
            SELECT ?slotType (COUNT(?slot) AS ?count) WHERE {{
                ?slot <{HALEY_SLOT_TYPE}> ?slotType
            }} GROUP BY ?slotType ORDER BY DESC(?count) LIMIT 20
        """,
        "description": "Distribution of slot types (hasSourceEntity, hasDestinationEntity)",
    },

    # ======================================================================
    # 2. Basic entity queries
    # ======================================================================
    {
        "label": "2a. Sample KGEntities with names",
        "sparql": f"""
            SELECT ?entity ?name WHERE {{
                ?entity <{RDF_TYPE}> <{HALEY_KG_ENTITY}> .
                ?entity <{VITAL_NAME}> ?name
            }} LIMIT 10
        """,
        "description": "First 10 named KGEntities",
    },
    {
        "label": "2b. KGEntities with type + name + description",
        "sparql": f"""
            SELECT ?entity ?name ?entityType ?desc WHERE {{
                ?entity <{RDF_TYPE}> <{HALEY_KG_ENTITY}> .
                ?entity <{VITAL_NAME}> ?name .
                ?entity <{HALEY_ENTITY_TYPE}> ?entityType .
                OPTIONAL {{ ?entity <{HALEY_KG_DESC}> ?desc }}
            }} LIMIT 10
        """,
        "description": "Entity details: name, type, and optional description",
    },
    {
        "label": "2c. Count entities by entity type",
        "sparql": f"""
            SELECT ?entityType ?entityTypeDesc (COUNT(?entity) AS ?count) WHERE {{
                ?entity <{RDF_TYPE}> <{HALEY_KG_ENTITY}> .
                ?entity <{HALEY_ENTITY_TYPE}> ?entityType .
                ?entity <{HALEY_ENTITY_TYPE_DESC}> ?entityTypeDesc
            }} GROUP BY ?entityType ?entityTypeDesc ORDER BY DESC(?count)
        """,
        "description": "How many entities per entity type (NounSynset, VerbSynset, etc)",
    },

    # ======================================================================
    # 3. Frame / edge traversal — the core graph structure
    # ======================================================================
    {
        "label": "3a. Sample frames with their type",
        "sparql": f"""
            SELECT ?frame ?frameType ?frameTypeDesc WHERE {{
                ?frame <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
                ?frame <{HALEY_FRAME_TYPE}> ?frameType .
                ?frame <{HALEY_FRAME_TYPE_DESC}> ?frameTypeDesc
            }} LIMIT 10
        """,
        "description": "First 10 KGFrames with their relationship type",
    },
    {
        "label": "3b. Frame → Slot → Entity (source side)",
        "sparql": f"""
            SELECT ?frame ?frameTypeDesc ?slot ?slotEntity WHERE {{
                ?frame <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
                ?frame <{HALEY_FRAME_TYPE_DESC}> ?frameTypeDesc .
                ?slot <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?slot <{HALEY_SLOT_VALUE}> ?slotEntity .
                ?edge <{VITAL_EDGE_SRC}> ?frame .
                ?edge <{VITAL_EDGE_DST}> ?slot
            }} LIMIT 10
        """,
        "description": "Traverse: Frame → Edge_hasKGSlot → source slot → entity URI",
    },
    {
        "label": "3c. Full edge traversal: Source Entity → Frame → Destination Entity",
        "sparql": f"""
            SELECT ?srcEntity ?frameTypeDesc ?dstEntity WHERE {{
                ?frame <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
                ?frame <{HALEY_FRAME_TYPE_DESC}> ?frameTypeDesc .

                ?srcSlot <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot <{HALEY_SLOT_VALUE}> ?srcEntity .
                ?srcEdge <{VITAL_EDGE_SRC}> ?frame .
                ?srcEdge <{VITAL_EDGE_DST}> ?srcSlot .

                ?dstSlot <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                ?dstSlot <{HALEY_SLOT_VALUE}> ?dstEntity .
                ?dstEdge <{VITAL_EDGE_SRC}> ?frame .
                ?dstEdge <{VITAL_EDGE_DST}> ?dstSlot
            }} LIMIT 10
        """,
        "description": "Full node→edge→node traversal via KGFrame slots",
    },
    {
        "label": "3d. Full traversal with entity names",
        "sparql": f"""
            SELECT ?srcName ?frameTypeDesc ?dstName WHERE {{
                ?frame <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
                ?frame <{HALEY_FRAME_TYPE_DESC}> ?frameTypeDesc .

                ?srcSlot <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot <{HALEY_SLOT_VALUE}> ?srcEntity .
                ?srcEdge <{VITAL_EDGE_SRC}> ?frame .
                ?srcEdge <{VITAL_EDGE_DST}> ?srcSlot .
                ?srcEntity <{VITAL_NAME}> ?srcName .

                ?dstSlot <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                ?dstSlot <{HALEY_SLOT_VALUE}> ?dstEntity .
                ?dstEdge <{VITAL_EDGE_SRC}> ?frame .
                ?dstEdge <{VITAL_EDGE_DST}> ?dstSlot .
                ?dstEntity <{VITAL_NAME}> ?dstName
            }} LIMIT 10
        """,
        "description": "Full node→edge→node with resolved entity names",
    },

    # ======================================================================
    # 4. Filtered traversals
    # ======================================================================
    {
        "label": "4a. Hyponym relationships only",
        "sparql": f"""
            SELECT ?srcName ?dstName WHERE {{
                ?frame <{HALEY_FRAME_TYPE}> <urn:Edge_WordnetHyponym> .

                ?srcSlot <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot <{HALEY_SLOT_VALUE}> ?srcEntity .
                ?srcEdge <{VITAL_EDGE_SRC}> ?frame .
                ?srcEdge <{VITAL_EDGE_DST}> ?srcSlot .
                ?srcEntity <{VITAL_NAME}> ?srcName .

                ?dstSlot <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                ?dstSlot <{HALEY_SLOT_VALUE}> ?dstEntity .
                ?dstEdge <{VITAL_EDGE_SRC}> ?frame .
                ?dstEdge <{VITAL_EDGE_DST}> ?dstSlot .
                ?dstEntity <{VITAL_NAME}> ?dstName
            }} LIMIT 20
        """,
        "description": "Only WordnetHyponym edges with named entities",
    },
    {
        "label": "4b. Count relationships by frame type",
        "sparql": f"""
            SELECT ?frameTypeDesc (COUNT(?frame) AS ?count) WHERE {{
                ?frame <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
                ?frame <{HALEY_FRAME_TYPE_DESC}> ?frameTypeDesc
            }} GROUP BY ?frameTypeDesc ORDER BY DESC(?count)
        """,
        "description": "Distribution of relationship types in the graph",
    },
    {
        "label": "4c. Entity name search with FILTER",
        "sparql": f"""
            SELECT ?entity ?name ?entityTypeDesc WHERE {{
                ?entity <{RDF_TYPE}> <{HALEY_KG_ENTITY}> .
                ?entity <{VITAL_NAME}> ?name .
                ?entity <{HALEY_ENTITY_TYPE_DESC}> ?entityTypeDesc .
                FILTER(CONTAINS(LCASE(?name), "dog"))
            }} LIMIT 20
        """,
        "description": "Search entities by name substring",
    },

    # ======================================================================
    # 5. Aggregation and analytics
    # ======================================================================
    {
        "label": "5a. Total triple count",
        "sparql": "SELECT (COUNT(*) AS ?total) WHERE { ?s ?p ?o }",
        "description": "Total number of triples",
    },
    {
        "label": "5b. Entity degree (outgoing frame count per entity)",
        "sparql": f"""
            SELECT ?srcEntity ?srcName (COUNT(?frame) AS ?degree) WHERE {{
                ?srcSlot <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot <{HALEY_SLOT_VALUE}> ?srcEntity .
                ?srcEdge <{VITAL_EDGE_SRC}> ?frame .
                ?srcEdge <{VITAL_EDGE_DST}> ?srcSlot .
                ?frame <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
                ?srcEntity <{VITAL_NAME}> ?srcName
            }} GROUP BY ?srcEntity ?srcName ORDER BY DESC(?degree) LIMIT 15
        """,
        "description": "Entities with the most outgoing relationships",
    },
    {
        "label": "5c. Subquery: top 5 most-connected entities and their first relationship",
        "sparql": f"""
            SELECT ?srcName ?degree ?relationType ?dstName WHERE {{
                {{
                    SELECT ?srcEntity (COUNT(?frame) AS ?degree) WHERE {{
                        ?srcSlot <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                        ?srcSlot <{HALEY_SLOT_VALUE}> ?srcEntity .
                        ?srcEdge <{VITAL_EDGE_SRC}> ?frame .
                        ?srcEdge <{VITAL_EDGE_DST}> ?srcSlot .
                        ?frame <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
                    }} GROUP BY ?srcEntity ORDER BY DESC(?degree) LIMIT 5
                }}
                ?srcEntity <{VITAL_NAME}> ?srcName .
                ?frame2 <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
                ?frame2 <{HALEY_FRAME_TYPE_DESC}> ?relationType .
                ?srcSlot2 <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot2 <{HALEY_SLOT_VALUE}> ?srcEntity .
                ?srcEdge2 <{VITAL_EDGE_SRC}> ?frame2 .
                ?srcEdge2 <{VITAL_EDGE_DST}> ?srcSlot2 .
                ?dstSlot <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                ?dstSlot <{HALEY_SLOT_VALUE}> ?dstEntity .
                ?dstEdge <{VITAL_EDGE_SRC}> ?frame2 .
                ?dstEdge <{VITAL_EDGE_DST}> ?dstSlot .
                ?dstEntity <{VITAL_NAME}> ?dstName .
            }} LIMIT 20
        """,
        "description": "Subquery for top entities joined with full frame traversal. "
                       "CTE MATERIALIZED approach: ~12s. Flat join: ~42s. "
                       "Bottleneck is aggregation scan + high fan-out (top entities have 400-670 connections).",
    },

    # ======================================================================
    # 7. Multi-hop pathway — stress test for deep graph traversals
    # ======================================================================
    {
        "label": "7a. Multi-hop pathway: a→b→c→d→e from 'happy'",
        "sparql": f"""
            SELECT ?aName ?rel1 ?bName ?rel2 ?cName ?rel3 ?dName ?rel4 ?eName WHERE {{
                ?a <{RDF_TYPE}> <{HALEY_KG_ENTITY}> .
                ?a <{VITAL_NAME}> ?aName .
                FILTER(CONTAINS(?aName, "happy"))

                ?srcSlot1 <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot1 <{HALEY_SLOT_VALUE}> ?a .
                ?srcEdge1 <{VITAL_EDGE_SRC}> ?frame1 .
                ?srcEdge1 <{VITAL_EDGE_DST}> ?srcSlot1 .
                ?frame1 <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
                ?frame1 <{HALEY_FRAME_TYPE_DESC}> ?rel1 .
                ?dstSlot1 <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                ?dstSlot1 <{HALEY_SLOT_VALUE}> ?b .
                ?dstEdge1 <{VITAL_EDGE_SRC}> ?frame1 .
                ?dstEdge1 <{VITAL_EDGE_DST}> ?dstSlot1 .
                ?b <{VITAL_NAME}> ?bName .

                ?srcSlot2 <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot2 <{HALEY_SLOT_VALUE}> ?b .
                ?srcEdge2 <{VITAL_EDGE_SRC}> ?frame2 .
                ?srcEdge2 <{VITAL_EDGE_DST}> ?srcSlot2 .
                ?frame2 <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
                ?frame2 <{HALEY_FRAME_TYPE_DESC}> ?rel2 .
                ?dstSlot2 <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                ?dstSlot2 <{HALEY_SLOT_VALUE}> ?c .
                ?dstEdge2 <{VITAL_EDGE_SRC}> ?frame2 .
                ?dstEdge2 <{VITAL_EDGE_DST}> ?dstSlot2 .
                ?c <{VITAL_NAME}> ?cName .

                ?srcSlot3 <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot3 <{HALEY_SLOT_VALUE}> ?c .
                ?srcEdge3 <{VITAL_EDGE_SRC}> ?frame3 .
                ?srcEdge3 <{VITAL_EDGE_DST}> ?srcSlot3 .
                ?frame3 <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
                ?frame3 <{HALEY_FRAME_TYPE_DESC}> ?rel3 .
                ?dstSlot3 <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                ?dstSlot3 <{HALEY_SLOT_VALUE}> ?d .
                ?dstEdge3 <{VITAL_EDGE_SRC}> ?frame3 .
                ?dstEdge3 <{VITAL_EDGE_DST}> ?dstSlot3 .
                ?d <{VITAL_NAME}> ?dName .

                ?srcSlot4 <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot4 <{HALEY_SLOT_VALUE}> ?d .
                ?srcEdge4 <{VITAL_EDGE_SRC}> ?frame4 .
                ?srcEdge4 <{VITAL_EDGE_DST}> ?srcSlot4 .
                ?frame4 <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
                ?frame4 <{HALEY_FRAME_TYPE_DESC}> ?rel4 .
                ?dstSlot4 <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                ?dstSlot4 <{HALEY_SLOT_VALUE}> ?e .
                ?dstEdge4 <{VITAL_EDGE_SRC}> ?frame4 .
                ?dstEdge4 <{VITAL_EDGE_DST}> ?dstSlot4 .
                ?e <{VITAL_NAME}> ?eName .
            }}
        """,
        "description": "4-hop pathway from 'happy' entities: a→b→c→d→e via 4 KGFrame traversals. "
                       "~45 triple patterns → 45+ quad JOINs. Stress test for deep graph traversal.",
    },
    {
        "label": "7b. Multi-hop pathway: hop 3 = Hyponym only",
        "sparql": f"""
            SELECT ?aName ?rel1 ?bName ?rel2 ?cName ?rel3 ?dName ?rel4 ?eName WHERE {{
                ?a <{RDF_TYPE}> <{HALEY_KG_ENTITY}> .
                ?a <{VITAL_NAME}> ?aName .
                FILTER(CONTAINS(?aName, "happy"))

                ?srcSlot1 <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot1 <{HALEY_SLOT_VALUE}> ?a .
                ?srcEdge1 <{VITAL_EDGE_SRC}> ?frame1 .
                ?srcEdge1 <{VITAL_EDGE_DST}> ?srcSlot1 .
                ?frame1 <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
                ?frame1 <{HALEY_FRAME_TYPE_DESC}> ?rel1 .
                ?dstSlot1 <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                ?dstSlot1 <{HALEY_SLOT_VALUE}> ?b .
                ?dstEdge1 <{VITAL_EDGE_SRC}> ?frame1 .
                ?dstEdge1 <{VITAL_EDGE_DST}> ?dstSlot1 .
                ?b <{VITAL_NAME}> ?bName .

                ?srcSlot2 <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot2 <{HALEY_SLOT_VALUE}> ?b .
                ?srcEdge2 <{VITAL_EDGE_SRC}> ?frame2 .
                ?srcEdge2 <{VITAL_EDGE_DST}> ?srcSlot2 .
                ?frame2 <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
                ?frame2 <{HALEY_FRAME_TYPE_DESC}> ?rel2 .
                ?dstSlot2 <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                ?dstSlot2 <{HALEY_SLOT_VALUE}> ?c .
                ?dstEdge2 <{VITAL_EDGE_SRC}> ?frame2 .
                ?dstEdge2 <{VITAL_EDGE_DST}> ?dstSlot2 .
                ?c <{VITAL_NAME}> ?cName .

                ?srcSlot3 <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot3 <{HALEY_SLOT_VALUE}> ?c .
                ?srcEdge3 <{VITAL_EDGE_SRC}> ?frame3 .
                ?srcEdge3 <{VITAL_EDGE_DST}> ?srcSlot3 .
                ?frame3 <{HALEY_FRAME_TYPE}> <urn:Edge_WordnetHyponym> .
                ?frame3 <{HALEY_FRAME_TYPE_DESC}> ?rel3 .
                ?dstSlot3 <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                ?dstSlot3 <{HALEY_SLOT_VALUE}> ?d .
                ?dstEdge3 <{VITAL_EDGE_SRC}> ?frame3 .
                ?dstEdge3 <{VITAL_EDGE_DST}> ?dstSlot3 .
                ?d <{VITAL_NAME}> ?dName .

                ?srcSlot4 <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot4 <{HALEY_SLOT_VALUE}> ?d .
                ?srcEdge4 <{VITAL_EDGE_SRC}> ?frame4 .
                ?srcEdge4 <{VITAL_EDGE_DST}> ?srcSlot4 .
                ?frame4 <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
                ?frame4 <{HALEY_FRAME_TYPE_DESC}> ?rel4 .
                ?dstSlot4 <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                ?dstSlot4 <{HALEY_SLOT_VALUE}> ?e .
                ?dstEdge4 <{VITAL_EDGE_SRC}> ?frame4 .
                ?dstEdge4 <{VITAL_EDGE_DST}> ?dstSlot4 .
                ?e <{VITAL_NAME}> ?eName .
            }}
        """,
        "description": "4-hop pathway with hop 3 constrained to Hyponym edges. "
                       "Tests selective edge-type filtering in deep traversals.",
    },
    {
        "label": "7c. Multi-hop: last entity = VerbSynsetNode",
        "sparql": f"""
            SELECT ?aName ?rel1 ?bName ?rel2 ?cName ?rel3 ?dName ?rel4 ?eName WHERE {{
                ?a <{RDF_TYPE}> <{HALEY_KG_ENTITY}> .
                ?a <{VITAL_NAME}> ?aName .
                FILTER(CONTAINS(?aName, "happy"))
                ?e <{HALEY_ENTITY_TYPE}> <urn:VerbSynsetNode> .

                ?srcSlot1 <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot1 <{HALEY_SLOT_VALUE}> ?a .
                ?srcEdge1 <{VITAL_EDGE_SRC}> ?frame1 .
                ?srcEdge1 <{VITAL_EDGE_DST}> ?srcSlot1 .
                ?frame1 <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
                ?frame1 <{HALEY_FRAME_TYPE_DESC}> ?rel1 .
                ?dstSlot1 <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                ?dstSlot1 <{HALEY_SLOT_VALUE}> ?b .
                ?dstEdge1 <{VITAL_EDGE_SRC}> ?frame1 .
                ?dstEdge1 <{VITAL_EDGE_DST}> ?dstSlot1 .
                ?b <{VITAL_NAME}> ?bName .

                ?srcSlot2 <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot2 <{HALEY_SLOT_VALUE}> ?b .
                ?srcEdge2 <{VITAL_EDGE_SRC}> ?frame2 .
                ?srcEdge2 <{VITAL_EDGE_DST}> ?srcSlot2 .
                ?frame2 <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
                ?frame2 <{HALEY_FRAME_TYPE_DESC}> ?rel2 .
                ?dstSlot2 <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                ?dstSlot2 <{HALEY_SLOT_VALUE}> ?c .
                ?dstEdge2 <{VITAL_EDGE_SRC}> ?frame2 .
                ?dstEdge2 <{VITAL_EDGE_DST}> ?dstSlot2 .
                ?c <{VITAL_NAME}> ?cName .

                ?srcSlot3 <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot3 <{HALEY_SLOT_VALUE}> ?c .
                ?srcEdge3 <{VITAL_EDGE_SRC}> ?frame3 .
                ?srcEdge3 <{VITAL_EDGE_DST}> ?srcSlot3 .
                ?frame3 <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
                ?frame3 <{HALEY_FRAME_TYPE_DESC}> ?rel3 .
                ?dstSlot3 <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                ?dstSlot3 <{HALEY_SLOT_VALUE}> ?d .
                ?dstEdge3 <{VITAL_EDGE_SRC}> ?frame3 .
                ?dstEdge3 <{VITAL_EDGE_DST}> ?dstSlot3 .
                ?d <{VITAL_NAME}> ?dName .

                ?srcSlot4 <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot4 <{HALEY_SLOT_VALUE}> ?d .
                ?srcEdge4 <{VITAL_EDGE_SRC}> ?frame4 .
                ?srcEdge4 <{VITAL_EDGE_DST}> ?srcSlot4 .
                ?frame4 <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
                ?frame4 <{HALEY_FRAME_TYPE_DESC}> ?rel4 .
                ?dstSlot4 <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                ?dstSlot4 <{HALEY_SLOT_VALUE}> ?e .
                ?dstEdge4 <{VITAL_EDGE_SRC}> ?frame4 .
                ?dstEdge4 <{VITAL_EDGE_DST}> ?dstSlot4 .
                ?e <{VITAL_NAME}> ?eName .
            }}
        """,
        "description": "4-hop pathway with last entity constrained to VerbSynsetNode. "
                       "Tests entity-type filtering at the endpoint of a deep traversal.",
    },
    {
        "label": "7d. Multi-hop reversed SPARQL order, e = VerbSynset",
        "sparql": f"""
            SELECT ?aName ?rel1 ?bName ?rel2 ?cName ?rel3 ?dName ?rel4 ?eName WHERE {{
                ?e <{HALEY_ENTITY_TYPE}> <urn:VerbSynsetNode> .
                ?e <{VITAL_NAME}> ?eName .

                ?srcSlot4 <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot4 <{HALEY_SLOT_VALUE}> ?d .
                ?srcEdge4 <{VITAL_EDGE_SRC}> ?frame4 .
                ?srcEdge4 <{VITAL_EDGE_DST}> ?srcSlot4 .
                ?frame4 <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
                ?frame4 <{HALEY_FRAME_TYPE_DESC}> ?rel4 .
                ?dstSlot4 <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                ?dstSlot4 <{HALEY_SLOT_VALUE}> ?e .
                ?dstEdge4 <{VITAL_EDGE_SRC}> ?frame4 .
                ?dstEdge4 <{VITAL_EDGE_DST}> ?dstSlot4 .
                ?d <{VITAL_NAME}> ?dName .

                ?srcSlot3 <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot3 <{HALEY_SLOT_VALUE}> ?c .
                ?srcEdge3 <{VITAL_EDGE_SRC}> ?frame3 .
                ?srcEdge3 <{VITAL_EDGE_DST}> ?srcSlot3 .
                ?frame3 <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
                ?frame3 <{HALEY_FRAME_TYPE_DESC}> ?rel3 .
                ?dstSlot3 <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                ?dstSlot3 <{HALEY_SLOT_VALUE}> ?d .
                ?dstEdge3 <{VITAL_EDGE_SRC}> ?frame3 .
                ?dstEdge3 <{VITAL_EDGE_DST}> ?dstSlot3 .
                ?c <{VITAL_NAME}> ?cName .

                ?srcSlot2 <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot2 <{HALEY_SLOT_VALUE}> ?b .
                ?srcEdge2 <{VITAL_EDGE_SRC}> ?frame2 .
                ?srcEdge2 <{VITAL_EDGE_DST}> ?srcSlot2 .
                ?frame2 <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
                ?frame2 <{HALEY_FRAME_TYPE_DESC}> ?rel2 .
                ?dstSlot2 <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                ?dstSlot2 <{HALEY_SLOT_VALUE}> ?c .
                ?dstEdge2 <{VITAL_EDGE_SRC}> ?frame2 .
                ?dstEdge2 <{VITAL_EDGE_DST}> ?dstSlot2 .
                ?b <{VITAL_NAME}> ?bName .

                ?srcSlot1 <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot1 <{HALEY_SLOT_VALUE}> ?a .
                ?srcEdge1 <{VITAL_EDGE_SRC}> ?frame1 .
                ?srcEdge1 <{VITAL_EDGE_DST}> ?srcSlot1 .
                ?frame1 <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
                ?frame1 <{HALEY_FRAME_TYPE_DESC}> ?rel1 .
                ?dstSlot1 <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                ?dstSlot1 <{HALEY_SLOT_VALUE}> ?b .
                ?dstEdge1 <{VITAL_EDGE_SRC}> ?frame1 .
                ?dstEdge1 <{VITAL_EDGE_DST}> ?dstSlot1 .

                ?a <{RDF_TYPE}> <{HALEY_KG_ENTITY}> .
                ?a <{VITAL_NAME}> ?aName .
                FILTER(CONTAINS(?aName, "happy"))
            }}
        """,
        "description": "Same edges as 7c but SPARQL patterns listed in reverse order "
                       "(hop 4 first, hop 1 last). Must produce identical row count to 7c.",
    },

    {
        "label": "7e. Happy frame query (mirrors happy_frame_query_17.sql)",
        "sparql": f"""
            SELECT ?entity ?frame ?srcEntity ?dstEntity WHERE {{
                {{
                    ?srcEntity <{HALEY_KG_DESC}> ?srcDesc .
                    FILTER(REGEX(?srcDesc, "(^|\\\\W)happy(\\\\W|$)", "i"))
                    FILTER(?srcEntity != ?dstEntity)

                    ?srcSlot <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                    ?srcSlot <{HALEY_SLOT_VALUE}> ?srcEntity .
                    ?srcEdge <{VITAL_EDGE_SRC}> ?frame .
                    ?srcEdge <{VITAL_EDGE_DST}> ?srcSlot .
                    ?dstSlot <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                    ?dstSlot <{HALEY_SLOT_VALUE}> ?dstEntity .
                    ?dstEdge <{VITAL_EDGE_SRC}> ?frame .
                    ?dstEdge <{VITAL_EDGE_DST}> ?dstSlot .
                    BIND(?srcEntity AS ?entity)
                }}
                UNION
                {{
                    ?dstEntity <{HALEY_KG_DESC}> ?dstDesc .
                    FILTER(REGEX(?dstDesc, "(^|\\\\W)happy(\\\\W|$)", "i"))
                    FILTER(?srcEntity != ?dstEntity)

                    ?srcSlot <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                    ?srcSlot <{HALEY_SLOT_VALUE}> ?srcEntity .
                    ?srcEdge <{VITAL_EDGE_SRC}> ?frame .
                    ?srcEdge <{VITAL_EDGE_DST}> ?srcSlot .
                    ?dstSlot <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                    ?dstSlot <{HALEY_SLOT_VALUE}> ?dstEntity .
                    ?dstEdge <{VITAL_EDGE_SRC}> ?frame .
                    ?dstEdge <{VITAL_EDGE_DST}> ?dstSlot .
                    BIND(?dstEntity AS ?entity)
                }}
            }}
            ORDER BY ?entity
            LIMIT 500
        """,
        "description": "SPARQL equivalent of happy_frame_query_17.sql: find frames where "
                       "source OR dest has 'happy' in description, srcEntity != dstEntity. "
                       "UNION: arm 1 = source is happy, arm 2 = dest is happy.",
    },

    # ======================================================================
    # 6. ASK / CONSTRUCT
    # ======================================================================
    {
        "label": "6a. ASK: do hyponym edges exist?",
        "sparql": f"""
            ASK {{
                ?frame <{HALEY_FRAME_TYPE}> <urn:Edge_WordnetHyponym>
            }}
        """,
        "description": "Boolean check for existence of hyponym relationships",
    },
    {
        "label": "6b. CONSTRUCT: build simple triples from frame traversal",
        "sparql": f"""
            CONSTRUCT {{
                ?srcEntity <urn:hyponymOf> ?dstEntity
            }} WHERE {{
                ?frame <{HALEY_FRAME_TYPE}> <urn:Edge_WordnetHyponym> .
                ?srcSlot <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot <{HALEY_SLOT_VALUE}> ?srcEntity .
                ?srcEdge <{VITAL_EDGE_SRC}> ?frame .
                ?srcEdge <{VITAL_EDGE_DST}> ?srcSlot .
                ?dstSlot <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                ?dstSlot <{HALEY_SLOT_VALUE}> ?dstEntity .
                ?dstEdge <{VITAL_EDGE_SRC}> ?frame .
                ?dstEdge <{VITAL_EDGE_DST}> ?dstSlot
            }} LIMIT 10
        """,
        "description": "CONSTRUCT simplified hyponym triples from the KGFrame structure",
    },
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def format_sql(sql: str, max_width: int = 120) -> str:
    """Lightly format SQL for readability in the log."""
    # Collapse whitespace but keep structure
    lines = sql.strip().split('\n')
    cleaned = []
    for line in lines:
        stripped = line.rstrip()
        if stripped:
            cleaned.append(stripped)
    return '\n'.join(cleaned)


def _run_explain(sql: str, db_mod) -> list:
    """Run EXPLAIN ANALYZE and return plan lines."""
    try:
        raw = db_mod.execute_query(f"EXPLAIN ANALYZE {sql}")
        return [list(r.values())[0] for r in raw]
    except Exception as e:
        return [f"EXPLAIN failed: {e}"]


def _extract_explain_ms(explain_lines: list) -> dict:
    """Extract Planning Time and Execution Time from EXPLAIN ANALYZE output."""
    import re
    result = {"planning_ms": 0.0, "execution_ms": 0.0}
    for line in explain_lines:
        m = re.search(r'Planning Time:\s*([\d.]+)\s*ms', line)
        if m:
            result["planning_ms"] = float(m.group(1))
        m = re.search(r'Execution Time:\s*([\d.]+)\s*ms', line)
        if m:
            result["execution_ms"] = float(m.group(1))
    return result


def _extract_timing(result) -> dict:
    """Extract key timing values from a QueryResult."""
    t = result.timing or {}
    gd = t.get("generate_detail", {})
    return {
        "sidecar_ms": t.get("sidecar_ms", 0),
        "generate_ms": t.get("generate_ms", 0),
        "execute_ms": t.get("execute_ms", 0),
        "optimize_ms": gd.get("optimize_ms", 0),
        "wall_ms": 0,  # filled in by caller
    }


def _format_rows(result, verbose: bool) -> list:
    """Format result rows for display."""
    lines = []
    if result.query_type == "ASK":
        lines.append(f"  Result: {result.boolean}")
    elif result.query_type == "CONSTRUCT":
        lines.append(f"  Triples: {len(result.triples)}")
        for i, t in enumerate(result.triples[:5]):
            s = str(t.get('subject', ''))[-50:]
            p = str(t.get('predicate', ''))[-40:]
            o = str(t.get('object', ''))[-50:]
            lines.append(f"    [{i}] ...{s}  {p}  ...{o}")
        if len(result.triples) > 5:
            lines.append(f"    ... ({len(result.triples) - 5} more)")
    else:
        lines.append(f"  Rows: {result.row_count}  Columns: {result.columns}")
        max_show = 10 if verbose else 5
        for i, row in enumerate(result.rows[:max_show]):
            vals = {}
            for k, v in row.items():
                sv = str(v) if v is not None else "NULL"
                if sv.startswith("http://vital.ai/"):
                    sv = "vital:" + sv.split('#')[-1] if '#' in sv else sv[-40:]
                elif sv.startswith("http://"):
                    sv = sv.split('#')[-1] if '#' in sv else sv[-40:]
                elif len(sv) > 60:
                    sv = sv[:57] + "..."
                vals[k] = sv
            lines.append(f"    [{i}] {vals}")
        if result.row_count > max_show:
            lines.append(f"    ... ({result.row_count - max_show} more)")
    return lines


async def _run_single_variant(space_id, sparql, db_mod):
    """Run a query via the async SparqlOrchestrator."""
    import psycopg
    from psycopg.rows import dict_row

    async with SparqlOrchestrator(space_id=space_id) as orch:
        # Get SQL (no execution)
        sql_result = await orch.execute(sparql, sql_only=True)
        if not sql_result.ok:
            return None, sql_result.error

        # Execute with timing
        t0 = time.monotonic()
        result = await orch.execute(sparql, include_sql=True)
        wall_ms = (time.monotonic() - t0) * 1000

        if not result.ok:
            return None, result.error

        # EXPLAIN ANALYZE on a fresh connection to avoid cache effects
        conn_params = db_mod.get_connection_params()
        conninfo = psycopg.conninfo.make_conninfo(**conn_params)
        explain_lines = []
        try:
            with psycopg.connect(conninfo, row_factory=dict_row) as fresh_conn:
                with fresh_conn.cursor() as cur:
                    cur.execute(f"EXPLAIN ANALYZE {sql_result.sql}")
                    explain_lines = [list(r.values())[0] for r in cur.fetchall()]
        except Exception as e:
            explain_lines = [f"EXPLAIN failed: {e}"]

        ti = _extract_timing(result)
        ti["wall_ms"] = wall_ms

        return {
            "sql": sql_result.sql,
            "explain": explain_lines,
            "result": result,
            "timing": ti,
            "explain_ms": _extract_explain_ms(explain_lines),
        }, None


async def run_queries(space_id: str, verbose: bool = False, selected: str = None):
    """
    Execute queries via the async SparqlOrchestrator and report timings.
    """
    from vitalgraph_sparql_sql import db

    passed = 0
    failed = 0
    errors = []
    results_summary = []  # (label, rows, exec_ms, pg_exec_ms, pg_plan_ms, wall_ms)

    queries = QUERIES
    if selected:
        prefixes = [s.strip() for s in selected.split(',')]
        queries = [q for q in QUERIES if any(q['label'].startswith(p) for p in prefixes)]
        if not queries:
            print(f"No queries matched filter: {selected}")
            print(f"Available: {', '.join(q['label'].split('.')[0] + '.' for q in QUERIES)}")
            return 1

    print("=" * 80)
    print(f"WordNet KGFrames — SPARQL → SQL v2")
    print(f"Space: {space_id}  |  Queries: {len(queries)}")
    print("=" * 80)

    for q in queries:
        label = q['label']
        sparql = q['sparql']
        desc = q.get('description', '')

        print(f"\n{'━' * 80}")
        print(f"  {label}")
        if desc:
            print(f"  {desc}")
        print(f"{'━' * 80}")

        # Show SPARQL
        sparql_clean = textwrap.dedent(sparql).strip()
        print(f"\n  SPARQL:")
        for line in sparql_clean.split('\n'):
            print(f"    {line}")

        data, err = await _run_single_variant(space_id, sparql, db)
        if err:
            print(f"\n  FAILED: {err}")
            failed += 1
            errors.append((label, err))
            continue

        passed += 1

        ti = data["timing"]
        ex = data["explain_ms"]
        print(f"\n  SQL: {len(data['sql'])} chars")
        print(f"  Execute: {ti['execute_ms']:.0f}ms  (wall: {ti['wall_ms']:.0f}ms, gen: {ti['generate_ms']:.0f}ms)")
        print(f"  EXPLAIN:  PG planning={ex['planning_ms']:.1f}ms  PG execution={ex['execution_ms']:.1f}ms")

        if verbose:
            print(f"  SQL:")
            for line in format_sql(data["sql"]).split('\n'):
                print(f"    {line}")
            print(f"  Full EXPLAIN:")
            for line in data["explain"]:
                print(f"    {line}")

        for line in _format_rows(data["result"], verbose):
            print(line)

        rows = data["result"].row_count
        results_summary.append((
            label, rows,
            ti["execute_ms"], ex["execution_ms"], ex["planning_ms"], ti["wall_ms"],
        ))

    # ── Summary table ───────────────────────────────────────────────────
    if results_summary:
        print(f"\n{'=' * 80}")
        print(f"Timing Summary")
        print(f"{'=' * 80}")
        print(f"  {'Query':<45} {'Rows':>5} {'Exec':>9} {'PG Plan':>9} {'PG Exec':>9} {'Wall':>9}")
        print(f"  {'-'*45} {'-'*5} {'-'*9} {'-'*9} {'-'*9} {'-'*9}")
        for label, rows, exec_ms, pg_ms, plan_ms, wall_ms in sorted(results_summary, key=lambda t: t[5], reverse=True):
            short = label[:45]
            print(f"  {short:<45} {rows:>5} {exec_ms:>8.0f}ms {plan_ms:>8.1f}ms {pg_ms:>8.0f}ms {wall_ms:>8.0f}ms")
        total_e = sum(r[2] for r in results_summary)
        total_p = sum(r[3] for r in results_summary)
        total_pl = sum(r[4] for r in results_summary)
        total_w = sum(r[5] for r in results_summary)
        print(f"  {'-'*45} {'-'*5} {'-'*9} {'-'*9} {'-'*9} {'-'*9}")
        print(f"  {'TOTAL':<45} {'':>5} {total_e:>8.0f}ms {total_pl:>8.1f}ms {total_p:>8.0f}ms {total_w:>8.0f}ms")

    # Summary
    print(f"\n{'=' * 80}")
    print(f"Summary: {passed} passed, {failed} failed, {passed + failed} total")
    if errors:
        print(f"\nFailures:")
        for label, err in errors:
            print(f"  [{label}] {err}")
    print(f"{'=' * 80}")
    return 0 if failed == 0 else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Query WordNet KGFrames data via SPARQL→SQL pipeline"
    )
    parser.add_argument("--space", default="wordnet_exp",
                        help="PostgreSQL space ID (table prefix)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show more result rows and full SQL/EXPLAIN")
    parser.add_argument("-q", "--query", default=None,
                        help="Run only queries starting with these prefixes (comma-separated, e.g. '1a,3c')")
    parser.add_argument("--log-level", default="WARNING",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="Logging level for the SPARQL pipeline internals")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(name)-30s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    sys.exit(asyncio.run(run_queries(args.space, verbose=args.verbose, selected=args.query)))


if __name__ == "__main__":
    main()
