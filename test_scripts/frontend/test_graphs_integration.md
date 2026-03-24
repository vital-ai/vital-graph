# Frontend Graphs Integration Test Plan

## Overview
This document outlines the testing approach for the newly integrated Graphs frontend components that now connect to the VitalGraph backend APIs.

## Components Updated

### 1. Graphs.tsx - Main Graphs List Page
**Backend Integration:**
- ✅ Space dropdown now fetches from `/api/spaces`
- ✅ Graph listing now fetches from `/api/graphs/sparql/{spaceId}/graphs`
- ✅ Search functionality filters graphs client-side
- ✅ Delete functionality uses `/api/graphs/sparql/{spaceId}/graph/{graphUri}` DELETE
- ✅ Navigation to graph details passes correct parameters

### 2. GraphDetail.tsx - Graph Details/Edit Page
**Backend Integration:**
- ✅ Graph data fetching from `/api/graphs/sparql/{spaceId}/graphs`
- ✅ Space info fetching from `/api/spaces`
- ✅ Graph creation uses `/api/graphs/sparql/{spaceId}/graph/{graphUri}` PUT
- ✅ Graph deletion uses `/api/graphs/sparql/{spaceId}/graph/{graphUri}` DELETE
- ✅ Graph purging uses `/api/graphs/sparql/{spaceId}/graph` POST with CLEAR operation

### 3. ApiService.ts - API Client
**New Methods Added:**
- ✅ `getGraphs(spaceId)` - Get all graphs in a space
- ✅ `getGraph(spaceId, graphUri)` - Get specific graph info
- ✅ `createGraph(spaceId, graphUri)` - Create new graph
- ✅ `deleteGraph(spaceId, graphUri, silent)` - Delete graph
- ✅ `executeGraphOperation(spaceId, operation, targetGraphUri, sourceGraphUri, silent)` - Execute graph operations

## Manual Testing Checklist

### Prerequisites
1. ✅ VitalGraph backend server running
2. ✅ Frontend development server running
3. ✅ At least one space created in the system
4. ✅ User authenticated and logged in

### Test Cases

#### TC1: Space Selection and Graph Loading
1. Navigate to `/graphs` or `/space/{spaceId}/graphs`
2. Verify space dropdown loads available spaces from backend
3. Select a space and verify graphs load for that space
4. Verify loading states and error handling

**Expected Results:**
- Space dropdown populated with real backend data
- Graph list shows actual graphs from selected space
- Loading spinners appear during API calls
- Error messages shown if API calls fail

#### TC2: Graph Search and Filtering
1. Select a space with multiple graphs
2. Enter search terms in the search box
3. Click search or press Enter
4. Verify results are filtered correctly

**Expected Results:**
- Search filters graphs by name and URI
- Results update in real-time
- Empty state shown when no matches found

#### TC3: Graph Creation
1. Navigate to `/space/{spaceId}/graph/new`
2. Fill in graph details (name, URI, type, description)
3. Click Save
4. Verify graph is created and user redirected

**Expected Results:**
- Form validation works correctly
- API call creates graph in backend
- Success message displayed
- Redirect to graphs list after creation

#### TC4: Graph Details View
1. Navigate to existing graph details page
2. Verify all graph information loads correctly
3. Test edit functionality (note: updates not yet supported)
4. Verify breadcrumb navigation works

**Expected Results:**
- Graph details load from backend
- Edit form populated with current values
- Breadcrumbs show correct navigation path

#### TC5: Graph Deletion
1. From graphs list, click delete button on a graph
2. Confirm deletion in dialog
3. Verify graph is removed from backend and list updates

**Expected Results:**
- Confirmation dialog appears
- Graph deleted from backend
- Graph list refreshes automatically
- Success message displayed

#### TC6: Graph Purging
1. Navigate to graph details page
2. Click purge button
3. Confirm purge operation
4. Verify graph content is cleared

**Expected Results:**
- Confirmation dialog appears
- CLEAR operation executed on backend
- Success message displayed
- Graph remains but content cleared

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
- Test with invalid graph URIs
- Test with empty required fields
- Test with duplicate graph names

## Performance Considerations

### Loading Performance
- Graph list should load within 2 seconds
- Search results should appear within 1 second
- Navigation between pages should be smooth

### Data Efficiency
- API calls should be minimized
- Caching should be used where appropriate
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

## Accessibility

Ensure the interface meets accessibility standards:
- Keyboard navigation works
- Screen reader compatibility
- Proper ARIA labels
- Color contrast compliance

## Integration Points

### Backend Dependencies
- Spaces API must be available
- Graphs API must be available
- Authentication system must be working
- SPARQL query engine must be operational

### Frontend Dependencies
- React Router for navigation
- Flowbite React components
- Authentication context
- API service layer

## Known Limitations

1. **Graph Updates**: Backend API doesn't support graph metadata updates yet
2. **Real-time Updates**: No WebSocket integration for live updates
3. **Bulk Operations**: No support for bulk graph operations
4. **Advanced Search**: Only basic text search implemented
5. **Graph Visualization**: No graph visualization components yet

## Future Enhancements

1. **Real-time Updates**: Add WebSocket support for live graph updates
2. **Advanced Filtering**: Add filters by graph type, creation date, size
3. **Bulk Operations**: Support selecting and operating on multiple graphs
4. **Graph Statistics**: Show more detailed graph statistics and metrics
5. **Graph Visualization**: Add graph visualization and exploration tools
6. **Export/Import**: Support for graph export and import operations

## Success Criteria

The integration is considered successful when:
- ✅ All API calls work correctly with real backend
- ✅ Error handling provides good user experience
- ✅ Loading states are smooth and informative
- ✅ Navigation between pages works seamlessly
- ✅ CRUD operations (Create, Read, Delete) function properly
- ✅ Search and filtering work as expected
- ✅ Mobile responsiveness is maintained
- ✅ No console errors or warnings
