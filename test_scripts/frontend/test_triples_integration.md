# Frontend Triples Integration Test Plan

## Overview
This document outlines the testing approach for the newly integrated Triples frontend component that now connects to the VitalGraph backend APIs.

## Components Updated

### 1. Triples.tsx - Main Triples Management Page
**Backend Integration:**
- ✅ Space dropdown now fetches from `/api/spaces`
- ✅ Graph dropdown now fetches from `/api/graphs/sparql/{spaceId}/graphs`
- ✅ Triples listing now fetches from `/api/graphs/triples` with pagination
- ✅ Add triple functionality uses `/api/graphs/triples` POST with JSON-LD
- ✅ Edit triple functionality uses DELETE + POST operations
- ✅ Delete triple functionality uses `/api/graphs/triples` DELETE with JSON-LD
- ✅ Search functionality uses `object_filter` parameter

### 2. ApiService.ts - API Client
**New Methods Added:**
- ✅ `getTriples(spaceId, graphId, options)` - Get paginated triples with filtering
- ✅ `addTriples(spaceId, graphId, document)` - Add triples via JSON-LD document
- ✅ `deleteTriples(spaceId, graphId, document)` - Delete triples via JSON-LD document

## Manual Testing Checklist

### Prerequisites
1. ✅ VitalGraph backend server running
2. ✅ Frontend development server running
3. ✅ At least one space with graphs created (e.g., WordNet data)
4. ✅ User authenticated and logged in

### Test Cases

#### TC1: Space and Graph Selection
1. Navigate to `/triples` page
2. Verify space dropdown loads available spaces from backend
3. Select a space and verify graphs load for that space
4. Select a graph and verify triples start loading
5. Verify loading states and error handling

**Expected Results:**
- Space dropdown populated with real backend data
- Graph dropdown shows actual graphs from selected space
- Loading spinners appear during API calls
- Error messages shown if API calls fail

#### TC2: Triples Display and Pagination
1. Select a space with graphs containing triples (e.g., WordNet space)
2. Verify triples are displayed in table format
3. Test pagination controls (next/previous page)
4. Change items per page and verify results update
5. Verify triple data shows subject, predicate, object, type

**Expected Results:**
- Triples displayed in readable table format
- Pagination works correctly with backend data
- Subject, predicate, object values are properly formatted
- Object type (URI/Literal) is correctly identified and displayed

#### TC3: Triple Search and Filtering
1. Select a graph with multiple triples
2. Enter search terms in the search box
3. Verify results are filtered by object content
4. Clear search and verify all triples return
5. Test with various search terms

**Expected Results:**
- Search filters triples based on object content
- Results update in real-time as you type
- Empty state shown when no matches found
- Pagination adjusts based on filtered results

#### TC4: Add New Triple
1. Click "Add Triple" button
2. Fill in subject, predicate, object fields
3. Select object type (URI or Literal)
4. Click "Add Triple" and verify success
5. Verify new triple appears in the list

**Expected Results:**
- Add modal opens with proper form fields
- Form validation works correctly
- Triple is added to backend via JSON-LD
- Triples list refreshes to show new triple
- Success feedback provided to user

#### TC5: Edit Existing Triple
1. Click edit button on an existing triple
2. Modify the subject, predicate, or object
3. Change object type if needed
4. Click "Save Changes" and verify update
5. Verify changes appear in the list

**Expected Results:**
- Edit modal opens with current triple values
- Form allows modification of all fields
- Backend receives delete + add operations
- Triples list refreshes with updated data
- Success feedback provided to user

#### TC6: Delete Triple
1. Click delete button on an existing triple
2. Confirm deletion in dialog
3. Verify triple is removed from backend and list updates
4. Test canceling deletion

**Expected Results:**
- Confirmation dialog appears
- Triple deleted from backend via JSON-LD
- Triples list refreshes automatically
- Success message displayed

## Data Format Testing

### JSON-LD Conversion
The frontend converts between Triple format and JSON-LD:

**Frontend Triple Format:**
```typescript
{
  id: number,
  space_id: string,
  graph_id: number,
  subject: string,
  predicate: string,
  object: string,
  object_type: 'uri' | 'literal',
  created_time: string,
  last_modified: string
}
```

**JSON-LD Format (sent to backend):**
```json
{
  "@context": {
    "@vocab": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
  },
  "@graph": [
    {
      "@id": "subject_uri",
      "predicate_uri": {
        "@id": "object_uri"  // for URI objects
      }
    }
  ]
}
```

**JSON-LD Format (for literals):**
```json
{
  "@context": {
    "@vocab": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
  },
  "@graph": [
    {
      "@id": "subject_uri",
      "predicate_uri": "literal_value"  // for literal objects
    }
  ]
}
```

## Error Scenarios to Test

### Network Errors
- Test with backend server down
- Test with slow network connections
- Test with intermittent connectivity

### Authentication Errors
- Test with expired tokens
- Test with invalid credentials
- Verify automatic token refresh works

### Data Validation Errors
- Test with invalid URIs
- Test with empty required fields
- Test with malformed JSON-LD

### Backend Errors
- Test with non-existent spaces
- Test with non-existent graphs
- Test with invalid triple data

## Performance Considerations

### Loading Performance
- Triples list should load within 2 seconds
- Pagination should be responsive
- Search results should appear within 1 second

### Data Efficiency
- API calls should use proper pagination
- Search should use backend filtering
- Loading states should provide good UX

## Browser Compatibility

Test in the following browsers:
- Chrome (latest)
- Firefox (latest)
- Safari (latest)
- Edge (latest)

## Mobile Responsiveness

Verify the interface works correctly on:
- Desktop (1920x1080)
- Tablet (768x1024)
- Mobile (375x667)

## Integration Points

### Backend Dependencies
- Spaces API must be available
- Graphs API must be available
- Triples API must be available
- Authentication system must be working

### Frontend Dependencies
- React Router for navigation
- Flowbite React components
- Authentication context
- API service layer

## Known Limitations

1. **Edit Operations**: Requires delete + add (no atomic update)
2. **Bulk Operations**: No support for bulk triple operations
3. **Advanced Search**: Only basic object text search implemented
4. **Triple Validation**: Limited URI and literal validation
5. **Performance**: Large graphs may have slow pagination

## Success Criteria

The integration is considered successful when:
- ✅ All API calls work correctly with real backend
- ✅ CRUD operations (Create, Read, Update, Delete) function properly
- ✅ Pagination works with backend data
- ✅ Search and filtering work as expected
- ✅ JSON-LD conversion works correctly
- ✅ Error handling provides good user experience
- ✅ Loading states are smooth and informative
- ✅ Navigation between pages works seamlessly
- ✅ Mobile responsiveness is maintained
- ✅ No console errors or warnings

## Test Data Requirements

### Recommended Test Setup
1. **Space with WordNet Data**: Use the space created by the import script
   - Space ID: `test_4847` (or similar)
   - Graph: `urn:kgframe-wordnet-002` with 8.5M triples
   
2. **Small Test Space**: Create a space with manageable data
   - Few hundred triples for testing pagination
   - Mix of URI and literal objects
   - Various predicate types

### Sample Test Triples
```turtle
<http://example.org/person1> <http://schema.org/name> "John Doe" .
<http://example.org/person1> <http://schema.org/age> "30"^^<http://www.w3.org/2001/XMLSchema#integer> .
<http://example.org/person1> <http://schema.org/knows> <http://example.org/person2> .
<http://example.org/person2> <http://schema.org/name> "Jane Smith" .
```

## Future Enhancements

1. **Advanced Search**: Add filters by subject, predicate, object type
2. **Bulk Operations**: Support selecting and operating on multiple triples
3. **Triple Validation**: Add URI validation and datatype checking
4. **Export/Import**: Support for triple export and import operations
5. **Visualization**: Add graph visualization for triple relationships
6. **Performance**: Implement virtual scrolling for large datasets
7. **Real-time Updates**: Add WebSocket support for live triple updates
