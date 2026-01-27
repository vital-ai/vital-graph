"""
KGTypes READ Implementation for VitalGraph

This module provides READ operations for KGTypes using SPARQL queries.
Implements GET, LIST, and batch GET operations with proper VitalSigns integration.
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGType import KGType
from .kg_backend_utils import FusekiPostgreSQLBackendAdapter


class KGTypesReadProcessor:
    """Processor for KGTypes READ operations."""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.KGTypesReadProcessor")
    
    async def get_kgtype_by_uri(self, backend, space_id: str, graph_id: str, kgtype_uri: str) -> Optional[GraphObject]:
        """
        Get a single KGType by URI.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            kgtype_uri: URI of the KGType to retrieve
            
        Returns:
            Optional[GraphObject]: KGType GraphObject or None if not found
        """
        try:
            self.logger.info(f"🔍 Getting KGType by URI: {kgtype_uri}")
            
            # SPARQL query to get all properties of the KGType
            # Filter out materialized predicates (vg-direct:*) as they're not VitalSigns properties
            query = f"""
            SELECT ?p ?o WHERE {{
                GRAPH <{graph_id}> {{
                    <{kgtype_uri}> ?p ?o .
                    FILTER(?p != <http://vital.ai/vitalgraph/direct#hasEntityFrame> &&
                           ?p != <http://vital.ai/vitalgraph/direct#hasFrame> &&
                           ?p != <http://vital.ai/vitalgraph/direct#hasSlot>)
                }}
            }}
            """
            
            result = await backend.execute_sparql_query(space_id, query)
            
            # Handle dictionary response format from backend
            if isinstance(result, dict):
                result = result.get('results', {}).get('bindings', [])
            
            if not result or len(result) == 0:
                self.logger.info(f"KGType not found: {kgtype_uri}")
                return None
            
            # Convert SPARQL results to RDFLib triples
            from rdflib import URIRef, Literal, BNode
            
            triples = []
            subject = URIRef(kgtype_uri)
            
            for binding in result:
                # Extract predicate and object from SPARQL binding
                predicate_data = binding.get('p', {})
                object_data = binding.get('o', {})
                
                # Convert to RDFLib terms
                if predicate_data.get('type') == 'uri':
                    predicate = URIRef(predicate_data.get('value', ''))
                else:
                    continue
                
                if object_data.get('type') == 'uri':
                    obj = URIRef(object_data.get('value', ''))
                elif object_data.get('type') == 'literal':
                    obj = Literal(object_data.get('value', ''))
                elif object_data.get('type') == 'bnode':
                    obj = BNode(object_data.get('value', ''))
                else:
                    continue
                
                triples.append((subject, predicate, obj))
            
            # Convert triples to VitalSigns GraphObject
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            
            # Log triples for debugging
            self.logger.info(f"🔍 Converting {len(triples)} triples to GraphObject for {kgtype_uri}")
            for i, triple in enumerate(triples[:5]):  # Log first 5 triples
                self.logger.info(f"  Triple {i+1}: {triple}")
            
            try:
                graph_object = GraphObject.from_triples(triples)
                if graph_object:
                    self.logger.info(f"✅ Successfully created GraphObject for {kgtype_uri}")
                    self.logger.info(f"  GraphObject type: {type(graph_object).__name__}")
                    self.logger.info(f"  GraphObject URI: {getattr(graph_object, 'URI', 'No URI attribute')}")
                else:
                    self.logger.warning(f"⚠️  GraphObject.from_triples returned None for {kgtype_uri}")
                    return None
            except Exception as e:
                self.logger.error(f"❌ Failed to convert triples to GraphObject for {kgtype_uri}: {e}")
                return None
            
            self.logger.info(f"✅ Retrieved KGType: {kgtype_uri} with {len(triples)} triples")
            return graph_object
            
        except Exception as e:
            self.logger.error(f"❌ Failed to get KGType {kgtype_uri}: {e}")
            raise
    
    async def get_kgtypes_by_uris(self, backend, space_id: str, graph_id: str, kgtype_uris: List[str]) -> List[GraphObject]:
        """
        Get multiple KGTypes by URIs.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            kgtype_uris: List of KGType URIs to retrieve
            
        Returns:
            List[GraphObject]: List of KGType GraphObjects (may be subclasses of KGType or KGType instances)
        """
        try:
            self.logger.info(f"🔍 Getting {len(kgtype_uris)} KGTypes by URIs")
            
            # Build VALUES clause for multiple URIs
            uri_values = " ".join([f"<{uri}>" for uri in kgtype_uris])
            
            # SPARQL query to get all properties of the KGTypes
            # Filter out materialized predicates (vg-direct:*) as they're not VitalSigns properties
            query = f"""
            SELECT ?s ?p ?o WHERE {{
                VALUES ?s {{ {uri_values} }}
                GRAPH <{graph_id}> {{
                    ?s ?p ?o .
                    FILTER(?p != <http://vital.ai/vitalgraph/direct#hasEntityFrame> &&
                           ?p != <http://vital.ai/vitalgraph/direct#hasFrame> &&
                           ?p != <http://vital.ai/vitalgraph/direct#hasSlot>)
                }}
            }}
            ORDER BY ?s
            """
            
            result = await backend.execute_sparql_query(space_id, query)
            
            # Handle dictionary response format from backend
            if isinstance(result, dict):
                result = result.get('results', {}).get('bindings', [])
            elif not result:
                result = []
            
            # Convert SPARQL results to RDFLib triples
            from rdflib import Graph, URIRef, Literal, BNode
            
            triples = []
            for binding in result:
                # Extract subject, predicate, object from SPARQL binding
                subject_data = binding.get('s', {})
                predicate_data = binding.get('p', {})
                object_data = binding.get('o', {})
                
                # Convert to RDFLib terms
                if subject_data.get('type') == 'uri':
                    subject = URIRef(subject_data.get('value', ''))
                elif subject_data.get('type') == 'bnode':
                    subject = BNode(subject_data.get('value', ''))
                else:
                    continue
                
                if predicate_data.get('type') == 'uri':
                    predicate = URIRef(predicate_data.get('value', ''))
                else:
                    continue
                
                if object_data.get('type') == 'uri':
                    obj = URIRef(object_data.get('value', ''))
                elif object_data.get('type') == 'literal':
                    obj = Literal(object_data.get('value', ''))
                elif object_data.get('type') == 'bnode':
                    obj = BNode(object_data.get('value', ''))
                else:
                    continue
                
                triples.append((subject, predicate, obj))
            
            # Handle empty triples list
            if not triples:
                self.logger.info(f"✅ No KGTypes found for the given URIs")
                return []
            
            # Convert RDFLib triples to VitalSigns GraphObjects
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            graph_objects = GraphObject.from_triples_list(triples)
            
            self.logger.info(f"✅ Retrieved {len(graph_objects)} KGType GraphObjects from {len(triples)} triples")
            return graph_objects
            
        except Exception as e:
            self.logger.error(f"❌ Failed to get KGTypes by URIs: {e}")
            raise
    
    async def list_kgtypes(self, backend, space_id: str, graph_id: str, 
                          page_size: int = 100, offset: int = 0, 
                          search: Optional[str] = None) -> Tuple[List[Tuple], int]:
        """
        List KGTypes with pagination and optional search.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            page_size: Number of types per page
            offset: Number of types to skip
            search: Optional search text to filter types
            
        Returns:
            Tuple[List[Tuple], int]: (List of RDFLib triples (subject, predicate, object), total count)
        """
        try:
            self.logger.info(f"🔍 Listing KGTypes (page_size: {page_size}, offset: {offset}, search: {search})")
            
            # SPARQL query to get KGTypes with pagination and search
            if search:
                # Use a subquery to first filter KGTypes that match the search criteria
                query = f"""
                SELECT ?s ?p ?o WHERE {{
                    GRAPH <{graph_id}> {{
                        {{
                            SELECT DISTINCT ?s WHERE {{
                                {{
                                    ?s a <http://vital.ai/ontology/haley-ai-kg#KGType> .
                                }} UNION {{
                                    ?s a <http://vital.ai/ontology/haley-ai-kg#KGEntityType> .
                                }} UNION {{
                                    ?s a <http://vital.ai/ontology/haley-ai-kg#KGFrameType> .
                                }} UNION {{
                                    ?s a <http://vital.ai/ontology/haley-ai-kg#KGRelationType> .
                                }} UNION {{
                                    ?s a <http://vital.ai/ontology/haley-ai-kg#KGSlotType> .
                                }}
                                {{
                                    ?s <http://vital.ai/ontology/vital-core#hasName> ?name .
                                    FILTER (CONTAINS(LCASE(STR(?name)), LCASE("{search}")))
                                }} UNION {{
                                    ?s <http://vital.ai/ontology/vital-core#hasDescription> ?description .
                                    FILTER (CONTAINS(LCASE(STR(?description)), LCASE("{search}")))
                                }} UNION {{
                                    FILTER (CONTAINS(LCASE(STR(?s)), LCASE("{search}")))
                                }}
                            }}
                            ORDER BY ?s
                            LIMIT {page_size}
                            OFFSET {offset}
                        }}
                        ?s ?p ?o .
                        FILTER(?p != <http://vital.ai/vitalgraph/direct#hasEntityFrame> &&
                               ?p != <http://vital.ai/vitalgraph/direct#hasFrame> &&
                               ?p != <http://vital.ai/vitalgraph/direct#hasSlot>)
                    }}
                }}
                ORDER BY ?s
                """
            else:
                # No search filter - get all KGTypes
                query = f"""
                SELECT ?s ?p ?o WHERE {{
                    GRAPH <{graph_id}> {{
                        {{
                            SELECT DISTINCT ?s WHERE {{
                                {{
                                    ?s a <http://vital.ai/ontology/haley-ai-kg#KGType> .
                                }} UNION {{
                                    ?s a <http://vital.ai/ontology/haley-ai-kg#KGEntityType> .
                                }} UNION {{
                                    ?s a <http://vital.ai/ontology/haley-ai-kg#KGFrameType> .
                                }} UNION {{
                                    ?s a <http://vital.ai/ontology/haley-ai-kg#KGRelationType> .
                                }} UNION {{
                                    ?s a <http://vital.ai/ontology/haley-ai-kg#KGSlotType> .
                                }}
                            }}
                            ORDER BY ?s
                            LIMIT {page_size}
                            OFFSET {offset}
                        }}
                        ?s ?p ?o .
                        FILTER(?p != <http://vital.ai/vitalgraph/direct#hasEntityFrame> &&
                               ?p != <http://vital.ai/vitalgraph/direct#hasFrame> &&
                               ?p != <http://vital.ai/vitalgraph/direct#hasSlot>)
                    }}
                }}
                ORDER BY ?s
                """
            
            result = await backend.execute_sparql_query(space_id, query)
            
            # Handle dictionary response format from backend
            if isinstance(result, dict):
                result = result.get('results', {}).get('bindings', [])
            elif not result:
                result = []
            
            # Get total count for pagination
            if search:
                count_query = f"""
                SELECT (COUNT(DISTINCT ?s) AS ?count) WHERE {{
                    GRAPH <{graph_id}> {{
                        {{
                            ?s a <http://vital.ai/ontology/haley-ai-kg#KGType> .
                        }} UNION {{
                            ?s a <http://vital.ai/ontology/haley-ai-kg#KGEntityType> .
                        }} UNION {{
                            ?s a <http://vital.ai/ontology/haley-ai-kg#KGFrameType> .
                        }} UNION {{
                            ?s a <http://vital.ai/ontology/haley-ai-kg#KGRelationType> .
                        }} UNION {{
                            ?s a <http://vital.ai/ontology/haley-ai-kg#KGSlotType> .
                        }}
                        {{
                            ?s <http://vital.ai/ontology/vital-core#hasName> ?name .
                            FILTER (CONTAINS(LCASE(STR(?name)), LCASE("{search}")))
                        }} UNION {{
                            ?s <http://vital.ai/ontology/vital-core#hasDescription> ?description .
                            FILTER (CONTAINS(LCASE(STR(?description)), LCASE("{search}")))
                        }} UNION {{
                            FILTER (CONTAINS(LCASE(STR(?s)), LCASE("{search}")))
                        }}
                    }}
                }}
                """
            else:
                count_query = f"""
                SELECT (COUNT(DISTINCT ?s) AS ?count) WHERE {{
                    GRAPH <{graph_id}> {{
                        {{
                            ?s a <http://vital.ai/ontology/haley-ai-kg#KGType> .
                        }} UNION {{
                            ?s a <http://vital.ai/ontology/haley-ai-kg#KGEntityType> .
                        }} UNION {{
                            ?s a <http://vital.ai/ontology/haley-ai-kg#KGFrameType> .
                        }} UNION {{
                            ?s a <http://vital.ai/ontology/haley-ai-kg#KGRelationType> .
                        }} UNION {{
                            ?s a <http://vital.ai/ontology/haley-ai-kg#KGSlotType> .
                        }}
                    }}
                }}
                """
            
            count_result = await backend.execute_sparql_query(space_id, count_query)
            
            # Handle dictionary response format from backend
            if isinstance(count_result, dict):
                count_result = count_result.get('results', {}).get('bindings', [])
            
            total_count = 0
            if count_result and len(count_result) > 0:
                total_count = int(count_result[0].get('count', {}).get('value', 0))
            
            # Convert SPARQL results to RDFLib triples
            from rdflib import Graph, URIRef, Literal, BNode
            
            triples = []
            for binding in result:
                # Extract subject, predicate, object from SPARQL binding
                subject_data = binding.get('s', {})
                predicate_data = binding.get('p', {})
                object_data = binding.get('o', {})
                
                # Convert to RDFLib terms
                if subject_data.get('type') == 'uri':
                    subject = URIRef(subject_data.get('value', ''))
                elif subject_data.get('type') == 'bnode':
                    subject = BNode(subject_data.get('value', ''))
                else:
                    continue
                
                if predicate_data.get('type') == 'uri':
                    predicate = URIRef(predicate_data.get('value', ''))
                else:
                    continue
                
                if object_data.get('type') == 'uri':
                    obj = URIRef(object_data.get('value', ''))
                elif object_data.get('type') == 'literal':
                    obj = Literal(object_data.get('value', ''))
                elif object_data.get('type') == 'bnode':
                    obj = BNode(object_data.get('value', ''))
                else:
                    continue
                
                triples.append((subject, predicate, obj))
            
            self.logger.info(f"✅ Listed {len(triples)} KGType RDFLib triples (total: {total_count})")
            return triples, total_count
            
        except Exception as e:
            self.logger.error(f"❌ Failed to list KGTypes: {e}")
            raise
    
    
