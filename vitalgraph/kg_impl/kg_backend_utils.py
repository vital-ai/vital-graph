"""
KG Backend Abstraction Layer

This module provides a unified interface for KG operations across different backends
(Fuseki+PostgreSQL, PyOxigraph, etc.). It abstracts backend-specific implementation
details and provides a consistent API for KG endpoint implementations.
"""

import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass

# VitalSigns imports
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame

# Model imports
from ..model.kgentities_model import EntityCreateResponse, EntityUpdateResponse

# Graph retrieval utilities
from .kg_graph_retrieval_utils import GraphObjectRetriever


@dataclass
class BackendOperationResult:
    """Result of a backend operation."""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    objects: Optional[List[GraphObject]] = None


class KGBackendInterface(ABC):
    """Abstract interface for KG backend operations."""
    
    @abstractmethod
    async def store_objects(self, space_id: str, graph_id: str, objects: List[GraphObject]) -> BackendOperationResult:
        """Store VitalSigns objects in the backend."""
        pass
    
    @abstractmethod
    async def object_exists(self, space_id: str, graph_id: str, uri: str) -> bool:
        """Check if an object exists in the backend."""
        pass
    
    @abstractmethod
    async def delete_object(self, space_id: str, graph_id: str, uri: str) -> BackendOperationResult:
        """Delete an object from the backend."""
        pass
    
    @abstractmethod
    async def execute_sparql_query(self, space_id: str, query: str) -> Dict[str, Any]:
        """Execute a SPARQL query against the backend."""
        pass
    
    @abstractmethod
    async def validate_parent_connection(self, space_id: str, graph_id: str, 
                                       parent_uri: str, child_uri: str) -> bool:
        """Validate that a parent-child relationship exists."""
        pass
    
    @abstractmethod
    async def update_quads(self, space_id: str, graph_id: str, 
                          delete_quads: List[tuple], insert_quads: List[tuple]) -> bool:
        """
        Atomically update quads by deleting old ones and inserting new ones.
        
        Implementation Strategy:
        1. Execute DELETE and INSERT within single PostgreSQL transaction
        2. Once PostgreSQL commits, synchronize Fuseki separately
        3. PostgreSQL transaction provides atomicity guarantee
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier (full URI)
            delete_quads: List of (subject, predicate, object, graph) tuples to delete
            insert_quads: List of (subject, predicate, object, graph) tuples to insert
            
        Returns:
            bool: True if operation succeeded, False otherwise
        """
        pass


class FusekiPostgreSQLBackendAdapter(KGBackendInterface):
    """Adapter for Fuseki+PostgreSQL hybrid backend."""
    
    def __init__(self, backend_impl):
        """Initialize with the actual backend implementation."""
        self.backend = backend_impl
        self.logger = logging.getLogger(f"{__name__}.FusekiPostgreSQLBackendAdapter")
        # Initialize centralized graph retrieval utility
        self.retriever = GraphObjectRetriever(backend_impl)
    
    async def store_objects(self, space_id: str, graph_id: str, objects: List[GraphObject]) -> BackendOperationResult:
        """Store VitalSigns objects using Fuseki+PostgreSQL backend following working triples endpoint pattern."""
        try:
            self.logger.debug(f"🔥 BACKEND ADAPTER: Storing {len(objects)} objects in space {space_id}, graph {graph_id}")
            
            # Convert VitalSigns objects to RDF quads using the same pattern as working triples endpoint
            from rdflib import Graph, URIRef
            
            # Create RDF graph and add objects
            rdf_graph = Graph()
            
            # Convert each object to RDF and add to graph
            for obj in objects:
                try:
                    # Use VitalSigns to_rdf method to get RDF representation
                    obj_rdf = obj.to_rdf()
                    # Parse the RDF and add to our graph
                    rdf_graph.parse(data=obj_rdf, format='turtle')
                    # self.logger.info(f"🔥 Added object {getattr(obj, 'URI', 'NO_URI')} to RDF graph")
                except Exception as e:
                    self.logger.warning(f"Failed to convert object to RDF: {e}")
                    continue
            
            # Use graph_id directly as it should already be a proper URI
            graph_uri = URIRef(graph_id)
            quads = []
            
            self.logger.debug(f"🔥 RDFLib graph has {len(rdf_graph)} triples")
            for s, p, o in rdf_graph:
                # Keep RDFLib objects to preserve type information (like triples endpoint)
                quads.append((s, p, o, graph_uri))
            
            self.logger.debug(f"🔥 Converted to {len(quads)} quads with graph {graph_id}")
            
            # Store via backend using add_rdf_quads_batch (like triples endpoint)
            success = await self.backend.add_rdf_quads_batch(space_id, quads)
            self.logger.debug(f"🔥 FUSEKI INSERT RESULT: {success}")
            
            return BackendOperationResult(
                success=True,
                message=f"Successfully stored {len(objects)} objects",
                data={"stored_count": len(objects)}
            )
            
        except Exception as e:
            self.logger.error(f"Error storing objects: {e}")
            return BackendOperationResult(
                success=False,
                message=f"Failed to store objects: {str(e)}",
                error=str(e)
            )
    
    async def object_exists(self, space_id: str, graph_id: str, uri: str) -> bool:
        """Check if object exists using SPARQL ASK query."""
        try:
            # Use graph_id directly as it should already be a proper URI
            full_graph_uri = graph_id
            
            ask_query = f"""
            ASK {{
                GRAPH <{full_graph_uri}> {{
                    <{uri}> ?p ?o .
                }}
            }}
            """
            
            result = await self.backend.query_quads(space_id, ask_query)
            # ASK queries return SPARQL JSON format with boolean result
            if isinstance(result, dict) and 'boolean' in result:
                return result['boolean']
            elif isinstance(result, list):
                return len(result) > 0
            else:
                return False
            
        except Exception as e:
            self.logger.error(f"Error checking object existence: {e}")
            return False
    
    async def get_object(self, space_id: str, graph_id: str, object_uri: str) -> BackendOperationResult:
        """Retrieve a single object by URI (generic method for any object type)."""
        try:
            self.logger.debug(f"🔍 Retrieving object {object_uri} from graph {graph_id}")
            
            # Use centralized retriever (filters OUT materialized edges by default)
            triples = await self.retriever.get_object_triples(
                space_id, graph_id, object_uri, include_materialized_edges=False
            )
            
            if not triples:
                return BackendOperationResult(success=True, message="Object not found", objects=[])
            
            # Convert triples to VitalSigns objects
            objects = await self._triples_to_vitalsigns(triples)
            
            return BackendOperationResult(
                success=True,
                message=f"Object {object_uri} retrieved successfully",
                objects=objects
            )
            
        except Exception as e:
            self.logger.error(f"Error retrieving object {object_uri}: {e}")
            return BackendOperationResult(
                success=False,
                message=f"Failed to retrieve object: {str(e)}",
                error=str(e),
                objects=[]
            )
    
    async def get_entity(self, space_id: str, graph_id: str, entity_uri: str) -> BackendOperationResult:
        """Retrieve a single entity by URI."""
        try:
            self.logger.debug(f"🔍 QUERYING FUSEKI - Space: {space_id}, Graph: {graph_id}")
            self.logger.debug(f"🔍 ENTITY URI: {entity_uri}")
            
            # Use centralized retriever (filters OUT materialized edges by default)
            triples = await self.retriever.get_object_triples(
                space_id, graph_id, entity_uri, include_materialized_edges=False
            )
            
            self.logger.debug(f"🔍 QUERY RESULT COUNT: {len(triples)}")
            self.logger.debug(f"🔍 First 3 triples: {triples[:3] if triples else 'NONE'}")
            
            if not triples:
                self.logger.warning(f"🔍 No triples returned for entity {entity_uri}")
                return BackendOperationResult(success=True, message="Entity not found", objects=[])
            
            # Convert triples to VitalSigns objects
            self.logger.debug(f"🔍 About to convert {len(triples)} triples to VitalSigns")
            objects = await self._triples_to_vitalsigns(triples)
            self.logger.debug(f"🔍 Conversion complete: got {len(objects)} objects")
            
            return BackendOperationResult(
                success=True,
                message=f"Successfully retrieved entity: {entity_uri}",
                objects=objects
            )
            
        except Exception as e:
            self.logger.error(f"Error retrieving entity {entity_uri}: {e}")
            return BackendOperationResult(
                success=False,
                message=f"Failed to retrieve entity: {str(e)}",
                error=str(e),
                objects=[]
            )
    
    async def get_entity_graph(self, space_id: str, graph_id: str, entity_uri: str) -> BackendOperationResult:
        """Retrieve complete entity graph including related objects."""
        try:
            self.logger.debug(f"🔍 Looking for entity graph with URI: {entity_uri}")
            self.logger.debug(f"🔍 In graph: {graph_id}")
            
            # Use centralized retriever (filters OUT materialized edges by default)
            triples = await self.retriever.get_entity_graph(
                space_id, graph_id, entity_uri, include_materialized_edges=False
            )
            
            self.logger.debug(f"🔍 Retrieved {len(triples)} triples")
            if triples and len(triples) > 0:
                # Show first few triples for debugging
                for i, triple in enumerate(triples[:5]):
                    self.logger.debug(f"🔍 Triple {i+1}: {triple}")
                if len(triples) > 5:
                    self.logger.debug(f"🔍 ... and {len(triples) - 5} more triples")
            
            if not triples or len(triples) == 0:
                return BackendOperationResult(
                    success=False,
                    message=f"Entity graph not found: {entity_uri}",
                    objects=[]
                )
            
            # Convert triples to VitalSigns objects
            objects = await self._triples_to_vitalsigns(triples)
            
            return BackendOperationResult(
                success=True,
                message=f"Successfully retrieved entity graph: {entity_uri}",
                objects=objects
            )
            
        except Exception as e:
            self.logger.error(f"Error retrieving entity graph {entity_uri}: {e}")
            return BackendOperationResult(
                success=False,
                message=f"Failed to retrieve entity graph: {str(e)}",
                error=str(e),
                objects=[]
            )
    
    async def get_entity_by_reference_id(self, space_id: str, graph_id: str, reference_id: str) -> BackendOperationResult:
        """Retrieve a single entity by reference ID."""
        try:
            self.logger.debug(f"🔍 QUERYING ENTITY BY REFERENCE ID: {reference_id}")
            
            # Use centralized retriever (filters OUT materialized edges by default)
            triples = await self.retriever.get_entity_by_reference_id(
                space_id, graph_id, reference_id, include_materialized_edges=False
            )
            
            self.logger.debug(f"🔍 QUERY RESULT COUNT: {len(triples) if triples else 0}")
            
            if not triples:
                return BackendOperationResult(success=True, message=f"Entity not found with reference ID: {reference_id}", objects=[])
            
            # Convert triples to VitalSigns objects
            objects = await self._triples_to_vitalsigns(triples)
            
            return BackendOperationResult(
                success=True,
                message=f"Successfully retrieved entity by reference ID: {reference_id}",
                objects=objects
            )
            
        except Exception as e:
            self.logger.error(f"Error retrieving entity by reference ID {reference_id}: {e}")
            return BackendOperationResult(
                success=False,
                message=f"Failed to retrieve entity: {str(e)}",
                error=str(e),
                objects=[]
            )
    
    async def get_entity_graph_by_reference_id(self, space_id: str, graph_id: str, reference_id: str) -> BackendOperationResult:
        """Retrieve complete entity graph by reference ID."""
        try:
            self.logger.debug(f"🔍 Looking for entity graph with reference ID: {reference_id}")
            self.logger.debug(f"🔍 In graph: {graph_id}")
            
            # Use centralized retriever (filters OUT materialized edges by default)
            triples = await self.retriever.get_entity_graph_by_reference_id(
                space_id, graph_id, reference_id, include_materialized_edges=False
            )
            
            self.logger.debug(f"🔍 Retrieved {len(triples) if triples else 0} triples")
            if triples and len(triples) > 0:
                # Show first few triples for debugging
                for i, triple in enumerate(triples[:5]):
                    self.logger.debug(f"🔍 Triple {i+1}: {triple}")
                if len(triples) > 5:
                    self.logger.debug(f"🔍 ... and {len(triples) - 5} more triples")
            
            if not triples or len(triples) == 0:
                return BackendOperationResult(
                    success=False,
                    message=f"Entity graph not found with reference ID: {reference_id}",
                    objects=[]
                )
            
            # Convert triples to VitalSigns objects
            objects = await self._triples_to_vitalsigns(triples)
            
            return BackendOperationResult(
                success=True,
                message=f"Successfully retrieved entity graph by reference ID: {reference_id}",
                objects=objects
            )
            
        except Exception as e:
            self.logger.error(f"Error retrieving entity graph by reference ID {reference_id}: {e}")
            return BackendOperationResult(
                success=False,
                message=f"Failed to retrieve entity graph: {str(e)}",
                error=str(e),
                objects=[]
            )
    
    async def _sparql_results_to_objects(self, sparql_result: List[Dict], single_uri: Optional[str] = None) -> List[GraphObject]:
        """Convert SPARQL query results (SPARQL JSON bindings) back to VitalSigns objects."""
        try:
            from vital_ai_vitalsigns.vitalsigns import VitalSigns
            
            if not sparql_result:
                return []
            
            # Use VitalSigns to convert SPARQL results directly
            vs = VitalSigns()
            
            # Convert SPARQL results to RDF triples format for VitalSigns
            from rdflib import URIRef, Literal
            
            triples = []
            for binding in sparql_result:
                # Handle SPARQL JSON binding format
                if 's' in binding:  # Graph query with subject
                    subject = str(binding['s'].get('value'))  # Cast to string to handle CombinedProperty
                    predicate = str(binding['p'].get('value'))  # Cast to string to handle CombinedProperty
                    obj_data = binding['o']
                else:  # Single entity query
                    subject = str(single_uri) if single_uri else None  # Cast to string to handle CombinedProperty
                    predicate = str(binding['p'].get('value'))  # Cast to string to handle CombinedProperty
                    obj_data = binding['o']
                
                if not subject:
                    continue
                
                # Create RDF triple tuple using rdflib types (as VitalSigns expects)
                subject_ref = URIRef(subject)
                predicate_ref = URIRef(predicate)
                
                # Handle object based on type
                if obj_data.get('type') == 'uri':
                    object_ref = URIRef(str(obj_data.get('value')))  # Cast to string to handle CombinedProperty
                else:
                    # Literal value
                    object_ref = Literal(str(obj_data.get('value')))  # Cast to string to handle CombinedProperty
                
                triple = (subject_ref, predicate_ref, object_ref)
                triples.append(triple)
            
            if not triples:
                return []
            
            # Group triples by subject URI to create separate objects
            from collections import defaultdict
            subject_triples = defaultdict(list)
            
            for triple in triples:
                subject_uri = str(triple[0])  # Convert URIRef to string
                subject_triples[subject_uri].append(triple)
            
            # Convert each subject's triples to a VitalSigns object
            objects = []
            for subject_uri, subject_triple_list in subject_triples.items():
                try:
                    def triple_generator():
                        for triple in subject_triple_list:
                            yield triple
                    
                    # VitalSigns from_triples returns a single object
                    obj = vs.from_triples(triple_generator())
                    if obj:
                        objects.append(obj)
                        
                except Exception as e:
                    self.logger.warning(f"Failed to convert triples for subject {subject_uri}: {e}")
                    continue
            
            self.logger.debug(f"🔍 Converted {len(triples)} triples into {len(objects)} VitalSigns objects")
            return objects
            
        except Exception as e:
            import traceback
            self.logger.error(f"Error converting SPARQL results to objects: {e}")
            self.logger.error("FULL TRACEBACK WITH LINE NUMBERS:")
            self.logger.error(traceback.format_exc())
            return []
    
    async def _triples_to_vitalsigns(self, triples: List[tuple]) -> List[GraphObject]:
        """
        Convert RDFLib triples to VitalSigns objects.
        
        Args:
            triples: List of (subject, predicate, object) tuples with RDFLib URIRef/Literal objects
            
        Returns:
            List of VitalSigns GraphObject instances
        """
        try:
            from vital_ai_vitalsigns.vitalsigns import VitalSigns
            
            if not triples:
                return []
            
            # Log first few triples to see their format
            self.logger.debug(f"🔍 Converting {len(triples)} triples to VitalSigns")
            for i, triple in enumerate(triples[:3]):
                self.logger.debug(f"  Triple {i+1}: s={type(triple[0]).__name__}:{triple[0]}, p={type(triple[1]).__name__}:{triple[1]}, o={type(triple[2]).__name__}:{triple[2]}")
            
            vs = VitalSigns()
            
            # Use VitalSigns from_triples_list to convert all triples at once
            objects = vs.from_triples_list(triples)
            
            self.logger.debug(f"🔍 Converted {len(triples)} triples into {len(objects)} VitalSigns objects")
            return objects
            
        except Exception as e:
            import traceback
            self.logger.error(f"Error converting triples to VitalSigns objects: {e}")
            self.logger.error("FULL TRACEBACK:")
            self.logger.error(traceback.format_exc())
            return []
    
    
    async def delete_object(self, space_id: str, graph_id: str, uri: str) -> BackendOperationResult:
        """Delete object using SPARQL DELETE query."""
        try:
            # Get the proper space-specific graph URI
            if hasattr(self.backend, '_get_space_graph_uri'):
                full_graph_uri = self.backend._get_space_graph_uri(space_id, graph_id)
            else:
                full_graph_uri = graph_id
            
            delete_query = f"""
            DELETE {{
                GRAPH <{full_graph_uri}> {{
                    <{uri}> ?p ?o .
                }}
            }}
            WHERE {{
                GRAPH <{full_graph_uri}> {{
                    <{uri}> ?p ?o .
                }}
            }}
            """
            
            await self.backend.execute_sparql_update(space_id, delete_query)
            
            return BackendOperationResult(
                success=True,
                message=f"Successfully deleted object {uri}"
            )
            
        except Exception as e:
            self.logger.error(f"Error deleting object: {e}")
            return BackendOperationResult(
                success=False,
                message=f"Failed to delete object: {str(e)}",
                error=str(e)
            )
    
    async def execute_sparql_query(self, space_id: str, query: str) -> Dict[str, Any]:
        """Execute SPARQL query via backend."""
        sparql_result = await self.backend.execute_sparql_query(space_id, query)
        
        return sparql_result
    
    async def query_quads(self, space_id: str, query: str) -> List[tuple]:
        """Query quads via backend - delegates to backend's query_quads method."""
        return await self.backend.query_quads(space_id, query)
    
    async def execute_sparql_update(self, space_id: str, update_query: str):
        """Execute SPARQL update via backend.
        
        Returns:
            Result from backend - may be a DualWriteResult (truthy when success=True,
            with fuseki_success attribute) or bool.
        """
        try:
            result = await self.backend.execute_sparql_update(space_id, update_query)
            return result if result is not None else True
        except Exception as e:
            self.logger.error(f"Error executing SPARQL update: {e}")
            return False
    
    async def remove_rdf_quads_batch(self, space_id: str, quads: List[tuple]) -> int:
        """Remove RDF quads directly without SPARQL parsing."""
        try:
            # Delegate to backend's db_ops remove_rdf_quads_batch method
            return await self.backend.db_ops.remove_rdf_quads_batch(space_id, quads)
        except Exception as e:
            self.logger.error(f"Error removing quads batch: {e}")
            return 0
    
    
    async def validate_parent_connection(self, space_id: str, graph_id: str, 
                                       parent_uri: str, child_uri: str) -> bool:
        """Validate parent-child relationship exists."""
        try:
            # Use graph_id directly as graph URI (matching original system)
            full_graph_uri = graph_id
            
            ask_query = f"""
            ASK {{
                GRAPH <{full_graph_uri}> {{
                    ?edge a ?edgeType .
                    ?edge <http://vital.ai/ontology/vital-core#edgeSource> <{parent_uri}> .
                    ?edge <http://vital.ai/ontology/vital-core#edgeDestination> <{child_uri}> .
                }}
            }}
            """
            
            result = await self.backend.query_quads(space_id, ask_query)
            # query_quads returns a list of tuples, need to check if any results exist
            return len(result) > 0 if isinstance(result, list) else result.get('boolean', False)
            
        except Exception as e:
            self.logger.error(f"Error validating parent connection: {e}")
            return False
    
    async def update_quads(self, space_id: str, graph_id: str, 
                          delete_quads: List[tuple], insert_quads: List[tuple]) -> bool:
        """
        Atomically update quads using proper transactional operations.
        
        Note: This is used by KGSlotUpdateProcessor. For direct slot updates,
        use the transactional pattern in _update_frame_slots_in_backend instead.
        """
        try:
            self.logger.debug(f"🔄 ATOMIC UPDATE: Starting update_quads for space {space_id}, graph {graph_id}")
            self.logger.debug(f"🔄 Delete quads: {len(delete_quads)}, Insert quads: {len(insert_quads)}")
            
            # Use backend's existing transactional methods
            # Delete operations first
            if delete_quads:
                success = await self.backend.remove_rdf_quads_batch(space_id, delete_quads)
                if not success:
                    raise Exception("Failed to delete quads")
                self.logger.debug(f"🔄 Deleted {len(delete_quads)} quads")
            
            # Insert operations second
            if insert_quads:
                success = await self.backend.add_rdf_quads_batch(space_id, insert_quads)
                if not success:
                    raise Exception("Failed to insert quads")
                self.logger.debug(f"🔄 Inserted {len(insert_quads)} quads")
            
            self.logger.debug("🔄 update_quads completed successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"🔄 update_quads failed: {e}")
            return False
    
    
    
    def _build_insert_query(self, space_id: str, graph_id: str, triples: List[tuple]) -> str:
        """Build SPARQL INSERT query from triples."""
        # Get the proper space-specific graph URI
        if hasattr(self.backend, '_get_space_graph_uri'):
            full_graph_uri = self.backend._get_space_graph_uri(space_id, graph_id)
        else:
            full_graph_uri = graph_id
        
        # Build INSERT DATA query
        insert_data = []
        for subject, predicate, obj in triples:
            # Format based on RDFLib object types or string validation
            from rdflib import URIRef, Literal
            from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
            
            # Subject (always a URI in RDF)
            if isinstance(subject, URIRef):
                subject_str = f"<{subject}>"
            else:
                subject_val = str(subject)
                if validate_rfc3986(subject_val, rule='URI'):
                    subject_str = f"<{subject_val}>"
                else:
                    subject_str = f"<{subject_val}>"  # Force as URI since subjects must be URIs
            
            # Predicate (always a URI in RDF)
            if isinstance(predicate, URIRef):
                predicate_str = f"<{predicate}>"
            else:
                predicate_val = str(predicate)
                if validate_rfc3986(predicate_val, rule='URI'):
                    predicate_str = f"<{predicate_val}>"
                else:
                    predicate_str = f"<{predicate_val}>"  # Force as URI since predicates must be URIs
            
            # Object (can be URI or Literal)
            if isinstance(obj, URIRef):
                obj_str = f"<{obj}>"
            elif isinstance(obj, Literal):
                obj_str = f'"{obj}"'
            else:
                obj_val = str(obj)
                if validate_rfc3986(obj_val, rule='URI'):
                    obj_str = f"<{obj_val}>"
                else:
                    obj_str = f'"{obj_val}"'
            
            insert_data.append(f"    {subject_str} {predicate_str} {obj_str} .")
        
        query = f"""
        INSERT DATA {{
            GRAPH <{full_graph_uri}> {{
{chr(10).join(insert_data)}
            }}
        }}
        """
        
        return query


def create_backend_adapter(backend_impl) -> KGBackendInterface:
    """Factory function to create appropriate backend adapter."""
    # Determine backend type and create appropriate adapter
    backend_type = type(backend_impl).__name__
    
    if 'FusekiPostgreSQL' in backend_type:
        return FusekiPostgreSQLBackendAdapter(backend_impl)
    else:
        # Default to Fuseki+PostgreSQL adapter
        return FusekiPostgreSQLBackendAdapter(backend_impl)
