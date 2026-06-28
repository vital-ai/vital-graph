# Files Endpoint Implementation Plan
## Fuseki-PostgreSQL Hybrid Backend

### Overview
The Files endpoint provides binary data storage capabilities for the VitalGraph knowledge graph system. It handles file upload/download operations, metadata management, and S3 integration with graph objects tracking S3 paths.

### Implementation Status
- **Current Status**: ⚠️ **INCOMPLETE - List Files NOT Implemented**
- **Priority**: HIGH - Critical functionality missing
- **Dependencies**: ✅ All dependencies satisfied
- **JsonLdRequest Support**: ✅ Complete - Handles both single files (JsonLdObject) and multiple files (JsonLdDocument)
- **MinIO/S3 Integration**: ✅ Complete with S3FileManager
- **Binary Streaming**: ✅ Complete with bytes, streams, and pump operations
- **Test Coverage**: ⚠️ Tests pass but don't validate list_files functionality

### Critical Issues Identified

#### 1. `_list_files()` is a NO-OP Stub
**Location:** `/vitalgraph/endpoint/files_endpoint.py` lines 206-270

The method returns hardcoded sample data:
```python
async def _list_files(self, space_id: str, graph_id: Optional[str], ...):
    """List files with pagination."""
    # NO-OP implementation - return sample JSON-LD files
    sample_files = JsonLdDocument(**{
        "@context": {...},
        "@graph": [
            {"@id": "haley:file_document_001", ...},
            {"@id": "haley:file_image_001", ...},
            {"@id": "haley:file_data_001", ...}
        ]
    })
    return FilesResponse(files=sample_files, total_count=3, ...)
```

**Impact:** Real uploaded files (like the PDF and PNG in production) are not returned in listings.

#### 2. Why Tests Didn't Catch This

**Server-Side Tests** (`/test_script_kg_impl/files/case_files_list.py`):
- Tests only validate that response has correct structure
- Comments acknowledge testing stub: "For stub implementation, this will return sample files"
- No validation that actual uploaded files appear in results
- Tests pass because stub returns valid FilesResponse structure

**Client-Side Tests** (`/vitalgraph_client_test/files/case_file_list.py`):
- Tests only check `response.total_count` exists
- Don't validate that uploaded files appear in listing
- Don't compare uploaded file URIs with listed file URIs
- Tests pass because stub returns valid response format

#### 3. Production Impact
- Files successfully uploaded to AWS S3 ✅
- File metadata nodes created in graph database ✅
- Files downloadable by URI ✅
- **Files NOT visible in list_files() results** ❌
- Client sees hardcoded sample files instead of real files

## Architecture

### VitalSigns Graph Object Model

**CRITICAL: FileNode is the ONLY valid graph object for Files endpoint operations.**

All file operations MUST use VitalSigns `FileNode` graph objects from `vital_ai_domain.model.FileNode`. Direct JSON-LD manipulation is NOT permitted.

**Correct Pattern:**
```python
from vital_ai_domain.model.FileNode import FileNode

# Create FileNode graph object
file_node = FileNode()
file_node.URI = "haley:file_001"
file_node.name = "Document Name"

# Convert to JSON-LD via VitalSigns
jsonld_dict = file_node.to_jsonld()
file_data = JsonLdObject(**jsonld_dict)
```

**For Multiple Files:**
```python
files_list = [file_node_1, file_node_2]
jsonld_dict = FileNode.to_jsonld_list(files_list)
files_data = JsonLdDocument(**jsonld_dict)
```

### File Storage Model
```
FileNode (VitalSigns Graph Object)
├── URI: Unique file identifier
├── name: File display name
├── hasKGGraphURI: file_group_uri (grouping URI)
├── hasFileName: original filename
├── hasFileSize: file size in bytes
├── fileType: MIME type (e.g., image/png, application/pdf) ✅ AUTO-SET ON UPLOAD
├── fileURL: Full S3 URL path ✅ AUTO-SET ON UPLOAD
├── hasS3Path: S3 object key/path (deprecated - use fileURL)
├── hasS3Bucket: S3 bucket name (deprecated - included in fileURL)
├── hasUploadTimestamp: upload date/time
└── hasFileChecksum: file integrity hash
```

**New in v1.1: Automatic Property Setting**
- `fileURL`: Automatically set to full S3 URL during file upload (e.g., `https://s3.us-east-1.amazonaws.com/bucket/key`)
- `fileType`: Automatically set to MIME type during file upload using Python's `mimetypes` library

### S3-Compatible Storage Architecture
```
Client Upload → API Endpoint → S3/MinIO Storage → Graph Object Creation → Metadata Storage
                     ↓              ↓                    ↓                    ↓
              Validation      Pre-signed URLs       File Tracking      Dual Backend
```

**Storage Backend Options:**
- **MinIO**: For local development and testing (S3-compatible API)
- **AWS S3**: For production deployments
- **Unified Interface**: Same S3 client API works with both backends

## File Pump Infrastructure

### Binary Streaming Framework
The VitalGraph client includes a comprehensive binary streaming and pumping infrastructure for efficient file operations.

**Core Files:**
- **`/vitalgraph/client/binary/streaming.py`** - Binary streaming framework (313 lines)
  - `PumpingGenerator` class - Generator wrapper for chaining operations
  - `pump_data()` function - Generic pump from generator to consumer
  - `create_generator()` factory - Creates generators from various sources (paths, bytes, streams)
  - `create_consumer()` factory - Creates consumers for various destinations
  - Generator classes: `FilePathGenerator`, `BytesGenerator`, `StreamGenerator`
  - Consumer classes: `FilePathConsumer`, `BytesConsumer`, `StreamConsumer`

**Client Implementation:**
- **`/vitalgraph/client/endpoint/files_endpoint.py`** - File-specific pump operations
  - `pump_file()` method (lines 476-522) - Direct file-to-file streaming pump
  - `upload_file_content()` with generators (lines 319-364)
  - `upload_from_generator()` (lines 366-380)
  - `download_file_content()` with consumers (lines 396-443)
  - `download_to_consumer()` (lines 445-460)

**Client Wrapper:**
- **`/vitalgraph/client/vitalgraph_client.py`** - Convenience methods
  - `pump_file()` method (lines 1222-1241) - Delegates to files endpoint

**Mock Implementation:**
- **`/vitalgraph/mock/client/endpoint/mock_files_endpoint.py`** - Testing stubs
  - `pump_file()` stub (lines 851-858) - Returns mock responses

### Pump Architecture
```
Source File → Download Stream → Pump Generator → Upload Stream → Target File
                    ↓                  ↓                ↓
              Chunk Reading      Streaming Transfer   Chunk Writing
```

**Key Features:**
- ✅ No intermediate storage - pure streaming
- ✅ Configurable chunk size (default 8KB)
- ✅ Support for multiple source/destination types
- ✅ Generator/Consumer pattern for flexibility
- ✅ Content-type preservation
- ✅ Error handling and cleanup

## JsonLdRequest Implementation

### Discriminated Union Support
The Files endpoint now uses the `JsonLdRequest` discriminated union pattern for consistent handling of JSON-LD data:

```python
from ..model.jsonld_model import JsonLdRequest, JsonLdObject, JsonLdDocument

# POST /files - Create file nodes
@router.post("/files", response_model=FileCreateResponse)
async def create_file_node(
    request: JsonLdRequest,  # Automatically handles JsonLdObject or JsonLdDocument
    space_id: str = Query(...),
    graph_id: Optional[str] = Query(None),
    current_user: Dict = Depends(auth_dependency)
):
    """Create file node(s). Uses discriminated union to automatically handle 
    single files (JsonLdObject) or multiple files (JsonLdDocument)."""
    return await _create_file_node(space_id, graph_id, request, current_user)
```

### Request Handling Logic
```python
async def _create_file_node(self, space_id: str, graph_id: Optional[str], 
                            request: JsonLdRequest, current_user: Dict):
    """Handle both single and multiple file node creation."""
    created_uris = []
    
    # Handle both JsonLdObject and JsonLdDocument
    if isinstance(request, JsonLdObject):
        # Single file
        if request.id:
            created_uris.append(request.id)
    elif isinstance(request, JsonLdDocument):
        # Multiple files in @graph
        if request.graph:
            for obj in request.graph:
                if '@id' in obj:
                    created_uris.append(obj['@id'])
    
    return FileCreateResponse(
        message=f"Successfully created {len(created_uris)} file nodes",
        created_count=len(created_uris),
        created_uris=created_uris
    )
```

### Benefits
- **Type Safety**: FastAPI automatically validates and routes requests based on discriminator
- **Consistency**: Same pattern used across all VitalGraph endpoints (KGEntities, KGFrames, KGTypes, Objects, Triples, KGRelations)
- **Validation**: Pydantic models enforce proper JSON-LD structure
- **Documentation**: OpenAPI/Swagger automatically documents the discriminated union

## API Endpoints

### Implemented Routes (Base Path: `/api/files`)

| Method | Route | Description | Request Body | Response |
|--------|-------|-------------|--------------|----------|
| GET | `/api/files` | List/Get files | - | `FilesResponse` or `JsonLdObject/JsonLdDocument` |
| POST | `/api/files` | Create file nodes | `JsonLdRequest` | `FileCreateResponse` |
| PUT | `/api/files` | Update file metadata | `JsonLdRequest` | `FileUpdateResponse` |
| DELETE | `/api/files` | Delete file | - | `FileDeleteResponse` |
| POST | `/api/files/upload` | Upload binary content | `multipart/form-data` | `FileUploadResponse` |
| GET | `/api/files/download` | Download binary content | - | `StreamingResponse` |

**Query Parameters:**
- `space_id` (required) - Space identifier
- `graph_id` (optional) - Graph identifier  
- `uri` (optional) - File URI for get/delete/upload/download
- `uri_list` (optional) - Comma-separated URIs for batch get
- `page_size` (optional) - Pagination size (default: 100)
- `offset` (optional) - Pagination offset (default: 0)
- `file_filter` (optional) - Filter keyword

**GET /api/files Behavior:**
- Without `uri` or `uri_list`: Returns paginated list of files (`FilesResponse`)
- With `uri`: Returns single file metadata (`JsonLdObject`)
- With `uri_list`: Returns multiple file metadata (`JsonLdDocument`)

### Future Enhancements (Not Yet Implemented)
- **POST /api/files/upload/stream** - Streaming upload for large files
- **GET /api/files/download/stream** - Streaming download with chunked transfer
- **GET /api/files/metadata** - Dedicated metadata endpoint
- **PUT /api/files/metadata** - Dedicated metadata update endpoint
- **GET /api/files/upload-url** - Pre-signed upload URL generation
- **GET /api/files/download-url** - Pre-signed download URL generation

## Implementation Requirements

### Core File Management
- **File Upload**: Secure file upload with validation and virus scanning
- **File Storage**: S3 integration with proper bucket management
- **File Retrieval**: Efficient file download with streaming support
- **File Deletion**: Atomic deletion from both S3 and graph storage

### URI Conflict Handling
- **CRITICAL**: Creating a FileNode with a URI that already exists MUST fail
- **Implementation**: Check for existing URIs before creation using `batch_check_subject_uri_conflicts`
- **Error Response**: Raise `ValueError` with message: `"Files with URIs already exist: {uri_list}"`
- **No HTTP Status Codes**: Return proper error response objects, not HTTP 404/409 status codes
- **Client Handling**: Clients should list existing files, delete conflicts, then create new files
- **Error Message**: Must clearly indicate which specific URI(s) already exist

### File Metadata Management
- **Metadata Extraction**: Automatic extraction of file metadata (EXIF, document properties)
- **Custom Metadata**: Support for user-defined metadata frames and slots
- **File Indexing**: Full-text indexing for searchable file content
- **Version Control**: File versioning and history tracking

### S3-Compatible Storage Integration Components
```python
class S3FileManager:
    """Unified S3-compatible file manager supporting both AWS S3 and MinIO."""
    
    def __init__(self, endpoint_url=None, use_ssl=True):
        """
        Initialize S3 client.
        
        Args:
            endpoint_url: MinIO endpoint URL (e.g., 'http://localhost:9000') 
                         or None for AWS S3
            use_ssl: Whether to use SSL (True for S3, False for local MinIO)
        """
        pass
    
    def upload_file(self, file_data, bucket, key, metadata=None)
    def download_file(self, bucket, key, stream=False)
    def delete_file(self, bucket, key)
    def generate_presigned_url(self, bucket, key, expiration=3600)
    def list_files(self, bucket, prefix=None, pagination=None)
```

**Storage Backend Configuration:**
- **Local Development**: MinIO with `endpoint_url='http://localhost:9000'`
- **Production**: AWS S3 with `endpoint_url=None` (uses default AWS endpoints)

### Security and Validation
- **File Type Validation**: Whitelist/blacklist of allowed file types
- **File Size Limits**: Configurable file size restrictions
- **Virus Scanning**: Integration with antivirus scanning services
- **Access Control**: File-level permissions and access control

## Backend Integration Requirements

### Graph Object Integration
- **File Graph Objects**: Create graph objects for each uploaded file
- **Metadata Frames**: Optional structured metadata using frame system
- **File Relationships**: Link files to entities, frames, and other objects
- **Grouping URIs**: Use hasKGGraphURI for efficient file organization

### Storage Coordination
- **Dual Storage**: S3 for binary data, graph storage for metadata
- **Consistency**: Ensure S3 and graph metadata remain synchronized
- **Transaction Support**: Atomic operations across S3 and graph storage
- **Cleanup**: Orphaned file detection and cleanup processes

### File Processing Pipeline
```python
async def process_file_upload(file_data, metadata):
    # 1. Validate file type and size
    validation_result = await validate_file(file_data)
    
    # 2. Upload to S3
    s3_path = await s3_manager.upload_file(file_data, bucket, key)
    
    # 3. Create graph object
    file_object = create_file_graph_object(s3_path, metadata)
    
    # 4. Store metadata in graph
    await backend.store_objects([file_object])
    
    # 5. Create metadata frames (optional)
    if metadata_frames:
        await create_file_metadata_frames(file_object.URI, metadata_frames)
    
    return file_object
```

### File Upload Property Auto-Setting (v1.1)

**Implementation:** After uploading file content to S3, the system automatically updates the FileNode with storage location and type information.

**Process Flow:**
```python
# In files_endpoint.py _upload_file_content()
async def _upload_file_content(space_id, graph_id, uri, file, current_user):
    # 1. Upload to S3/MinIO
    result = file_manager.upload_file(file_data, object_key, content_type)
    
    # 2. Generate S3 URL
    s3_url = file_manager.get_file_url(object_key)  # e.g., https://s3.us-east-1.amazonaws.com/bucket/key
    
    # 3. Get existing FileNode GraphObject
    file_node = await files_impl.get_file_by_uri(space_id, uri, graph_id)
    
    # 4. Update properties using VitalSigns
    file_node.fileURL = s3_url  # Full S3 URL
    file_node.fileType = content_type  # MIME type from mimetypes library
    
    # 5. Update FileNode in database
    await files_impl.update_files(space_id, [file_node], graph_id)
```

**Key Components:**

1. **S3FileManager.get_file_url()** (`/vitalgraph/storage/s3_file_manager.py`):
   - Generates full S3 URL from object key
   - Handles both MinIO and AWS S3 URL formats
   - Returns: `https://s3.{region}.amazonaws.com/{bucket}/{key}` for S3
   - Returns: `{protocol}://{endpoint}/{bucket}/{key}` for MinIO

2. **FilesImpl.get_file_by_uri()** (`/vitalgraph/endpoint/impl/files_impl.py`):
   - Returns FileNode GraphObject directly (not JSON-LD dict)
   - Enables direct property manipulation via VitalSigns

3. **FilesImpl.update_files()** (`/vitalgraph/endpoint/impl/files_impl.py`):
   - Accepts list of FileNode GraphObjects
   - Converts to quads using VitalSigns
   - Uses `remove_quads_by_subject_uris()` to delete old quads
   - Inserts new quads with updated properties

**MIME Type Detection:**
- Uses Python's built-in `mimetypes` library
- Detects from file extension and content
- Examples: `image/png`, `image/jpeg`, `application/pdf`, `text/plain`
- Fallback: `application/octet-stream` if type cannot be determined

**Benefits:**
- ✅ Automatic property setting - no manual client updates needed
- ✅ Consistent S3 URL format across all files
- ✅ Accurate MIME type detection
- ✅ Properties queryable via SPARQL in Fuseki
- ✅ Properties stored in PostgreSQL for fast access

**Verification:**
```sparql
# Query FileNode properties in Fuseki
PREFIX vital: <http://vital.ai/ontology/vital#>

SELECT ?file ?fileURL ?fileType
WHERE {
    GRAPH <urn:graph> {
        ?file a vital:FileNode .
        ?file vital:hasFileURL ?fileURL .
        ?file vital:hasFileType ?fileType .
    }
}
```

## Completed Implementation

### ✅ Phase 1: Core Implementation (COMPLETE)
**Server-Side Components:**
- ✅ S3FileManager class (`/vitalgraph/storage/s3_file_manager.py`)
  - Unified interface for MinIO and AWS S3
  - Upload, download, delete operations
  - Presigned URL generation
  - Metadata management
  - Bucket management
  - **NEW:** `get_file_url()` method for generating full S3 URLs
- ✅ Files endpoint (`/vitalgraph/endpoint/files_endpoint.py`)
  - JsonLdRequest pattern for create/update
  - Binary upload/download with MinIO integration
  - File metadata CRUD operations
  - Streaming response for downloads
  - **NEW:** Automatic `fileURL` and `fileType` property setting on upload
- ✅ Files implementation (`/vitalgraph/endpoint/impl/files_impl.py`)
  - **NEW:** `get_file_by_uri()` returns FileNode GraphObject directly
  - **NEW:** `update_files()` accepts list of FileNode GraphObjects
  - VitalSigns-native GraphObject handling
- ✅ Router registration (`/vitalgraph/impl/vitalgraphapp_impl.py`)
  - Registered with `/api` prefix
  - Config passed for MinIO integration

**Client-Side Components:**
- ✅ Files endpoint client (`/vitalgraph/client/endpoint/files_endpoint.py`)
  - Metadata operations (list, get, create, update, delete)
  - Binary operations with streaming support
  - Upload from bytes, streams, paths, generators
  - Download to bytes, streams, paths, consumers
  - Pump file operations for direct streaming

**Configuration:**
- ✅ MinIO Docker service in `docker-compose.yml`
- ✅ File storage config in `vitalgraphdb-config.yaml`
- ✅ Environment-based backend switching (MinIO/S3)

### ✅ Phase 2: Binary Streaming (COMPLETE)
**Streaming Framework:**
- ✅ Generator/Consumer pattern (`/vitalgraph/client/binary/streaming.py`)
  - `create_generator()` - Creates generators from various sources
  - `create_consumer()` - Creates consumers for various destinations
  - `pump_data()` - Generic pump function
  - Support for bytes, streams, paths, and custom generators

**Upload Methods:**
- ✅ Byte array upload
- ✅ Stream upload (BinaryIO)
- ✅ File path upload
- ✅ Generator-based upload
- ✅ Large file support (chunked)

**Download Methods:**
- ✅ Download as bytes
- ✅ Download to stream
- ✅ Download to file path
- ✅ Download to consumer
- ✅ Streaming response

**Pump Operations:**
- ✅ Direct file-to-file streaming
- ✅ No intermediate storage
- ✅ Configurable chunk size
- ✅ Content-type preservation

### ✅ Phase 3: Test Infrastructure (COMPLETE)
**Server-Side Tests:**
- ✅ Comprehensive test script (`/test_scripts/fuseki_postgresql/test_files_endpoint_fuseki_postgresql.py`)
  - Follows KGEntities pattern
  - 11 test phases
  - Space creation/cleanup
  - MinIO integration validation

**Test Case Modules** (`/test_script_kg_impl/files/`):
- ✅ `case_files_create.py` - File node creation
- ✅ `case_files_list.py` - File listing
- ✅ `case_files_get.py` - File retrieval
- ✅ `case_files_update.py` - Metadata updates
- ✅ `case_files_delete.py` - File deletion
- ✅ `case_files_upload.py` - Binary upload (bytes, streams, large files)
- ✅ `case_files_download.py` - Binary download (bytes, streams)

**Client-Side Tests:**
- ✅ Comprehensive test script (`/vitalgraph_client_test/test_files_endpoint.py`)
  - JWT authentication
  - Space creation/cleanup
  - 4 test suites

**Client Test Cases** (`/vitalgraph_client_test/files/`):
- ✅ `case_file_create.py` - Create single/multiple file nodes
- ✅ `case_file_upload.py` - Upload bytes, streams, large files
- ✅ `case_file_download.py` - Download as bytes, to streams
- ✅ `case_file_pump.py` - Pump files between nodes

### Future Enhancements
**Not Yet Implemented:**
- File metadata extraction (EXIF, document properties)
- Virus scanning integration
- File versioning and history
- Pre-signed URL endpoints
- Dedicated streaming endpoints
- File search and indexing
- Thumbnail generation
- Content analysis

## File Processing Features

### Metadata Extraction
- **Image Files**: EXIF data, dimensions, color profiles
- **Document Files**: Author, creation date, document properties
- **Audio/Video**: Duration, codec, bitrate, metadata tags
- **Archive Files**: Contents listing, compression ratios

### Content Processing
- **Text Extraction**: Full-text content extraction for indexing
- **Thumbnail Generation**: Image and video thumbnail creation
- **Format Conversion**: Optional format conversion capabilities
- **Content Analysis**: Content type detection and validation

### File Organization
- **Folder Structures**: Virtual folder organization using graph relationships
- **File Collections**: Group related files using collection objects
- **Tagging System**: Flexible tagging and categorization
- **File Hierarchies**: Support for hierarchical file organization

## Success Criteria

### ✅ Completed
- ✅ All core file operations implemented and tested
- ✅ MinIO/S3 integration working reliably
- ✅ JsonLdRequest pattern fully implemented
- ✅ Binary streaming with bytes, streams, and generators
- ✅ File pump operations for direct streaming
- ✅ Comprehensive server-side test suite
- ✅ Comprehensive client-side test suite
- ✅ Production-ready file management capabilities
- ✅ Docker configuration with MinIO service
- ✅ Configuration management for MinIO/S3 switching
- ✅ **NEW:** Automatic `fileURL` and `fileType` property setting on upload
- ✅ **NEW:** VitalSigns-native FileNode GraphObject handling in implementation layer
- ✅ **NEW:** S3 URL generation for both MinIO and AWS S3
- ✅ **NEW:** MIME type detection using Python mimetypes library
- ✅ **NEW:** FileNode property updates stored in both Fuseki and PostgreSQL

## Dependencies and Integration

### External Dependencies
- **AWS S3**: Binary file storage for production deployments
- **MinIO**: S3-compatible storage for local development and testing
- **File Processing Libraries**: Metadata extraction and content processing
- **Security Scanning**: Antivirus and malware detection
- **Image Processing**: Thumbnail generation and image manipulation

### Integration Points
- **Entity Integration**: Link files to entities and frames
- **Search Integration**: Full-text search of file content
- **Backup Integration**: File backup and disaster recovery
- **CDN Integration**: Content delivery network for file access

## Configuration Requirements

### Configuration Files Location

**IMPORTANT: Use the correct configuration files for file storage settings**

**Server-Side Configuration (VitalGraph Database):**
- **Primary Config**: `/vitalgraphdb_config/vitalgraphdb-config.yaml`
- **Fuseki-PostgreSQL Config**: `/vitalgraphdb_config/vitalgraphdb-config-fuseki-postgresql.yaml`
- **Purpose**: Server-side settings for file storage backend (MinIO/S3)

**Client-Side Configuration:**
- **Client Config**: `/vitalgraphclient_config/vitalgraphclient-config.yaml`
- **Purpose**: Client connection settings (should NOT contain file storage backend settings)

**⚠️ Common Mistake:** Do NOT add file storage backend configuration to the client config file. File storage settings belong in the server-side `vitalgraphdb-config.yaml` files.

### Storage Backend Configuration

**MinIO Configuration (Local Development/Testing):**
```python
MINIO_CONFIG = {
    'endpoint_url': 'http://localhost:9000',
    'access_key_id': 'minioadmin',
    'secret_access_key': 'minioadmin',
    'bucket_name': 'vitalgraph-files-local',
    'use_ssl': False,
    'presigned_url_expiration': 3600,
    'max_file_size': 100 * 1024 * 1024,  # 100MB
    'allowed_file_types': ['.pdf', '.jpg', '.png', '.docx', '.txt']
}
```

**AWS S3 Configuration (Production Deployments):**
```python
S3_CONFIG = {
    'endpoint_url': None,  # Use default AWS endpoints
    'bucket_name': 'vitalgraph-files',
    'region': 'us-east-1',
    'access_key_id': '...',
    'secret_access_key': '...',
    'use_ssl': True,
    'presigned_url_expiration': 3600,
    'max_file_size': 100 * 1024 * 1024,  # 100MB
    'allowed_file_types': ['.pdf', '.jpg', '.png', '.docx', '.txt']
}
```

**YAML Configuration in vitalgraphdb-config.yaml:**

Add this section to `/vitalgraphdb_config/vitalgraphdb-config.yaml`:

```yaml
# File Storage Configuration (MinIO for local, S3 for production)
file_storage:
  # Backend type: 'minio' for local development, 's3' for production
  backend: minio  # or 's3'
  
  # MinIO Configuration (local development/testing)
  minio:
    endpoint_url: http://localhost:9000
    access_key_id: minioadmin
    secret_access_key: minioadmin
    bucket_name: vitalgraph-files-local
    use_ssl: false
    region: us-east-1  # Not used by MinIO but kept for compatibility
  
  # AWS S3 Configuration (production deployments)
  s3:
    endpoint_url: null  # Use default AWS endpoints
    access_key_id: ${AWS_ACCESS_KEY_ID}  # From environment variable
    secret_access_key: ${AWS_SECRET_ACCESS_KEY}  # From environment variable
    bucket_name: vitalgraph-files-prod
    use_ssl: true
    region: us-east-1
  
  # Common settings for both backends
  settings:
    presigned_url_expiration: 3600  # 1 hour
    max_file_size: 104857600  # 100MB in bytes
    chunk_size: 8192  # 8KB chunks for streaming
    allowed_file_types:
      - .pdf
      - .jpg
      - .jpeg
      - .png
      - .gif
      - .docx
      - .txt
      - .csv
      - .json
      - .xml
```

**Environment-Based Configuration Pattern:**
```python
# In server code, load based on file_storage.backend setting
def get_file_storage_config(config: dict) -> dict:
    """Get file storage config based on backend type."""
    backend = config['file_storage']['backend']
    
    if backend == 'minio':
        return config['file_storage']['minio']
    elif backend == 's3':
        return config['file_storage']['s3']
    else:
        raise ValueError(f"Unknown file storage backend: {backend}")
```

### File Processing Configuration
- **Metadata Extraction**: Enable/disable metadata extraction by file type
- **Thumbnail Generation**: Configure thumbnail sizes and formats
- **Content Indexing**: Enable full-text indexing for searchable content
- **Virus Scanning**: Configure antivirus scanning integration

## Notes
- File operations require careful coordination between S3 and graph storage
- Security is critical for file upload and access operations
- Performance optimization essential for large file handling
- Metadata extraction enables rich file search and organization
- Integration with entity system enables sophisticated file relationships