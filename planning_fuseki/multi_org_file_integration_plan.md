# Multi-Org Test: File Upload/Download Integration Plan

## Overview
Integrate file upload/download operations into the multi-org CRUD test suite, creating file nodes that are referenced by business entities through frames.

## Current Test Flow
```
0. KGTypes operations (create and list entity types, frame types, slot types)
1. Create 10 organization entities (with reference IDs)
2. Create 10 business events (referencing organizations)
3. List all entities
4. Get individual entities by URI
5. Get entities by reference ID (single and multiple)
6. Update entities (employee counts)
7. Verify updates
8. Frame-level operations (list, get, update frames)
9. KGQuery frame-based connection queries (multi-frame slot criteria)
10. Entity graph operations
11. Delete entities
12. Verify deletions
```

## Proposed New Test Flow
```
0. KGTypes operations (create and list entity types, frame types, slot types)
   - ADD: Create file-related frame types and slot types
1. **NEW: Upload 10 PDF files and create file nodes (binary data + metadata)**
2. Create 10 organization entities (with reference IDs)
   - MODIFY: Include file reference frames in entity graph specification
   - Frames contain URIs pointing to file nodes
3. Create 10 business events (referencing organizations)
   - MODIFY: Include file references in event frames (invoices, receipts)
4. **NEW: Download and verify files**
5. List all entities (10 orgs + 10 events = 20 KGEntities)
   - Note: File nodes are NOT KGEntities, they are separate file resources
6. Get individual entities by URI
7. Get entities by reference ID (single and multiple)
8. Update entities (employee counts)
9. Verify updates
10. Frame-level operations (list, get, update frames)
    - VERIFY: File URI references in frames point to valid file nodes
11. KGQuery frame-based queries (multi-frame slot criteria)
    - ADD: Query entities by file URI references in frames
12. Entity graph operations
13. Delete entities (20 KGEntities)
14. Verify deletions
15. **NEW: Delete file nodes (10 files) and verify file cleanup**
```

## New Test Case Files to Create

### 1. `case_upload_files.py`
**Location:** `/Users/hadfield/Local/vital-git/vital-graph/vitalgraph_client_test/multi_kgentity/case_upload_files.py`

**Responsibilities:**
- Upload 10 PDF files from test files location
- Create 10 file nodes (binary data + metadata, NOT KGEntities)
- Track file node URIs for later use in entity frames
- Verify file upload success

**Test Files Source:**
- Use existing PDFs from `/Users/hadfield/Local/vital-git/vital-graph/test_files/`
- If only 2 PDFs exist, duplicate/rename to create 10 test files

**File Types/Purposes:**
1. Contract documents (3 files)
2. Financial reports (2 files)
3. Marketing materials (2 files)
4. Technical specifications (2 files)
5. Legal documents (1 file)

**Tests:**
- Upload each file successfully
- Verify file node creation
- Verify file metadata (size, name, content type)

**Returns:**
- Dictionary with file URIs mapped to file purposes/types
- Example: `{"contract_1": "urn:file:contract_techcorp", "financial_1": "urn:file:report_q1", ...}`

### 2. `case_download_files.py`
**Location:** `/Users/hadfield/Local/vital-git/vital-graph/vitalgraph_client_test/multi_kgentity/case_download_files.py`

**Responsibilities:**
- Download files using file node URIs
- Verify downloaded file content matches original
- Test download error handling

**Input Required:**
- `file_uris`: Dictionary of file URIs from upload step

**Tests:**
- Download each file successfully
- Verify file size matches
- Verify content hash/checksum (if available)
- Test download of non-existent file (error case)

### 3. `case_delete_files.py`
**Location:** `/Users/hadfield/Local/vital-git/vital-graph/vitalgraph_client_test/multi_kgentity/case_delete_files.py`

**Responsibilities:**
- Delete file nodes
- Verify file deletion from storage
- Verify frames referencing deleted files are handled correctly

**Tests:**
- Delete individual file nodes
- Verify file no longer downloadable
- Verify file node entity removed
- Check orphaned frame references (if any)

## KGTypes to Add

### Frame Types
```python
FRAME_TYPES = [
    {
        "uri": "http://vital.ai/ontology/haley-ai-kg#BusinessContractFrame",
        "name": "BusinessContractFrame",
        "description": "Frame for business contract documents"
    },
    {
        "uri": "http://vital.ai/ontology/haley-ai-kg#FinancialDocumentFrame",
        "name": "FinancialDocumentFrame",
        "description": "Frame for financial documents and reports"
    },
    {
        "uri": "http://vital.ai/ontology/haley-ai-kg#MarketingMaterialFrame",
        "name": "MarketingMaterialFrame",
        "description": "Frame for marketing materials and collateral"
    },
    {
        "uri": "http://vital.ai/ontology/haley-ai-kg#TechnicalDocumentFrame",
        "name": "TechnicalDocumentFrame",
        "description": "Frame for technical specifications and documentation"
    },
    {
        "uri": "http://vital.ai/ontology/haley-ai-kg#LegalDocumentFrame",
        "name": "LegalDocumentFrame",
        "description": "Frame for legal documents and agreements"
    }
]
```

### Slot Types
```python
SLOT_TYPES = [
    {
        "uri": "http://vital.ai/ontology/haley-ai-kg#DocumentFileURISlot",
        "name": "DocumentFileURISlot",
        "parent_class": "http://vital.ai/ontology/haley-ai-kg#KGURISlot",
        "description": "Slot for document file URI reference"
    },
    {
        "uri": "http://vital.ai/ontology/haley-ai-kg#DocumentTypeSlot",
        "name": "DocumentTypeSlot",
        "parent_class": "http://vital.ai/ontology/haley-ai-kg#KGTextSlot",
        "description": "Slot for document type/category"
    },
    {
        "uri": "http://vital.ai/ontology/haley-ai-kg#DocumentDateSlot",
        "name": "DocumentDateSlot",
        "parent_class": "http://vital.ai/ontology/haley-ai-kg#KGDateSlot",
        "description": "Slot for document date"
    },
    {
        "uri": "http://vital.ai/ontology/haley-ai-kg#DocumentTitleSlot",
        "name": "DocumentTitleSlot",
        "parent_class": "http://vital.ai/ontology/haley-ai-kg#KGTextSlot",
        "description": "Slot for document title"
    }
]
```

### Entity Types
**Note:** File nodes are NOT KGEntity types. They are separate file resources managed through the files endpoint, not the kgentities endpoint. No new entity types need to be created for file support.

## Modifications to Existing Test Cases

### `case_kgtypes_operations.py`
- Add file-related frame types to the creation list
- Add file-related slot types to the creation list
- **Note:** No entity types needed - files are not KGEntities

### `case_create_organizations.py`
**MAJOR MODIFICATION:** Add file reference frames to organization entity graphs

**Current Structure:**
```python
# Organization entity with basic frames
org_entity = {
    "entity": {...},
    "frames": [
        # Existing frames (e.g., BusinessInfoFrame)
    ]
}
```

**New Structure:**
```python
# Organization entity with file reference frames
org_entity = {
    "entity": {...},
    "frames": [
        # Existing frames
        # NEW: File reference frames
        {
            "frame_type": "BusinessContractFrame",
            "slots": [
                {"slot_type": "DocumentFileURISlot", "value": file_uris["contract_1"]},
                {"slot_type": "DocumentTypeSlot", "value": "Service Agreement"},
                {"slot_type": "DocumentDateSlot", "value": "2024-01-15"}
            ]
        }
    ]
}
```

**File-to-Organization Mapping:**
- Org 1 (TechCorp Industries): Contract + Technical docs
- Org 2 (Global Finance Group): Contract + Financial reports
- Org 3 (Healthcare Solutions): Contract + Legal docs
- Org 4 (Energy Dynamics): Technical + Financial docs
- Org 5 (Retail Innovations): Marketing materials
- Org 6 (Manufacturing Corp): Technical docs
- Org 7 (Transportation Networks): Contract
- Org 8 (Media & Entertainment): Marketing materials
- Org 9 (Biotech Research Labs): Legal + Technical docs
- Org 10 (Consulting Partners): Financial reports

**Input Required:**
- `file_uris`: Dictionary of file URIs from upload step
- Must be passed to `run_tests()` method

**Tests:**
- Verify frames with file references are created
- Verify slot values contain correct file URIs

### `case_create_business_events.py`
**MODIFICATION:** Add file references to business event frames

**Input Required:**
- `file_uris`: Dictionary of file URIs from upload step

**Example File References:**
- Purchase events: Invoice/receipt files
- Contract events: Contract document files
- Report events: Report document files

**Tests:**
- Verify event frames include file references where appropriate

### `case_kgquery_frame_queries.py`
**ADDITION:** Add test for querying by file references

**New Tests:**
- Test 5: Find organizations with contract documents
- Test 6: Find organizations with specific file URI
- Test 7: Multi-frame query - orgs with contracts AND technical docs

**Input Required:**
- `file_uris`: Dictionary to construct queries

## Test Data Requirements

### Source Files
- **Location:** `/Users/hadfield/Local/vital-git/vital-graph/test_files/`
- **Current files:** 2 PDFs
- **Required:** 10 PDFs with different purposes

**Strategy:**
1. Use existing 2 PDFs as-is
2. Create symbolic links or copies with different names to simulate 10 different documents
3. Assign different purposes/categories to each

### File Naming Convention
```
contract_techcorp.pdf
contract_globalfinance.pdf
contract_healthcare.pdf
financial_report_q1.pdf
financial_report_q2.pdf
marketing_brochure_retail.pdf
marketing_presentation_media.pdf
technical_spec_energy.pdf
technical_spec_biotech.pdf
legal_agreement_healthcare.pdf
```

## Expected Test Results

### Resource Counts
- **KGEntities:** 20 total
  - Organizations: 10
  - Business Events: 10
- **File Nodes:** 10 (separate file resources, NOT KGEntities)
- **Total Resources: 30** (20 entities + 10 files)

### Frame Counts (per entity type)
- Organizations: ~2-3 frames each (including file reference frames)
- Business Events: 2 frames each
- File Nodes: 0 frames (files are referenced, not containers)

### Expected Test Metrics
- File upload success rate: 100% (10/10)
- File-entity linking success: 100% (10/10 organizations)
- File download success: 100% (10/10)
- Query by file reference: Should find appropriate entities
- File deletion: 100% (10/10)

## Implementation Order

1. **Update `case_kgtypes_operations.py`**
   - Add new frame types, slot types, entity types

2. **Create `case_upload_files.py`**
   - Implement file upload logic
   - Test with 10 PDFs
   - Return file URIs dictionary

3. **Update `case_create_organizations.py`**
   - Accept `file_uris` parameter
   - Add file reference frames to entity graphs
   - Map files to appropriate organizations

4. **Update `case_create_business_events.py`**
   - Accept `file_uris` parameter (optional)
   - Add file references to event frames where appropriate

5. **Create `case_download_files.py`**
   - Implement download and verification
   - Accept `file_uris` parameter

6. **Update `case_kgquery_frame_queries.py`**
   - Add KGQuery tests for file references
   - Accept `file_uris` parameter

7. **Create `case_delete_files.py`**
   - Implement file deletion and cleanup
   - Accept `file_uris` parameter

8. **Update `test_multiple_organizations_crud.py`**
   - Integrate new test cases in correct order
   - Pass `file_uris` between test cases
   - Update entity count expectations (20 KGEntities: 10 orgs + 10 events)
   - Note: File nodes are separate resources, not counted in KGEntity lists
   - Update test flow documentation

## Questions for Discussion

1. **File Storage:** Should we verify actual file storage on disk, or just API-level operations?

2. **File Duplication:** Is it acceptable to use the same 2 PDFs with different names/metadata, or should we create/find 10 unique PDFs?

3. **Business Events:** Should business events also reference files (e.g., invoices, receipts), or only organizations?
   - **Recommendation:** Yes, add file references to events (invoices for purchases, receipts for transactions)

4. **Cleanup Strategy:** Should file deletion happen before or after entity deletion? Should frames be removed before files?
   - **Recommendation:** Delete files AFTER entities are deleted (files are referenced by entities)

5. **Error Cases:** How many error/negative test cases should we include (e.g., upload invalid file, download non-existent file)?
   - **Recommendation:** Include at least 1-2 error cases (download non-existent file, verify deleted file)

6. **File Metadata:** What metadata should we track? (file size, content type, upload date, checksum, etc.)
   - **Recommendation:** Track file size, content type, file name at minimum

7. **Query Complexity:** Should we test complex queries like "organizations with contracts AND financial reports"?
   - **Recommendation:** Yes, add multi-frame query test for file references

8. **Performance:** Should we test bulk file operations (upload/download multiple files at once)?
   - **Recommendation:** Start with individual operations, add bulk if time permits

9. **Versioning:** Should we test file versioning (uploading new version of same document)?
   - **Recommendation:** Skip versioning for initial implementation, can add later

## Success Criteria

- All file uploads succeed
- All file-entity links are created correctly
- All files can be downloaded and verified
- KGQuery can find entities by file references
- All files can be deleted cleanly
- No orphaned references after deletion
- Test suite maintains 95%+ pass rate
- Total test count increases to ~85-90 tests (from current 67)

## Risks and Mitigation

### Risk 1: File Storage Issues
- **Mitigation:** Verify file endpoint is working before integration

### Risk 2: Large Test Files
- **Mitigation:** Use small PDFs (<1MB each) for testing

### Risk 3: Test Execution Time
- **Mitigation:** File operations may slow down test suite; consider parallel uploads if needed

### Risk 4: Cleanup Failures
- **Mitigation:** Ensure robust cleanup in finally blocks; verify files deleted even on test failure

### Risk 5: Frame Reference Integrity
- **Mitigation:** Verify frame-slot-file reference chain is correct before proceeding to next test

## Timeline Estimate

- Planning & Discussion: 30 minutes
- Implementation: 3-4 hours
  - KGTypes update: 30 minutes
  - Upload case: 45 minutes
  - Link case: 45 minutes
  - Download case: 30 minutes
  - Query case: 45 minutes
  - Delete case: 30 minutes
  - Integration & testing: 45 minutes
- Testing & Refinement: 1 hour
- **Total: 4-5 hours**
