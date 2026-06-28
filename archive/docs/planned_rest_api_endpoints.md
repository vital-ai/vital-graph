# VitalGraph REST API Endpoints - Planning Document

## Overview

This document outlines planned REST API endpoints to support the frontend functionality in VitalGraph. The endpoints are organized by functional area and follow RESTful conventions with space ID and graph ID parameters where applicable.

## Base URL Structure

All endpoints will be under the `/api` prefix and follow this pattern:
- `/api/{resource}` - Global resources (spaces, users, etc.)
- `/api/spaces/{spaceId}/{resource}` - Space-scoped resources
- `/api/spaces/{spaceId}/graphs/{graphId}/{resource}` - Graph-scoped resources

## Existing Endpoints (Reference)

**Authentication:**
- `POST /api/login` - User login ✅
- `POST /api/logout` - User logout ✅

**Spaces:**
- `GET /api/spaces` - List all spaces ✅
- `POST /api/spaces` - Create new space ✅
- `GET /api/spaces/{space_id}` - Get space details ✅
- `PUT /api/spaces/{space_id}` - Update space ✅
- `DELETE /api/spaces/{space_id}` - Delete space ✅
- `GET /api/spaces/filter/{name_filter}` - Filter spaces by name ✅

**Users:**
- `GET /api/users` - List all users 

**SPARQL (all under `/api/graphs/sparql` prefix):**

**Query Endpoints:**
- `POST /api/graphs/sparql/{space_id}/query` - Execute SPARQL queries (SELECT, CONSTRUCT, ASK, DESCRIBE) 
- `GET /api/graphs/sparql/{space_id}/query` - Simple SPARQL queries via GET parameters 

**Update Endpoints:**
- `POST /api/graphs/sparql/{space_id}/update` - Execute SPARQL UPDATE operations 
- `POST /api/graphs/sparql/{space_id}/update-form` - Form-based SPARQL updates 

**Insert Endpoints:**
- `POST /api/graphs/sparql/{space_id}/insert` - Execute SPARQL INSERT operations 
- `POST /api/graphs/sparql/{space_id}/insert-form` - Form-based SPARQL inserts 
- `POST /api/graphs/sparql/{space_id}/insert-data` - Direct RDF data insertion 

**Delete Endpoints:**
- `POST /api/graphs/sparql/{space_id}/delete` - Execute SPARQL DELETE operations 
- `POST /api/graphs/sparql/{space_id}/delete-form` - Form-based SPARQL deletes 
- `DELETE /api/graphs/sparql/{space_id}/graph` - Clear specific graph 

**Graph Management Endpoints:**
- `GET /api/graphs/sparql/{space_id}/graphs` - List all graphs in space 
- `GET /api/graphs/sparql/{space_id}/graph/{graph_uri}` - Get specific graph info 
- `POST /api/graphs/sparql/{space_id}/graph` - Execute graph operations (CREATE, DROP, CLEAR, COPY, MOVE, ADD) 
- `PUT /api/graphs/sparql/{space_id}/graph/{graph_uri}` - Create new graph 
- `DELETE /api/graphs/sparql/{space_id}/graph/{graph_uri}` - Drop graph 

**Graph Operations (via POST /{space_id}/graph):**
- **CREATE** - Create a new empty graph
- **DROP** - Delete a graph and all its triples
- **CLEAR** - Remove all triples from a graph (but keep the graph)
- **COPY** - Copy all triples from source graph to target graph
- **MOVE** - Move all triples from source graph to target graph
- **ADD** - Add all triples from source graph to target graph (without removing from source)

**System:**
- `GET /api/health` - Health check 
- `WebSocket /api/ws` - WebSocket connection 

## Space Management Endpoints

### Spaces
All space CRUD operations already exist ✅

## Graph Data Management Endpoints (using `/api/graphs` prefix)

### Triples
- `GET /api/graphs/triples?space_id={spaceId}&graph_id={graphId}&page_size={pageSize}&offset={offset}&subject={subjectUri}&predicate={predicateUri}&object={objectValue}&object_filter={keyword}` - List/search triples with pagination/filtering
  - **subject** (optional): Subject URI to filter by
  - **predicate** (optional): Predicate URI to filter by  
  - **object** (optional): Object value to filter by (string that may include RDF data typing, e.g., `"2"^^<http://www.w3.org/2001/XMLSchema#integer>`)
  - **object_filter** (optional): Keyword to search within object string values
- `POST /api/graphs/triples?space_id={spaceId}&graph_id={graphId}` - Add new triples (set of triples posted in request body)
- `DELETE /api/graphs/triples?space_id={spaceId}&graph_id={graphId}` - Delete specific triples (triples to delete posted in request body)


### Graph Objects
- `GET /api/graphs/objects?space_id={spaceId}&graph_id={graphId}&page_size={pageSize}&offset={offset}` - List graph objects with pagination/search
- `POST /api/graphs/objects?space_id={spaceId}&graph_id={graphId}` - Create new graph objects (N objects by posting the triples of the objects in request body) - Returns error if any subject URI already exists
- `GET /api/graphs/objects?space_id={spaceId}&graph_id={graphId}&uri={objectUri}` - Get object details by URI
- `GET /api/graphs/objects?space_id={spaceId}&graph_id={graphId}&uri_list={uri1,uri2,uri3}` - Get multiple objects by comma-separated URI list
- `PUT /api/graphs/objects?space_id={spaceId}&graph_id={graphId}` - Update object (deletes existing object with subject URI first, then inserts replacement)
- `DELETE /api/graphs/objects?space_id={spaceId}&graph_id={graphId}&uri={objectUri}` - Delete object by URI
- `DELETE /api/graphs/objects?space_id={spaceId}&graph_id={graphId}&uri_list={uri1,uri2,uri3}` - Delete multiple objects by comma-separated URI list


## KG Entity Management Endpoints

### KG Entities
- `GET /api/graphs/kgentities?space_id={spaceId}&graph_id={graphId}&page_size={pageSize}&offset={offset}&entity_type_uri={entityTypeUri}` - List KG entities with pagination/search
- `POST /api/graphs/kgentities?space_id={spaceId}&graph_id={graphId}` - Create new KG entities (N entities by posting the triples of the entities in request body) - Returns error if any subject URI already exists
- `GET /api/graphs/kgentities?space_id={spaceId}&graph_id={graphId}&uri={entityUri}` - Get entity details by URI
- `GET /api/graphs/kgentities?space_id={spaceId}&graph_id={graphId}&uri_list={uri1,uri2,uri3}` - Get multiple entities by comma-separated URI list
- `PUT /api/graphs/kgentities?space_id={spaceId}&graph_id={graphId}` - Update entity (deletes existing entity with subject URI first, then inserts replacement)
- `DELETE /api/graphs/kgentities?space_id={spaceId}&graph_id={graphId}&uri={entityUri}` - Delete entity by URI
- `DELETE /api/graphs/kgentities?space_id={spaceId}&graph_id={graphId}&uri_list={uri1,uri2,uri3}` - Delete multiple entities by comma-separated URI list

### Entity Frames
- `GET /api/graphs/kgentities/kgframes?space_id={spaceId}&graph_id={graphId}&uri={entityUri}&frame_type_uri={frameTypeUri}` - Get frame URIs linked to entity (returns list of frame URIs or empty list)
- `GET /api/graphs/kgentities/kgframes?space_id={spaceId}&graph_id={graphId}&uri_list={uri1,uri2,uri3}&frame_type_uri={frameTypeUri}` - Get frame URIs linked to multiple entities (returns list of frame URIs or empty list)

## KG Frame Management Endpoints

### KG Frames
- `GET /api/graphs/kgframes?space_id={spaceId}&graph_id={graphId}&page_size={pageSize}&offset={offset}&frame_uri_type={frameUriType}` - List KG frames with pagination/search
- `POST /api/graphs/kgframes?space_id={spaceId}&graph_id={graphId}` - Create new KG frames (N frames by posting the triples of the frames in request body) - Returns error if any subject URI already exists
- `GET /api/graphs/kgframes?space_id={spaceId}&graph_id={graphId}&uri={frameUri}` - Get frame details by URI
- `GET /api/graphs/kgframes?space_id={spaceId}&graph_id={graphId}&uri_list={uri1,uri2,uri3}` - Get multiple frames by comma-separated URI list
- `PUT /api/graphs/kgframes?space_id={spaceId}&graph_id={graphId}` - Update frame (deletes existing frame with subject URI first, then inserts replacement)
- `DELETE /api/graphs/kgframes?space_id={spaceId}&graph_id={graphId}&uri={frameUri}` - Delete frame by URI
- `DELETE /api/graphs/kgframes?space_id={spaceId}&graph_id={graphId}&uri_list={uri1,uri2,uri3}` - Delete multiple frames by comma-separated URI list

### Frame Slots
Frame slots endpoints operate on complete frame objects that include both the frame node and its connected slot nodes with values. A frame is a node which may have edges to slot nodes, with slot nodes having values. For example, an address frame might have a postal code slot, street address slot, city slot, etc. These API endpoints operate on sets of objects representing frames with their complete slot structure.

- `GET /api/graphs/kgframes/kgslots?space_id={spaceId}&graph_id={graphId}&frame_uri={frameUri}` - Get frame plus its slot elements by frame URI (returns frame object with connected slot nodes and values)
- `GET /api/graphs/kgframes/kgslots?space_id={spaceId}&graph_id={graphId}&frame_uri_list={uri1,uri2,uri3}` - Get multiple frames plus their slot elements by comma-separated frame URI list
- `POST /api/graphs/kgframes/kgslots?space_id={spaceId}&graph_id={graphId}` - Insert frame/slots (set of frame objects with their slot nodes posted in request body) - Returns error if any frame URI already exists
- `PUT /api/graphs/kgframes/kgslots?space_id={spaceId}&graph_id={graphId}` - Update frame/slots (deletes existing frame and slot objects with same URIs first, then inserts replacements)
- `DELETE /api/graphs/kgframes/kgslots?space_id={spaceId}&graph_id={graphId}&frame_uri={frameUri}` - Delete frame and its slot elements by frame URI
- `DELETE /api/graphs/kgframes/kgslots?space_id={spaceId}&graph_id={graphId}&frame_uri_list={uri1,uri2,uri3}` - Delete multiple frames and their slot elements by comma-separated frame URI list

## KG Type Management Endpoints

### KG Types
- `GET /api/graphs/kgtypes?space_id={spaceId}&graph_id={graphId}&page_size={pageSize}&offset={offset}&type_filter={keyword}` - List KG types in graph with pagination/search
- `POST /api/graphs/kgtypes?space_id={spaceId}&graph_id={graphId}` - Create new KG types
- `GET /api/graphs/kgtypes?space_id={spaceId}&graph_id={graphId}&uri={typeUri}` - Get type details by URI
- `GET /api/graphs/kgtypes?space_id={spaceId}&graph_id={graphId}&uri_list={uri1,uri2,uri3}` - Get multiple types by comma-separated URI list
- `PUT /api/graphs/kgtypes?space_id={spaceId}&graph_id={graphId}` - Update types
- `DELETE /api/graphs/kgtypes?space_id={spaceId}&graph_id={graphId}&uri={typeUri}` - Delete type by URI
- `DELETE /api/graphs/kgtypes?space_id={spaceId}&graph_id={graphId}&uri_list={uri1,uri2,uri3}` - Delete multiple types by comma-separated URI list


## File Management Endpoints

### Files
- `GET /api/graphs/files?space_id={spaceId}&graph_id={graphId}&page_size={pageSize}&offset={offset}&file_filter={keyword}` - List files in graph with pagination/search
- `POST /api/graphs/files?space_id={spaceId}&graph_id={graphId}` - Create new file node (metadata only)
- `GET /api/graphs/files?space_id={spaceId}&graph_id={graphId}&uri={fileUri}` - Get file node details by URI
- `GET /api/graphs/files?space_id={spaceId}&graph_id={graphId}&uri_list={uri1,uri2,uri3}` - Get multiple file nodes by comma-separated URI list
- `PUT /api/graphs/files?space_id={spaceId}&graph_id={graphId}` - Update file node metadata
- `DELETE /api/graphs/files?space_id={spaceId}&graph_id={graphId}&uri={fileUri}` - Delete file node by URI

### File Content
- `POST /api/graphs/files/upload?space_id={spaceId}&graph_id={graphId}&uri={fileUri}` - Upload binary file content to existing file node
- `GET /api/graphs/files/download?space_id={spaceId}&graph_id={graphId}&uri={fileUri}` - Download binary file content by URI


## Data Import/Export Endpoints (using `/api/data` prefix)

### Import Operations
- `POST /api/data/import` - Create new data import job
- `GET /api/data/import?space_id={spaceId}&graph_id={graphId}` - List all import jobs
- `GET /api/data/import/{importId}` - Get import job details
- `PUT /api/data/import/{importId}` - Update import job
- `DELETE /api/data/import/{importId}` - Delete import job
- `POST /api/data/import/{importId}/execute` - Execute import job
- `GET /api/data/import/{importId}/status` - Get import execution status
- `GET /api/data/import/{importId}/log` - Get import execution log
- `POST /api/data/import/{importId}/upload` - upload file to import


### Export Operations
- `POST /api/data/export` - Create new data export job
- `GET /api/data/export?space_id={spaceId}&graph_id={graphId}` - List all export jobs
- `GET /api/data/export/{exportId}` - Get export job details
- `PUT /api/data/export/{exportId}` - Update export job
- `DELETE /api/data/export/{exportId}` - Delete export job
- `POST /api/data/export/{exportId}/execute` - Execute export job
- `GET /api/data/export/{exportId}/status` - Get export execution status
- `GET /api/data/export/{exportId}/download?binary_id={binaryId}` - Download export results



## Request/Response Patterns

### Common Query Parameters
- `page` - Page number for pagination (default: 1)
- `limit` - Items per page (default: 10, max: 100)
- `search` - Search term for filtering
- `sort` - Sort field
- `order` - Sort order (asc/desc)
- `filter` - Additional filters (format TBD)

### Common Response Structure
```json
{
  "data": [...],
  "pagination": {
    "page": 1,
    "limit": 10,
    "total": 100,
    "pages": 10
  },
  "meta": {
    "timestamp": "2024-01-01T00:00:00Z",
    "version": "1.0"
  }
}
```

### Error Response Structure
```json
{
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "The requested resource was not found",
    "details": {...}
  }
}
```
