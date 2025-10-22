"""
Implementation Utilities for VitalGraph

This module provides reusable utility functions that can be shared across
KGType, KGEntity, KGFrame, and general object implementations. It handles JSON-LD
processing, GraphObject conversion, transaction management, and conflict detection
without containing any direct SQL code.
"""

import logging
from typing import List, Tuple, Optional, Dict, Any, Callable
from pyld import jsonld
from rdflib import Graph, URIRef
import json

# VitalSigns imports
from vital_ai_vitalsigns.vitalsigns import VitalSigns



class ImplValidationError(Exception):
    """Base class for implementation validation errors."""
    pass


class ImplConflictError(Exception):
    """Raised when resource conflicts occur."""
    pass






async def check_subject_uri_conflicts(space_manager, space_id: str, subject_uris: List[str]) -> List[str]:
    """
    Check for existing objects with same subject URIs using db_objects layer.
    
    Args:
        space_manager: Space manager instance
        space_id: Space identifier
        subject_uris: List of subject URIs to check
        
    Returns:
        List of URIs that already exist in the database
        
    Raises:
        ImplValidationError: If database operation fails
    """
    logger = logging.getLogger(__name__)
    
    try:
        # Get space implementation
        space_record = space_manager.get_space(space_id)
        if not space_record:
            raise ImplValidationError(f"Space '{space_id}' not found")
        
        space_impl = space_record.space_impl
        db_space_impl = space_impl.get_db_space_impl()
        if not db_space_impl:
            raise ImplValidationError(f"Database implementation not available for space '{space_id}'")
        
        # Use db_objects layer for optimized conflict detection
        existing_uris = await db_space_impl.db_objects.get_existing_object_uris(space_id, subject_uris)
        
        logger.debug(f"Found {len(existing_uris)} existing URIs out of {len(subject_uris)} checked")
        return existing_uris
        
    except Exception as e:
        raise ImplValidationError(f"Failed to check URI conflicts: {e}")


async def get_existing_quads_for_uris(space_manager, space_id: str, graph_id: str, subject_uris: List[str]) -> List[Tuple]:
    """
    Get existing quads for update/delete operations using db_objects layer.
    
    Args:
        space_manager: Space manager instance
        space_id: Space identifier
        graph_id: Graph identifier
        subject_uris: List of subject URIs
        
    Returns:
        List of tuples (subject, predicate, object, graph) as RDFLib Identifiers
        
    Raises:
        ImplValidationError: If database operation fails
    """
    logger = logging.getLogger(__name__)
    
    try:
        # Get space implementation
        space_record = space_manager.get_space(space_id)
        if not space_record:
            raise ImplValidationError(f"Space '{space_id}' not found")
        
        space_impl = space_record.space_impl
        db_space_impl = space_impl.get_db_space_impl()
        if not db_space_impl:
            raise ImplValidationError(f"Database implementation not available for space '{space_id}'")
        
        # Use db_objects layer for optimized quad retrieval
        quads = await db_space_impl.db_objects.get_objects_by_uris_batch(space_id, subject_uris, graph_id)
        
        logger.debug(f"Retrieved {len(quads)} quads for {len(subject_uris)} objects")
        return quads
        
    except Exception as e:
        raise ImplValidationError(f"Failed to retrieve existing quads: {e}")


async def execute_with_transaction(space_manager, space_id: str, operation_func, *args, **kwargs):
    """
    Execute operations within a transaction with proper error handling.
    
    Args:
        space_manager: Space manager instance
        space_id: Space identifier
        operation_func: Async function to execute within transaction
        *args, **kwargs: Arguments to pass to operation_func
        
    Returns:
        Result from operation_func
        
    Raises:
        ImplValidationError: If transaction setup fails
        ImplConflictError: If operation conflicts occur
    """
    logger = logging.getLogger(__name__)
    
    try:
        # Get space implementation
        space_record = space_manager.get_space(space_id)
        if not space_record:
            raise ImplValidationError(f"Space '{space_id}' not found")
        
        space_impl = space_record.space_impl
        db_space_impl = space_impl.get_db_space_impl()
        if not db_space_impl:
            raise ImplValidationError(f"Database implementation not available for space '{space_id}'")
        
        # Create transaction using the core's transaction management
        async with await db_space_impl.core.create_transaction(db_space_impl) as transaction:
            # Execute operation with transaction
            result = await operation_func(transaction, *args, **kwargs)
            logger.debug(f"Transaction operation completed successfully")
            return result
            
    except ImplValidationError:
        raise
    except ImplConflictError:
        raise
    except Exception as e:
        raise ImplValidationError(f"Transaction execution failed: {e}")


async def get_db_space_impl(space_manager, space_id: str):
    """
    Get database space implementation for the given space.
    
    Args:
        space_manager: The space manager instance
        space_id: Space identifier
        
    Returns:
        Database space implementation
    """
    space_record = space_manager.get_space(space_id)
    if not space_record:
        raise ImplValidationError(f"Space {space_id} not found")
    
    space_impl = space_record.space_impl
    db_space_impl = space_impl.get_db_space_impl()
    if not space_impl:
        raise ImplValidationError(f"Space implementation not available for space '{space_id}'")
    if not db_space_impl:
        raise ImplValidationError(f"Database implementation not available for space '{space_id}'")
    
    return db_space_impl


def validate_uri_format(uri: str) -> None:
    """
    Validate URI format (http:// or urn: prefix).
    
    Args:
        uri: URI to validate
        
    Raises:
        ImplValidationError: If URI format is invalid
    """
    if not uri:
        raise ImplValidationError("URI cannot be empty")
    
    if not (uri.startswith('http://') or uri.startswith('https://') or uri.startswith('urn:')):
        raise ImplValidationError(f"Invalid URI format: {uri}. Must start with http://, https://, or urn:")


def validate_required_fields(obj_data: Dict, required_fields: List[str]) -> None:
    """
    Validate that required fields are present in object data.
    
    Args:
        obj_data: Object data dictionary
        required_fields: List of required field names
        
    Raises:
        ImplValidationError: If required fields are missing
    """
    missing_fields = []
    for field in required_fields:
        if field not in obj_data or obj_data[field] is None:
            missing_fields.append(field)
    
    if missing_fields:
        raise ImplValidationError(f"Missing required fields: {', '.join(missing_fields)}")


def extract_subject_uris(jsonld_objects: List[Dict]) -> List[str]:
    """
    Extract subject URIs from JSON-LD objects.
    
    Args:
        jsonld_objects: List of JSON-LD object dictionaries
        
    Returns:
        List of subject URIs
        
    Raises:
        ImplValidationError: If URIs are missing or invalid
    """
    subject_uris = []
    for i, obj in enumerate(jsonld_objects):
        uri = obj.get('@id') or obj.get('URI')
        if not uri:
            raise ImplValidationError(f"Object at index {i} missing URI (@id or URI field)")
        
        validate_uri_format(uri)
        subject_uris.append(uri)
    
    return subject_uris






async def batch_check_subject_uri_conflicts(
    space_manager, 
    space_id: str, 
    subject_uris: List[str]
) -> List[str]:
    """
    Check for URI conflicts for multiple objects in batch.
    
    Args:
        space_manager: The space manager instance
        space_id: Space identifier
        subject_uris: List of subject URIs to check
        
    Returns:
        List of conflicting URIs (empty if no conflicts)
        
    Raises:
        ImplValidationError: If check fails
    """
    try:
        if not subject_uris:
            return []
        
        # Use existing utility for batch checking
        conflicts = await check_subject_uri_conflicts(
            space_manager, space_id, subject_uris
        )
        
        return conflicts
        
    except Exception as e:
        raise ImplValidationError(f"Failed to check batch URI conflicts: {e}")


async def batch_get_existing_quads_for_uris(
    space_manager, 
    space_id: str, 
    graph_id: str, 
    subject_uris: List[str]
) -> List:
    """
    Get existing quads for multiple objects in batch.
    
    Args:
        space_manager: The space manager instance
        space_id: Space identifier
        graph_id: Graph identifier
        subject_uris: List of subject URIs to get quads for
        
    Returns:
        List of existing RDF quads
        
    Raises:
        ImplValidationError: If retrieval fails
    """
    try:
        if not subject_uris:
            return []
        
        # Use existing utility for batch retrieval
        existing_quads = await get_existing_quads_for_uris(
            space_manager, space_id, graph_id, subject_uris
        )
        
        return existing_quads
        
    except Exception as e:
        raise ImplValidationError(f"Failed to get batch existing quads: {e}")
