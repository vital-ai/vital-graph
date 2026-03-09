import React, { useState, useEffect, useCallback } from 'react';
import { useOutletContext, useNavigate } from 'react-router-dom';
import axios from 'axios';
import {
  Button,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeadCell,
  TableRow,
  Alert,
  TextInput,
  Select,
  Label,
  Pagination,
  Badge,
  Spinner,
  Modal
} from 'flowbite-react';
import { HiPlus, HiEye, HiTrash } from 'react-icons/hi2';
import { HiSearch } from 'react-icons/hi';

interface RDFObject {
  id: number;
  object_uri: string;
  object_type: string;
  rdf_type: string;
  properties_count: number;
  last_modified: string;
}

const GraphObjects: React.FC = () => {
  const navigate = useNavigate();
  
  // Get shared state from parent ObjectsLayout
  const context = useOutletContext<{
    selectedSpace: string;
    selectedGraph: string;
    spacesLoading: boolean;
    graphsLoading: boolean;
    error: string | null;
  }>();

  // Handle case where context might be undefined initially
  const {
    selectedSpace = '',
    selectedGraph = '',
    spacesLoading = true,
  } = context || {};

  // Local state management
  const [objects, setObjects] = useState<RDFObject[]>([]);
  const [filteredObjects, setFilteredObjects] = useState<RDFObject[]>([]);
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [itemsPerPage, setItemsPerPage] = useState<number>(10);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [showDeleteModal, setShowDeleteModal] = useState<boolean>(false);
  const [objectToDelete, setObjectToDelete] = useState<RDFObject | null>(null);
  const [totalCount, setTotalCount] = useState<number>(0);

  // No longer need navigation logic - handled by parent ObjectsLayout

  // Spaces and graphs are now managed by parent ObjectsLayout

  // Fetch objects for selected space and graph
  const fetchObjects = useCallback(async () => {
    if (!selectedSpace || !selectedGraph) return;
    
    try {
      setLoading(true);
      setError('');
      
      const graphUri = selectedGraph;
      
      console.log('Fetching objects for space:', selectedSpace, 'graph:', graphUri);
      
      // Call the actual objects API endpoint using axios (handles auth automatically)
      const response = await axios.get('/api/graphs/objects', {
        params: {
          space_id: selectedSpace,
          graph_id: graphUri,
          page_size: itemsPerPage,
          offset: (currentPage - 1) * itemsPerPage
        }
      });
      
      const data = response.data;
      console.log('Objects API response:', data);
      
      // API returns QuadResponse: { results: [{s, p, o, g}, ...], total_count, page_size, offset }
      const quads: Array<{s: string; p: string; o: string; g?: string}> = data.results || [];
      
      // Group quads by subject to form objects
      const subjectMap = new Map<string, { predicates: Map<string, string[]> }>();
      for (const quad of quads) {
        const subj = quad.s.replace(/^<|>$/g, ''); // strip angle brackets
        if (!subjectMap.has(subj)) {
          subjectMap.set(subj, { predicates: new Map() });
        }
        const entry = subjectMap.get(subj)!;
        const pred = quad.p.replace(/^<|>$/g, '');
        if (!entry.predicates.has(pred)) {
          entry.predicates.set(pred, []);
        }
        entry.predicates.get(pred)!.push(quad.o);
      }
      
      const RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type';
      const transformedObjects: RDFObject[] = [];
      let idx = 0;
      for (const [subjectUri, { predicates }] of subjectMap) {
        const typeValues = predicates.get(RDF_TYPE) || [];
        const rdfType = typeValues.length > 0
          ? typeValues[0].replace(/^<|>$/g, '')
          : 'Unknown';
        
        transformedObjects.push({
          id: idx++,
          object_uri: subjectUri,
          object_type: rdfType.toLowerCase().includes('edge') ? 'Edge' : 'Node',
          rdf_type: rdfType,
          last_modified: new Date().toISOString(),
          properties_count: predicates.size,
        });
      }
      
      setObjects(transformedObjects);
      setError(null);
      setTotalCount(data.total_count ?? transformedObjects.length);
      console.log(`Total objects: ${data.total_count}, showing ${transformedObjects.length}`);
      
    } catch (err) {
      console.error('Error fetching objects:', err);
      setError('Failed to load objects. Please try again later.');
      setObjects([]);
    } finally {
      setLoading(false);
    }
  }, [selectedSpace, selectedGraph, itemsPerPage, currentPage]);

  // Filter objects based on search term
  useEffect(() => {
    const filtered = objects.filter(obj =>
      obj.object_uri.toLowerCase().includes(searchTerm.toLowerCase()) ||
      obj.rdf_type.toLowerCase().includes(searchTerm.toLowerCase()) ||
      obj.object_type.toLowerCase().includes(searchTerm.toLowerCase())
    );
    setFilteredObjects(filtered);
    setCurrentPage(1);
  }, [objects, searchTerm, itemsPerPage]);

  useEffect(() => {
    fetchObjects();
    // Reset pagination when component mounts or tab becomes active
    setCurrentPage(1);
  }, [fetchObjects]);

  // Pagination — server-side when not filtering, client-side when searching
  const isSearching = searchTerm.length > 0;
  const totalPages = isSearching
    ? Math.ceil(filteredObjects.length / itemsPerPage)
    : Math.ceil(totalCount / itemsPerPage);
  const currentObjects = isSearching
    ? filteredObjects.slice((currentPage - 1) * itemsPerPage, currentPage * itemsPerPage)
    : filteredObjects;

  // Utility functions
  const extractLocalName = (uri: string): string => {
    if (!uri) return '';
    const parts = uri.split(/[#/]/);
    return parts[parts.length - 1] || uri;
  };

  const formatDateTime = (dateString: string): string => {
    return new Date(dateString).toLocaleString();
  };

  const getObjectTypeBadge = (type: string) => {
    const config = type === 'Node' 
      ? { color: 'blue', text: 'Node' }
      : { color: 'green', text: 'Edge' };
    return <Badge color={config.color}>{config.text}</Badge>;
  };

  return (
    <>

      {/* Add Object Button */}
      {selectedSpace && selectedGraph && (
        <div className="mb-6">
          <Button 
            onClick={() => {
              navigate(`/space/${selectedSpace}/graph/${encodeURIComponent(selectedGraph)}/objects/new?mode=create`);
            }} 
            color="blue"
          >
            <HiPlus className="mr-2 h-4 w-4" />
            Add Graph Object
          </Button>
        </div>
      )}

      {/* Search and Filter */}
      {selectedSpace && selectedGraph && (
        <div className="mb-6">
          <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-end">
            <div className="flex-1">
              <div className="relative">
                <HiSearch className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400" />
                <TextInput
                  type="text"
                  placeholder="Search objects by URI, type, or object type..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="pl-10"
                />
              </div>
            </div>
            <div className="flex-shrink-0">
              <Label htmlFor="page-size">Items per page</Label>
              <Select
                id="page-size"
                value={itemsPerPage}
                onChange={(e) => {
                  setItemsPerPage(parseInt(e.target.value));
                  setCurrentPage(1);
                }}
              >
                <option value={10}>10</option>
                <option value={20}>20</option>
                <option value={50}>50</option>
                <option value={100}>100</option>
              </Select>
            </div>
          </div>
        </div>
      )}

      {/* Selection Required Messages */}
      {!selectedSpace && !spacesLoading && (
        <div className="text-center py-12">
          <div className="text-gray-500 dark:text-gray-400">
            <p className="text-lg mb-2">Select a space to view graph objects</p>
            <p className="text-sm">Choose a space from the dropdown above to see available graphs.</p>
          </div>
        </div>
      )}
      
      {selectedSpace && !selectedGraph && (
        <div className="text-center py-12">
          <div className="text-gray-500 dark:text-gray-400">
            <p className="text-lg mb-2">Select a graph to view graph objects</p>
            <p className="text-sm">Choose a graph from the dropdown above to see its objects.</p>
          </div>
        </div>
      )}

      {/* Loading Spinner */}
      {selectedSpace && selectedGraph && loading && (
        <div className="mt-8 flex justify-center">
          <Spinner size="lg" />
          <span className="ml-2 text-gray-600 dark:text-gray-400">Loading graph objects...</span>
        </div>
      )}

      {error && (
        <Alert color="failure">
          {error}
        </Alert>
      )}

      {/* Objects Table */}
      {selectedSpace && selectedGraph && !loading && filteredObjects.length === 0 && !error ? (
        <Alert color="info">
          {searchTerm ? 
            `No graph objects found matching "${searchTerm}". Try a different search term.` :
            'No graph objects found in this graph. Add your first object to get started.'
          }
        </Alert>
      ) : selectedSpace && selectedGraph && !loading && currentObjects.length > 0 && (
        <>
          <div className="overflow-x-auto">
            <Table>
              <TableHead>
                <TableRow>
                  <TableHeadCell>Object URI</TableHeadCell>
                  <TableHeadCell>RDF Type</TableHeadCell>
                  <TableHeadCell>Object Type</TableHeadCell>
                  <TableHeadCell>Properties</TableHeadCell>
                  <TableHeadCell>Last Modified</TableHeadCell>
                  <TableHeadCell>Actions</TableHeadCell>
                </TableRow>
              </TableHead>
              <TableBody className="divide-y">
                {currentObjects.map((obj) => (
                  <TableRow key={obj.id}>
                    <TableCell className="font-medium">
                      <div className="max-w-xs">
                        <div className="font-mono text-sm text-blue-600 truncate">
                          {extractLocalName(obj.object_uri)}
                        </div>
                        <div className="text-xs text-gray-500 truncate">
                          {obj.object_uri}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell className="font-mono text-sm">
                      {extractLocalName(obj.rdf_type)}
                    </TableCell>
                    <TableCell>
                      {getObjectTypeBadge(obj.object_type)}
                    </TableCell>
                    <TableCell>
                      <span className="text-sm text-gray-600 dark:text-gray-400">
                        {obj.properties_count} properties
                      </span>
                    </TableCell>
                    <TableCell className="text-sm text-gray-600 dark:text-gray-400">
                      {formatDateTime(obj.last_modified)}
                    </TableCell>
                    <TableCell>
                      <div className="flex space-x-2">
                        <Button
                          size="xs"
                          color="blue"
                          onClick={() => {
                            navigate(`/space/${selectedSpace}/graph/${encodeURIComponent(selectedGraph)}/objects/${encodeURIComponent(obj.object_uri)}`);
                          }}
                        >
                          <HiEye className="h-3 w-3" />
                        </Button>
                        <Button
                          size="xs"
                          color="red"
                          onClick={() => {
                            setObjectToDelete(obj);
                            setShowDeleteModal(true);
                          }}
                        >
                          <HiTrash className="h-3 w-3" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex justify-center mt-6">
              <Pagination
                currentPage={currentPage}
                totalPages={totalPages}
                onPageChange={setCurrentPage}
                showIcons
              />
            </div>
          )}
        </>
      )}

      {/* Delete Confirmation Modal */}
      <Modal show={showDeleteModal} onClose={() => setShowDeleteModal(false)} size="md">
        <div className="p-6">
          <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">Delete Object</h3>
          <p className="text-gray-600 dark:text-gray-400 mb-6">
            Are you sure you want to delete this object? This action cannot be undone.
          </p>
          {objectToDelete && (
            <div className="bg-gray-50 dark:bg-gray-700 p-3 rounded mb-6">
              <p className="text-sm font-mono text-gray-800 dark:text-gray-200">
                {objectToDelete.object_uri}
              </p>
            </div>
          )}
          <div className="flex justify-end gap-3">
            <Button 
              onClick={() => {
                // Handle delete logic here
                console.log('Deleting object:', objectToDelete?.id);
                setShowDeleteModal(false);
                setObjectToDelete(null);
              }} 
              color="failure"
            >
              Delete
            </Button>
            <Button 
              color="gray" 
              onClick={() => {
                setShowDeleteModal(false);
                setObjectToDelete(null);
              }}
            >
              Cancel
            </Button>
          </div>
        </div>
      </Modal>
    </>
  );
};

export default GraphObjects;
