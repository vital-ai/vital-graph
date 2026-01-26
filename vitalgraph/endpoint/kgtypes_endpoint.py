"""KG Types Endpoint for VitalGraph

Implements REST API endpoints for KG type management operations using JSON-LD 1.1 format.
Based on the planned API specification in docs/planned_rest_api_endpoints.md
"""

from typing import Dict, Any, Optional, List, Union
from fastapi import APIRouter, HTTPException, Depends, Query, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import logging
from datetime import datetime

from pyld import jsonld
import vital_ai_vitalsigns as vitalsigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGType import KGType

# Legacy import removed - now using kg_impl processors directly
from ..kg_impl.kgtypes_create_impl import KGTypesCreateProcessor
from ..kg_impl.kgtypes_read_impl import KGTypesReadProcessor
from ..kg_impl.kgtypes_update_impl import KGTypesUpdateProcessor
from ..kg_impl.kgtypes_delete_impl import KGTypesDeleteProcessor
from ..kg_impl.kg_backend_utils import create_backend_adapter
from ..model.jsonld_model import JsonLdDocument, JsonLdObject, JsonLdRequest
from ..model.kgtypes_model import KGTypeFilter
from vitalgraph.model.kgtypes_model import (
    KGTypeListResponse, KGTypeCreateResponse, KGTypeUpdateResponse, KGTypeDeleteResponse,
    KGTypeCreateRequest, KGTypeUpdateRequest, KGTypeGetResponse, KGTypeBatchDeleteRequest
)


class KGTypesEndpoint:
    """KG Types endpoint handler."""
    
    def __init__(self, space_manager, auth_dependency):
        self.space_manager = space_manager
        self.auth_dependency = auth_dependency
        self.logger = logging.getLogger(f"{__name__}.KGTypesEndpoint")
        self.router = APIRouter()
        
        # Initialize KGType services with new atomic processors
        self.kgtypes_create_processor = KGTypesCreateProcessor()
        self.kgtypes_read_processor = KGTypesReadProcessor()
        self.kgtypes_update_processor = KGTypesUpdateProcessor()
        self.kgtypes_delete_processor = KGTypesDeleteProcessor()
        
        self._setup_routes()
    
    
    def _jsonld_to_vitalsigns_objects(self, data: JsonLdRequest) -> List[GraphObject]:
        """
        Convert Pydantic JSON-LD models to VitalSigns KGType objects using VitalSigns 0.1.40 JSON-LD API.
        
        Args:
            data: JsonLdRequest (discriminated union of JsonLdObject or JsonLdDocument)
            
        Returns:
            List[GraphObject]: List of VitalSigns KGType objects
        """
        try:
            # Use VitalSigns 0.1.40 native JSON-LD conversion methods
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            
            # Convert Pydantic model to JSON-LD dictionary
            if isinstance(data, JsonLdObject):
                # Single object - use from_jsonld()
                jsonld_dict = data.model_dump(by_alias=True)
                graph_object = GraphObject.from_jsonld(jsonld_dict)
                graph_objects = [graph_object] if graph_object else []
            elif isinstance(data, JsonLdDocument):
                # Document with @graph array - use from_jsonld_list()
                jsonld_dict = data.model_dump(by_alias=True)
                graph_objects = GraphObject.from_jsonld_list(jsonld_dict)
            else:
                raise ValueError(f"Unsupported data type: {type(data)}")
            
            # Filter to ensure we only have valid GraphObject instances
            kgtype_objects = []
            for obj in graph_objects:
                if isinstance(obj, GraphObject):
                    kgtype_objects.append(obj)
            
            self.logger.info(f"Converted {len(kgtype_objects)} objects from JSON-LD using VitalSigns 0.1.40 native methods")
            return kgtype_objects
            
        except Exception as e:
            self.logger.error(f"Error converting JSON-LD to VitalSigns objects: {e}")
            raise
    
    def _validate_operation_compatibility(self, operation: str, format_type: str, object_count: int):
        """Validate that operation type matches data format."""
        if operation == "single_update" and format_type == "multiple":
            raise ValueError("Cannot use JsonLdDocument for single object update operations")
        if operation == "batch_create" and format_type == "single":
            raise ValueError("Cannot use JsonLdObject for batch operations")
        if format_type == "single" and object_count > 1:
            raise ValueError("JsonLdObject format detected but multiple objects provided")
    
    def _setup_routes(self):
        """Setup KG types routes."""
        
        # GET /api/graphs/kgtypes - List KG types with pagination/filtering
        @self.router.get(
            "/kgtypes",
            response_model=Union[KGTypeGetResponse, KGTypeListResponse],
            tags=["KG Types"],
            summary="List KG Types",
            description="List KG types in graph with pagination and filtering options. Returns KGTypeGetResponse for single URI, KGTypeListResponse for lists/searches."
        )
        async def list_kgtypes(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            page_size: int = Query(10, ge=1, le=100, description="Number of types per page"),
            offset: int = Query(0, ge=0, description="Number of types to skip"),
            search: Optional[str] = Query(None, description="Search text to filter types"),
            uri: Optional[str] = Query(None, description="Get specific type by URI"),
            uri_list: Optional[str] = Query(None, description="Get multiple types by comma-separated URI list"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            # Handle specific URI request
            if uri:
                return await self._get_kgtype_by_uri(space_id, graph_id, uri, current_user)
            
            # Handle multiple URI request
            elif uri_list:
                return await self._get_kgtypes_by_uris(space_id, graph_id, uri_list, current_user)
            
            # Handle regular list/search request
            else:
                return await self._list_kgtypes(
                    space_id, graph_id, page_size, offset, 
                    filter=None, current_user=current_user, 
                    search=search
                )
        
        # POST /api/graphs/kgtypes - Create new KG types
        @self.router.post(
            "/kgtypes",
            response_model=KGTypeCreateResponse,
            tags=["KG Types"],
            summary="Create KG Types",
            description="Create new KG types in the specified graph"
        )
        async def create_kgtypes(
            request: KGTypeCreateRequest = Body(..., description="KGType creation request with Union data support"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            return await self._create_kgtypes(request.space_id, request.graph_id, request.data, current_user)
        
        # PUT /api/graphs/kgtypes - Update KG types
        @self.router.put(
            "/kgtypes",
            response_model=KGTypeUpdateResponse,
            tags=["KG Types"],
            summary="Update KG Types",
            description="Update existing KG types in the specified graph"
        )
        async def update_kgtypes(
            request: KGTypeUpdateRequest = Body(..., description="KGType update request with Union data support"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            return await self._update_kgtypes(request.space_id, request.graph_id, request.data, current_user)
        
        # DELETE /api/graphs/kgtypes - Delete KG types
        @self.router.delete(
            "/kgtypes",
            response_model=KGTypeDeleteResponse,
            tags=["KG Types"],
            summary="Delete KG Types",
            description="Delete KG types from the specified graph"
        )
        async def delete_kgtypes(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            uri: Optional[str] = Query(None, description="Delete specific type by URI"),
            uri_list: Optional[List[str]] = Query(None, description="Delete multiple types by URI list"),
            request: Optional[KGTypeBatchDeleteRequest] = Body(None, description="Batch delete request with Union data support"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            return await self._delete_kgtypes(space_id, graph_id, uri, uri_list, request.data if request else None, current_user)
    
    async def _list_kgtypes(
        self,
        space_id: str,
        graph_id: str,
        page_size: int,
        offset: int,
        filter: Optional[str] = None,
        current_user: Dict = None,
        search: Optional[str] = None
    ) -> KGTypeListResponse:
        """List KG types with filtering and pagination using JSON-LD format."""
        
        try:
            self.logger.info(f"Listing KG types in space '{space_id}', graph '{graph_id}' for user '{current_user.get('username', 'unknown')}'")
            
            # Get complete JSON-LD document from new atomic processor
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                raise HTTPException(status_code=500, detail=f"Space {space_id} not available - server configuration error")
            
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                raise HTTPException(status_code=500, detail="Backend implementation not available")
            
            backend_adapter = create_backend_adapter(backend)
            
            # Apply search filter if provided (prioritize search over filter for HTTP routes)
            search_filter = search if search else filter
            triples, total_count = await self.kgtypes_read_processor.list_kgtypes(
                backend=backend_adapter,
                space_id=space_id,
                graph_id=graph_id,
                page_size=page_size,
                offset=offset,
                search=search_filter
            )
            
            self.logger.info(f"🔍 LIST: Received {len(triples)} RDFLib triples, total_count: {total_count}")
            
            # Handle empty list case
            if not triples or len(triples) == 0:
                # Create empty JSON-LD document for empty results
                final_jsonld = {
                    "@context": {"@vocab": "http://vital.ai/ontology/"},
                    "@graph": []
                }
                jsonld_doc = JsonLdDocument(**final_jsonld)
            else:
                # Convert RDFLib triples to VitalSigns GraphObjects
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                graph_objects = GraphObject.from_triples_list(triples)
                
                # Check if single or multiple objects
                if len(graph_objects) == 1:
                    # Single object - use JsonLdObject
                    jsonld_dict = graph_objects[0].to_jsonld()
                    # Ensure @type field is present
                    if '@type' not in jsonld_dict and 'type' in jsonld_dict:
                        jsonld_dict['@type'] = jsonld_dict.pop('type')
                    jsonld_doc = JsonLdObject(**jsonld_dict)
                else:
                    # Multiple objects - use JsonLdDocument
                    final_jsonld = GraphObject.to_jsonld_list(graph_objects)
                    
                    # Ensure @type fields are present in @graph objects
                    if '@graph' in final_jsonld:
                        for obj in final_jsonld['@graph']:
                            if '@type' not in obj and 'type' in obj:
                                obj['@type'] = obj.pop('type')
                    
                    jsonld_doc = JsonLdDocument(**final_jsonld)
            
            return KGTypeListResponse(
                success=True,
                message=f"Successfully listed {total_count} KGTypes",
                data=jsonld_doc,
                total_count=total_count,
                page_size=page_size,
                offset=offset,
                pagination={
                    "page": (offset // page_size) + 1,
                    "limit": page_size,
                    "total": total_count,
                    "pages": (total_count + page_size - 1) // page_size
                },
                meta={
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "version": "1.0",
                    "format": "JSON-LD 1.1"
                }
            )
        
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error listing KG types: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error listing KG types: {str(e)}"
            )
    
    async def _get_kgtype_by_uri(
        self,
        space_id: str,
        graph_id: str,
        uri: str,
        current_user: Dict
    ) -> KGTypeGetResponse:
        """Get a specific KGType by URI."""
        try:
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                raise HTTPException(status_code=500, detail=f"Space {space_id} not available - server configuration error")
            
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                raise HTTPException(status_code=500, detail="Backend implementation not available")
            
            backend_adapter = create_backend_adapter(backend)
            kgtype_object = await self.kgtypes_read_processor.get_kgtype_by_uri(
                backend=backend_adapter,
                space_id=space_id,
                graph_id=graph_id,
                kgtype_uri=uri
            )
            
            if not kgtype_object:
                self.logger.warning(f"🔍 GET: KGType not found: {uri}")
                # Return empty response instead of 404 - service should never return 404
                return KGTypeGetResponse(
                    success=True,
                    message=f"KGType with URI '{uri}' not found",
                    data=None
                )
            
            # Convert VitalSigns GraphObject to JsonLdObject
            jsonld_dict = kgtype_object.to_jsonld()
            
            # Fix @type field - convert array to string if needed for VitalSigns compatibility
            if '@type' in jsonld_dict and isinstance(jsonld_dict['@type'], list) and len(jsonld_dict['@type']) == 1:
                jsonld_dict['@type'] = jsonld_dict['@type'][0]
            
            # Create JsonLdObject that preserves @type field
            jsonld_obj = JsonLdObject(**jsonld_dict)
            
            return KGTypeGetResponse(
                success=True,
                message=f"Successfully retrieved KGType: {uri}",
                data=jsonld_obj
            )
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error getting KGType by URI: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error getting KGType: {str(e)}"
            )
    
    async def _get_kgtypes_by_uris(
        self,
        space_id: str,
        graph_id: str,
        uri_list: str,
        current_user: Dict
    ) -> KGTypeListResponse:
        """Get multiple KGTypes by URI list."""
        try:
            uris = [u.strip() for u in uri_list.split(',') if u.strip()]
            
            # Get complete JSON-LD document from new atomic processor
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                raise HTTPException(status_code=500, detail=f"Space {space_id} not available - server configuration error")
            
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                raise HTTPException(status_code=500, detail="Backend implementation not available")
            
            backend_adapter = create_backend_adapter(backend)
            kgtype_objects = await self.kgtypes_read_processor.get_kgtypes_by_uris(
                backend=backend_adapter,
                space_id=space_id,
                graph_id=graph_id,
                kgtype_uris=uris
            )
            
            self.logger.info(f"🔍 GET_BY_URIS: Received {len(kgtype_objects)} KGType GraphObjects for {len(uris)} URIs")
            
            # Convert VitalSigns GraphObjects to JsonLdDocument
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            final_jsonld = GraphObject.to_jsonld_list(kgtype_objects)
            
            # Ensure @type fields are present in @graph objects
            if '@graph' in final_jsonld:
                for obj in final_jsonld['@graph']:
                    if '@type' not in obj and 'type' in obj:
                        obj['@type'] = obj.pop('type')
            
            jsonld_doc = JsonLdDocument(**final_jsonld)
            
            # Get count from the converted objects
            object_count = len(graph_objects)
            
            return KGTypeListResponse(
                success=True,
                message=f"Successfully retrieved {object_count} KGTypes",
                data=jsonld_doc,
                total_count=object_count,
                page_size=object_count,
                offset=0,
                pagination={
                    "page": 1,
                    "limit": object_count,
                    "total": object_count,
                    "pages": 1
                },
                meta={
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "version": "1.0",
                    "format": "JSON-LD 1.1"
                }
            )
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error getting KGTypes by URI list: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error getting KGTypes: {str(e)}"
            )
    
    async def _create_kgtypes(
        self,
        space_id: str,
        graph_id: str,
        data: JsonLdRequest,
        current_user: Dict
    ) -> KGTypeCreateResponse:
        """Create KG types from JSON-LD document or object using proper VitalGraph patterns."""
        
        try:
            self.logger.info(f"Creating KG types in space '{space_id}', graph '{graph_id}' for user '{current_user.get('username', 'unknown')}'")
            
            # Validate space manager (same as triples endpoint)
            if self.space_manager is None:
                raise HTTPException(
                    status_code=500,
                    detail="Space manager not available"
                )
            
            # Validate space exists (same as triples endpoint)
            if not self.space_manager.has_space(space_id):
                raise HTTPException(
                    status_code=404,
                    detail=f"Space '{space_id}' not found"
                )
            
            # Validate input data
            if isinstance(data, JsonLdObject):
                if not data.id or not data.type:
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid request: JsonLdObject must have @id and @type"
                    )
            elif isinstance(data, JsonLdDocument):
                if not data.graph or len(data.graph) == 0:
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid request: JsonLdDocument must have non-empty @graph"
                    )
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid data type: expected JsonLdObject or JsonLdDocument"
                )
            
            # Always use batch operations for consistency and to avoid manual JSON-LD document creation
            try:
                # Use new atomic KGTypes CREATE processor
                space_record = self.space_manager.get_space(space_id)
                if not space_record:
                    raise HTTPException(status_code=404, detail=f"Space {space_id} not found")
                
                space_impl = space_record.space_impl
                backend = space_impl.get_db_space_impl()
                if not backend:
                    raise HTTPException(status_code=500, detail="Backend implementation not available")
                
                backend_adapter = create_backend_adapter(backend)
                # Convert JSON-LD to VitalSigns objects for the processor
                kgtype_objects = self._jsonld_to_vitalsigns_objects(data)
                
                # Handle single vs multiple objects appropriately
                if len(kgtype_objects) == 1:
                    # Single GraphObject - use single create method
                    created_uri = await self.kgtypes_create_processor.create_kgtype(
                        backend=backend_adapter,
                        space_id=space_id,
                        graph_id=graph_id,
                        kgtype_object=kgtype_objects[0]
                    )
                    created_uris = [created_uri]
                else:
                    # Multiple GraphObjects - use batch create method
                    created_uris = await self.kgtypes_create_processor.create_kgtypes_batch(
                        backend=backend_adapter,
                        space_id=space_id,
                        graph_id=graph_id,
                        kgtype_objects=kgtype_objects
                    )
                
                created_count = len(created_uris)
                self.logger.info(f"Created {created_count} KGTypes: {created_uris}")
                
                return KGTypeCreateResponse(
                    success=True,
                    message=f"Successfully created {created_count} KG type definitions in graph '{graph_id}' in space '{space_id}'",
                    created_count=created_count,
                    created_uris=created_uris
                )
                
            except Exception as e:
                self.logger.error(f"Create operation failed: {e}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to create KGTypes: {str(e)}"
                )
        
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error creating KG types: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error creating KG types: {str(e)}"
            )
    
    async def _update_kgtypes(
        self,
        space_id: str,
        graph_id: str,
        data: JsonLdRequest,
        current_user: Dict
    ) -> KGTypeUpdateResponse:
        """Update KG types from JSON-LD document or object using proper VitalGraph patterns."""
        
        try:
            self.logger.info(f"Updating KG types in space '{space_id}', graph '{graph_id}' for user '{current_user.get('username', 'unknown')}'")
            
            # Validate space manager (same as triples endpoint)
            if self.space_manager is None:
                raise HTTPException(
                    status_code=500,
                    detail="Space manager not available"
                )
            
            # Validate space exists (same as triples endpoint)
            if not self.space_manager.has_space(space_id):
                raise HTTPException(
                    status_code=404,
                    detail=f"Space '{space_id}' not found"
                )
            
            # Validate input data
            if isinstance(data, JsonLdObject):
                if not data.id or not data.type:
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid request: JsonLdObject must have @id and @type"
                    )
            elif isinstance(data, JsonLdDocument):
                if not data.graph or len(data.graph) == 0:
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid request: JsonLdDocument must have non-empty @graph"
                    )
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid data type: expected JsonLdObject or JsonLdDocument"
                )
            
            # Always use batch operations for consistency and to avoid manual JSON-LD document creation
            try:
                # Use new atomic KGTypes UPDATE processor
                space_record = self.space_manager.get_space(space_id)
                if not space_record:
                    raise HTTPException(status_code=404, detail=f"Space {space_id} not found")
                
                space_impl = space_record.space_impl
                backend = space_impl.get_db_space_impl()
                if not backend:
                    raise HTTPException(status_code=500, detail="Backend implementation not available")
                
                backend_adapter = create_backend_adapter(backend)
                
                # Convert JSON-LD to VitalSigns objects using VitalSigns utilities
                kgtype_objects = self._jsonld_to_vitalsigns_objects(data)
                
                # Prepare kgtype_updates dict mapping URI to GraphObject list
                kgtype_updates = {}
                for kgtype_obj in kgtype_objects:
                    uri = str(kgtype_obj.URI)
                    kgtype_updates[uri] = [kgtype_obj]
                
                updated_uris = await self.kgtypes_update_processor.update_kgtypes_batch(
                    backend=backend_adapter,
                    space_id=space_id,
                    graph_id=graph_id,
                    kgtype_updates=kgtype_updates
                )
                
                updated_count = len(updated_uris)
                self.logger.info(f"Updated {updated_count} KGTypes: {updated_uris}")
                
                # Return the first URI as the primary updated URI
                primary_uri = updated_uris[0] if updated_uris else ""
                return KGTypeUpdateResponse(
                    success=True,
                    message=f"Successfully updated {updated_count} KG type definitions in graph '{graph_id}' in space '{space_id}'",
                    updated_count=updated_count,
                    updated_uris=updated_uris
                )
                
            except Exception as e:
                self.logger.error(f"Update operation failed: {e}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to update KGTypes: {str(e)}"
                )
        
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error updating KG types: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error updating KG types: {str(e)}"
            )
    
    async def _delete_kgtypes(
        self,
        space_id: str,
        graph_id: str,
        uri: Optional[str],
        uri_list: Optional[str],
        document: Optional[JsonLdDocument],
        current_user: Dict
    ) -> KGTypeDeleteResponse:
        """Delete KG types by URI, URI list, or JSON-LD document using proper VitalGraph patterns."""
        
        try:
            self.logger.info(f"Deleting KG types from space '{space_id}', graph '{graph_id}' for user '{current_user.get('username', 'unknown')}'")
            
            # Validate space manager (same as triples endpoint)
            if self.space_manager is None:
                raise HTTPException(
                    status_code=500,
                    detail="Space manager not available"
                )
            
            # Validate space exists (same as triples endpoint)
            if not self.space_manager.has_space(space_id):
                raise HTTPException(
                    status_code=404,
                    detail=f"Space '{space_id}' not found"
                )
            
            # Validate that at least one deletion method is provided
            if not uri and not uri_list and not (document and document.graph):
                raise HTTPException(
                    status_code=400,
                    detail="Invalid request: must provide uri, uri_list, or document with @graph"
                )
            
            deleted_count = 0
            deleted_uris = []
            delete_method = ""
            
            try:
                if uri:
                    # Delete single KGType by URI
                    # Ensure URI is a string (handle CombinedProperty from VitalSigns)
                    uri_str = str(uri) if uri else uri
                    space_record = self.space_manager.get_space(space_id)
                    if not space_record:
                        raise HTTPException(status_code=404, detail=f"Space {space_id} not found")
                    
                    space_impl = space_record.space_impl
                    backend = space_impl.get_db_space_impl()
                    if not backend:
                        raise HTTPException(status_code=500, detail="Backend implementation not available")
                    
                    backend_adapter = create_backend_adapter(backend)
                    success = await self.kgtypes_delete_processor.delete_kgtype(
                        backend=backend_adapter,
                        space_id=space_id,
                        graph_id=graph_id,
                        kgtype_uri=uri_str
                    )
                    if success:
                        deleted_count = 1
                        deleted_uris = [uri_str]
                        self.logger.info(f"Deleted KGType: {uri_str}")
                    delete_method = f"URI '{uri_str}'"
                        
                elif uri_list:
                    # Delete multiple KGTypes by URI list
                    # Handle both string (comma-separated) and list formats
                    if isinstance(uri_list, str):
                        uris = [u.strip() for u in uri_list.split(',') if u.strip()]
                    elif isinstance(uri_list, list):
                        uris = [str(u).strip() for u in uri_list if str(u).strip()]
                    else:
                        raise HTTPException(
                            status_code=400,
                            detail="Invalid URI list format: expected string or list"
                        )
                    
                    if not uris:
                        raise HTTPException(
                            status_code=400,
                            detail="Invalid URI list: no valid URIs found"
                        )
                    
                    space_record = self.space_manager.get_space(space_id)
                    if not space_record:
                        raise HTTPException(status_code=404, detail=f"Space {space_id} not found")
                    
                    space_impl = space_record.space_impl
                    backend = space_impl.get_db_space_impl()
                    if not backend:
                        raise HTTPException(status_code=500, detail="Backend implementation not available")
                    
                    backend_adapter = create_backend_adapter(backend)
                    deleted_count = await self.kgtypes_delete_processor.delete_kgtypes_batch(
                        backend=backend_adapter,
                        space_id=space_id,
                        graph_id=graph_id,
                        kgtype_uris=uris
                    )
                    deleted_uris = uris[:deleted_count] if deleted_count > 0 else []
                    delete_method = f"URI list with {len(uris)} URIs"
                    
                elif document and document.graph:
                    # Delete KGTypes specified in JSON-LD document
                    uris_to_delete = []
                    for kgtype_obj in document.graph:
                        kgtype_uri = kgtype_obj.get('@id') or kgtype_obj.get('URI')
                        if kgtype_uri:
                            uris_to_delete.append(kgtype_uri)
                    
                    if not uris_to_delete:
                        raise HTTPException(
                            status_code=400,
                            detail="Invalid document: no valid URIs found in @graph objects"
                        )
                    
                    space_record = self.space_manager.get_space(space_id)
                    if not space_record:
                        raise HTTPException(status_code=404, detail=f"Space {space_id} not found")
                    
                    space_impl = space_record.space_impl
                    backend = space_impl.get_db_space_impl()
                    if not backend:
                        raise HTTPException(status_code=500, detail="Backend implementation not available")
                    
                    backend_adapter = create_backend_adapter(backend)
                    deleted_count = await self.kgtypes_delete_processor.delete_kgtypes_batch(
                        backend=backend_adapter,
                        space_id=space_id,
                        graph_id=graph_id,
                        kgtype_uris=uris_to_delete
                    )
                    deleted_uris = uris_to_delete[:deleted_count] if deleted_count > 0 else []
                    delete_method = f"JSON-LD document with {len(uris_to_delete)} type definitions"
                
                # Ensure all URIs are strings (handle CombinedProperty from VitalSigns)
                deleted_uris_str = [str(u) for u in deleted_uris] if deleted_uris else []
                
                self.logger.debug(f"Delete response - deleted_uris type: {type(deleted_uris)}, deleted_uris_str type: {type(deleted_uris_str)}")
                self.logger.debug(f"Delete response - deleted_uris: {deleted_uris}, deleted_uris_str: {deleted_uris_str}")
                
                return KGTypeDeleteResponse(
                    success=True,
                    message=f"Successfully deleted {deleted_count} KG types via {delete_method} from graph '{graph_id}' in space '{space_id}'",
                    deleted_count=deleted_count,
                    deleted_uris=deleted_uris_str
                )
                
            except Exception as e:
                # Handle service-level errors
                if "not found" in str(e).lower():
                    raise HTTPException(
                        status_code=404,
                        detail=f"One or more KGTypes not found: {str(e)}"
                    )
                else:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Failed to delete KGTypes: {str(e)}"
                    )
        
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error deleting KG types: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error deleting KG types: {str(e)}"
            )


def create_kgtypes_router(space_manager, auth_dependency) -> APIRouter:
    """Create and return the KG types router."""
    endpoint = KGTypesEndpoint(space_manager, auth_dependency)
    return endpoint.router
