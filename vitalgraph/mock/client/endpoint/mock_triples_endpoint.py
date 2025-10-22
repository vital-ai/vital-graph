"""
Mock implementation of TriplesEndpoint for testing with VitalSigns native functionality.

This implementation uses:
- Real pyoxigraph quad operations for all triple operations
- VitalSigns native functionality for JSON-LD to triple conversion
- SPARQL pattern matching for efficient triple queries
- No mock data generation - all operations use real pyoxigraph storage
"""

from typing import Dict, Any, Optional, List
from .mock_base_endpoint import MockBaseEndpoint
from vitalgraph.model.triples_model import (
    TripleListResponse, TripleOperationResponse
)
from vitalgraph.model.jsonld_model import JsonLdDocument


class MockTriplesEndpoint(MockBaseEndpoint):
    """Mock implementation of TriplesEndpoint with real quad operations."""
    
    def list_triples(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, 
                    subject: Optional[str] = None, predicate: Optional[str] = None, 
                    object: Optional[str] = None, object_filter: Optional[str] = None) -> TripleListResponse:
        """
        List/Search triples with optional filtering using pyoxigraph pattern matching.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            page_size: Number of triples per page
            offset: Offset for pagination
            subject: Optional subject filter
            predicate: Optional predicate filter
            object: Optional object filter
            object_filter: Optional object filter term
            
        Returns:
            TripleListResponse with real pyoxigraph results
        """
        self._log_method_call("list_triples", space_id=space_id, graph_id=graph_id, subject=subject, 
                             predicate=predicate, object=object, object_filter=object_filter, 
                             page_size=page_size, offset=offset)
        
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id) if self.space_manager else None
            if not space:
                # Return empty JSON-LD document for nonexistent space
                empty_jsonld = {
                    "@context": {},
                    "@graph": []
                }
                return TripleListResponse(
                    data=JsonLdDocument(**empty_jsonld),
                    total_count=0,
                    page_size=page_size,
                    offset=offset
                )
            
            # Use pyoxigraph pattern matching
            quads = space.query_quads_pattern(
                subject=subject,
                predicate=predicate,
                object_value=object,
                graph_id=graph_id
            )
            
            # Apply pagination
            total_count = len(quads)
            self.logger.info(f"Retrieved {total_count} quads from pyoxigraph")
            if offset:
                quads = quads[offset:]
            if page_size:
                quads = quads[:page_size]
            
            self.logger.info(f"After pagination: {len(quads)} quads")
            
            # Convert quads back to VitalSigns objects, then to JSON-LD using VitalSigns
            if quads:
                # Convert quads to triples (remove graph_id and clean URIs from pyoxigraph)
                triples = []
                for q in quads:
                    # Strip angle brackets from pyoxigraph URIs
                    clean_subject = q["subject"].strip('<>') if isinstance(q["subject"], str) else q["subject"]
                    clean_predicate = q["predicate"].strip('<>') if isinstance(q["predicate"], str) else q["predicate"]
                    clean_object = q["object"].strip('<>') if isinstance(q["object"], str) and q["object"].startswith('<') else q["object"]
                    
                    triples.append((clean_subject, clean_predicate, clean_object))
                
                # Create JSON-LD structure directly from cleaned triples
                self.logger.info(f"Converting {len(triples)} triples to JSON-LD")
                if triples:
                    self.logger.info(f"First triple: {triples[0]}")
                try:
                    jsonld_data = self._triples_to_jsonld_document(triples)
                    self.logger.info(f"JSON-LD result has {len(jsonld_data.get('@graph', []))} entities")
                except Exception as e:
                    self.logger.error(f"Exception in _triples_to_jsonld_document: {e}")
                    # Fallback to empty result
                    from ai_haley_kg_domain.model.KGEntity import KGEntity
                    jsonld_data = KGEntity.to_jsonld_list([])
            else:
                # Empty result - use a default VitalSigns class
                from ai_haley_kg_domain.model.KGEntity import KGEntity
                jsonld_data = KGEntity.to_jsonld_list([])
            
            return TripleListResponse(
                data=JsonLdDocument(**jsonld_data),
                total_count=total_count,
                page_size=page_size,
                offset=offset
            )
                
        except Exception as e:
            self.logger.error(f"Error listing triples: {e}")
            # Return empty JSON-LD document
            empty_jsonld = {
                "@context": {},
                "@graph": []
            }
            return TripleListResponse(
                data=JsonLdDocument(**empty_jsonld),
                total_count=0,
                page_size=page_size,
                offset=offset
            )
    
    
    def add_triples(self, space_id: str, graph_id: str, document: JsonLdDocument) -> TripleOperationResponse:
        """
        Add triples to a graph using VitalSigns native functionality and pyoxigraph.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JsonLdDocument containing objects to convert to triples
            
        Returns:
            TripleOperationResponse with real operation results
        """
        self._log_method_call("add_triples", space_id=space_id, graph_id=graph_id, document=document)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id) if self.space_manager else None
            if not space:
                return TripleOperationResponse(
                    success=False,
                    message=f"Space {space_id} not found"
                )
            
            # Convert JSON-LD document to VitalSigns objects using the helper method
            document_dict = document.model_dump(by_alias=True)
            objects = self._jsonld_to_vitalsigns_objects(document_dict)
            
            if not objects:
                return TripleOperationResponse(
                    success=True,
                    message="No valid objects to add"
                )
            
            # Store objects in pyoxigraph (which converts them to triples)
            stored_count = self._store_vitalsigns_objects_in_pyoxigraph(space, objects, graph_id)
            
            return TripleOperationResponse(
                success=True,
                message=f"Successfully added triples for {stored_count} objects"
            )
                
        except Exception as e:
            self.logger.error(f"Error adding triples: {e}")
            return TripleOperationResponse(
                success=False,
                message=str(e)
            )
    
    def delete_triples(self, space_id: str, graph_id: str, 
                      subject: Optional[str] = None, predicate: Optional[str] = None, 
                      object: Optional[str] = None) -> TripleOperationResponse:
        """
        Delete triples from a graph using pyoxigraph pattern matching.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            subject: Optional subject filter
            
        Returns:
            TripleOperationResponse with real deletion results
        """
        self._log_method_call("delete_triples", space_id=space_id, graph_id=graph_id, 
                             subject=subject, predicate=predicate, object=object)
        
        try:
            space = self.space_manager.get_space(space_id) if self.space_manager else None
            if not space:
                return TripleOperationResponse(
                    success=False,
                    message=f"Space {space_id} not found"
                )
            deleted_count = 0
            
            # Count total quads before deletion
            all_quads_before = space.query_quads_pattern(graph_id=graph_id)
            total_before = len(all_quads_before)
            self.logger.info(f"Total quads in graph before deletion: {total_before}")
            
            # Delete by pattern - find matching quads first
            matching_quads = space.query_quads_pattern(
                subject=subject,
                predicate=predicate,
                object_value=object,
                graph_id=graph_id
            )
            
            self.logger.info(f"Found {len(matching_quads)} matching quads to delete")
            
            for quad in matching_quads:
                try:
                    # Clean URIs by removing angle brackets if present
                    clean_subject = quad["subject"].strip('<>') if isinstance(quad["subject"], str) else quad["subject"]
                    clean_predicate = quad["predicate"].strip('<>') if isinstance(quad["predicate"], str) else quad["predicate"]
                    clean_object = quad["object"].strip('<>') if isinstance(quad["object"], str) else quad["object"]
                    
                    # Debug logging
                    self.logger.info(f"Attempting to delete quad: {clean_subject} {clean_predicate} {clean_object}")
                    
                    space.remove_quad(
                        subject=clean_subject,
                        predicate=clean_predicate,
                        object_value=clean_object,
                        graph_id=graph_id
                    )
                    deleted_count += 1
                    self.logger.info(f"Successfully deleted quad, count now: {deleted_count}")
                except Exception as e:
                    self.logger.error(f"Failed to delete quad: {e}")
                    self.logger.error(f"Quad details: subject='{clean_subject}', predicate='{clean_predicate}', object='{clean_object}', graph='{graph_id}'")
            
            # Count total quads after deletion
            all_quads_after = space.query_quads_pattern(graph_id=graph_id)
            total_after = len(all_quads_after)
            actual_deleted = total_before - total_after
            self.logger.info(f"Total quads in graph after deletion: {total_after}")
            self.logger.info(f"Expected to delete {len(matching_quads)}, actually deleted {actual_deleted}")
            
            return TripleOperationResponse(
                success=True,
                message=f"Successfully deleted {actual_deleted} triples",
                deleted_count=actual_deleted
            )
                
        except Exception as e:
            self.logger.error(f"Error deleting triples: {e}")
            return TripleOperationResponse(
                success=False,
                message=str(e)
            )
