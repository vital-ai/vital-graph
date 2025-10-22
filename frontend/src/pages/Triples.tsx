import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Button,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeadCell,
  TableRow,
  Alert,
  TextInput,
  Pagination,
  Badge,
  Modal,
  Label,
  Textarea
} from 'flowbite-react';
import {
  HiPlus,
  HiPencil,
  HiTrash,
  HiSearch
} from 'react-icons/hi';
import { type Space, type Graph, type Triple } from '../mock';
import { type SpaceInfo, type GraphInfo } from '../types/api';
import { apiService } from '../services/ApiService';
import TriplesIcon from '../components/icons/TriplesIcon';
import NavigationBreadcrumb from '../components/NavigationBreadcrumb';

// Helper functions for data conversion (similar to Graphs.tsx)
const extractGraphName = (graphUri: string): string => {
  if (!graphUri) return 'Unknown Graph';
  
  const parts = graphUri.split(/[/#]/);
  const name = parts[parts.length - 1];
  
  if (!name || name.length === 0) {
    if (graphUri.includes('global')) return 'Global';
    if (graphUri.includes('default')) return 'Default';
    return 'Graph';
  }
  
  return name
    .replace(/[-_]/g, ' ')
    .replace(/\b\w/g, l => l.toUpperCase());
};

const inferGraphType = (graphUri: string): string => {
  if (!graphUri) return 'Graph';
  
  const uri = graphUri.toLowerCase();
  if (uri.includes('global')) return 'Global Graph';
  if (uri.includes('ontology')) return 'Ontology';
  if (uri.includes('knowledge')) return 'Knowledge Graph';
  if (uri.includes('user')) return 'User Graph';
  if (uri.includes('entity')) return 'Entity Graph';
  if (uri.includes('process') || uri.includes('workflow')) return 'Process Graph';
  if (uri.includes('experiment')) return 'Experimental Graph';
  if (uri.includes('data') || uri.includes('dataset')) return 'Data Graph';
  if (uri.includes('result') || uri.includes('analysis')) return 'Results Graph';
  
  return 'Graph';
};

const Triples: React.FC = () => {
  const navigate = useNavigate();
  const { spaceId, graphId } = useParams<{ spaceId?: string; graphId?: string }>();
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [selectedSpace, setSelectedSpace] = useState<string>(spaceId || '');
  const [spacesLoading, setSpacesLoading] = useState<boolean>(true);
  const [graphs, setGraphs] = useState<Graph[]>([]);
  const [selectedGraph, setSelectedGraph] = useState<string>(graphId ? decodeURIComponent(graphId) : '');

  // Navigate to hierarchical URL when space/graph selection changes
  useEffect(() => {
    if (selectedSpace && selectedGraph !== '' && !spaceId && !graphId) {
      navigate(`/space/${selectedSpace}/graph/${encodeURIComponent(selectedGraph)}/triples`);
    }
  }, [selectedSpace, selectedGraph, navigate, spaceId, graphId]);

  const [searchTerm, setSearchTerm] = useState<string>('');
  const [debouncedSearchTerm, setDebouncedSearchTerm] = useState<string>('');
  const [isSearching, setIsSearching] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(false);
  const [graphsLoading, setGraphsLoading] = useState<boolean>(false);
  const [triples, setTriples] = useState<Triple[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showAddModal, setShowAddModal] = useState<boolean>(false);
  const [showEditModal, setShowEditModal] = useState<boolean>(false);
  const [showDeleteModal, setShowDeleteModal] = useState<boolean>(false);
  const [editingTriple, setEditingTriple] = useState<Triple | null>(null);
  const [deletingTriple, setDeletingTriple] = useState<Triple | null>(null);
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [totalPages, setTotalPages] = useState<number>(1);
  const [itemsPerPage, setItemsPerPage] = useState<number>(10);

  // Form state for add/edit modals
  const [tripleForm, setTripleForm] = useState({
    subject: '',
    predicate: '',
    object: '',
    objectType: 'uri' as 'uri' | 'literal'
  });

  // Handler functions for modal operations
  const handleAddTriple = async () => {
    if (!tripleForm.subject || !tripleForm.predicate || !tripleForm.object) {
      return; // Basic validation
    }

    try {
      // Find the selected graph to get its URI
      const selectedGraphObj = graphs.find(g => g.graph_uri === selectedGraph);
      if (!selectedGraphObj) {
        setError('Selected graph not found');
        return;
      }

      // Create JSON-LD document for the triple
      const jsonldDoc = {
        "@context": {
          "@vocab": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        },
        "@graph": [
          {
            "@id": tripleForm.subject,
            [tripleForm.predicate]: tripleForm.objectType === 'uri' 
              ? { "@id": tripleForm.object }
              : tripleForm.object
          }
        ]
      };

      await apiService.addTriples(selectedSpace, selectedGraphObj.graph_uri, jsonldDoc);
      
      // Refresh triples list
      await fetchTriples();
      
      setTripleForm({ subject: '', predicate: '', object: '', objectType: 'uri' });
      setShowAddModal(false);
    } catch (err) {
      console.error('Error adding triple:', err);
      setError('Failed to add triple. Please try again.');
    }
  };

  const handleEditTriple = async () => {
    if (!editingTriple || !tripleForm.subject || !tripleForm.predicate || !tripleForm.object) {
      return; // Basic validation
    }

    try {
      // Find the selected graph to get its URI
      const selectedGraphObj = graphs.find(g => g.graph_uri === selectedGraph);
      if (!selectedGraphObj) {
        setError('Selected graph not found');
        return;
      }

      // For editing, we need to delete the old triple and add the new one
      // First, delete the old triple
      const oldJsonldDoc = {
        "@context": {
          "@vocab": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        },
        "@graph": [
          {
            "@id": editingTriple.subject,
            [editingTriple.predicate]: editingTriple.object_type === 'uri' 
              ? { "@id": editingTriple.object }
              : editingTriple.object
          }
        ]
      };

      await apiService.deleteTriples(selectedSpace, selectedGraphObj.graph_uri, oldJsonldDoc);

      // Then add the new triple
      const newJsonldDoc = {
        "@context": {
          "@vocab": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        },
        "@graph": [
          {
            "@id": tripleForm.subject,
            [tripleForm.predicate]: tripleForm.objectType === 'uri' 
              ? { "@id": tripleForm.object }
              : tripleForm.object
          }
        ]
      };

      await apiService.addTriples(selectedSpace, selectedGraphObj.graph_uri, newJsonldDoc);
      
      // Refresh triples list
      await fetchTriples();
      
      setTripleForm({ subject: '', predicate: '', object: '', objectType: 'uri' });
      setShowEditModal(false);
      setEditingTriple(null);
    } catch (err) {
      console.error('Error editing triple:', err);
      setError('Failed to edit triple. Please try again.');
    }
  };

  const handleEditClick = (triple: Triple) => {
    setEditingTriple(triple);
    setTripleForm({
      subject: triple.subject,
      predicate: triple.predicate,
      object: triple.object,
      objectType: triple.object_type
    });
    setShowEditModal(true);
  };

  const handleDeleteClick = (triple: Triple) => {
    setDeletingTriple(triple);
    setShowDeleteModal(true);
  };

  const handleConfirmDelete = async () => {
    if (!deletingTriple) return;

    try {
      // Find the selected graph to get its URI
      const selectedGraphObj = graphs.find(g => g.graph_uri === selectedGraph);
      if (!selectedGraphObj) {
        setError('Selected graph not found');
        return;
      }

      // Create JSON-LD document for the triple to delete
      const jsonldDoc = {
        "@context": {
          "@vocab": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        },
        "@graph": [
          {
            "@id": deletingTriple.subject,
            [deletingTriple.predicate]: deletingTriple.object_type === 'uri' 
              ? { "@id": deletingTriple.object }
              : deletingTriple.object
          }
        ]
      };

      await apiService.deleteTriples(selectedSpace, selectedGraphObj.graph_uri, jsonldDoc);
      
      // Refresh triples list
      await fetchTriples();
      
      setShowDeleteModal(false);
      setDeletingTriple(null);
    } catch (err) {
      console.error('Error deleting triple:', err);
      setError('Failed to delete triple. Please try again.');
    }
  };

  // Fetch available spaces
  const fetchSpaces = useCallback(async () => {
    try {
      setSpacesLoading(true);
      setError(null);
      
      const spacesData = await apiService.getSpaces();
      
      // Convert backend format to frontend format
      const convertedSpaces: Space[] = spacesData.map((space: SpaceInfo) => ({
        id: space.id || 0,
        tenant: space.tenant || 'default',
        space: space.space,
        space_name: space.space_name,
        description: space.space_description || '',
        created_time: space.created_time,
        last_modified: space.updated_time
      }));
      
      setSpaces(convertedSpaces);
    } catch (err) {
      console.error('Error fetching spaces:', err);
      setError('Failed to load spaces. Please try again later.');
      setSpaces([]);
    } finally {
      setSpacesLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSpaces();
  }, [fetchSpaces]);

  // Debounce search term to avoid excessive API calls
  useEffect(() => {
    if (searchTerm !== debouncedSearchTerm) {
      setIsSearching(true);
    }
    
    const timer = setTimeout(() => {
      setDebouncedSearchTerm(searchTerm);
      setIsSearching(false);
    }, 500); // 500ms delay

    return () => clearTimeout(timer);
  }, [searchTerm, debouncedSearchTerm]);

  // Fetch graphs for selected space
  const fetchGraphs = useCallback(async () => {
    if (!selectedSpace) {
      setGraphs([]);
      return;
    }

    try {
      setGraphsLoading(true);
      setError(null);
      
      const graphsData = await apiService.getGraphs(selectedSpace);
      
      // Convert backend format to frontend format
      const convertedGraphs: Graph[] = graphsData.map((graph: GraphInfo, index: number) => ({
        id: index,
        space_id: selectedSpace,
        graph_name: extractGraphName(graph.graph_uri),
        graph_uri: graph.graph_uri,
        graph_type: inferGraphType(graph.graph_uri),
        triple_count: graph.triple_count || 0,
        created_time: graph.created_time || new Date().toISOString(),
        last_modified: graph.updated_time || new Date().toISOString(),
        description: `Graph containing ${graph.triple_count || 0} triples`,
        status: 'active'
      }));
      
      setGraphs(convertedGraphs);
    } catch (err) {
      console.error('Error fetching graphs:', err);
      setError('Failed to load graphs. Please try again later.');
      setGraphs([]);
    } finally {
      setGraphsLoading(false);
    }
  }, [selectedSpace]);

  useEffect(() => {
    fetchGraphs();
    if (!graphId) {
      setSelectedGraph('');
    }
  }, [fetchGraphs, graphId]);



  // Fetch triples for selected space and graph
  const fetchTriples = useCallback(async () => {
    if (!selectedSpace || selectedGraph === '') return;
    
    try {
      setLoading(true);
      setError(null);
      
      // Find the selected graph to get its URI
      const selectedGraphObj = graphs.find(g => g.graph_uri === selectedGraph);
      if (!selectedGraphObj) {
        setError('Selected graph not found');
        setLoading(false);
        return;
      }
      
      const offset = (currentPage - 1) * itemsPerPage;
      
      // Fetch triples from backend
      const response = await apiService.getTriples(selectedSpace, selectedGraphObj.graph_uri, {
        page_size: itemsPerPage,
        offset: offset,
        object_filter: debouncedSearchTerm || undefined
      });
      
      // Convert JSON-LD response to Triple format
      const convertedTriples: Triple[] = [];
      let tripleId = offset + 1;
      
      if (response.data && response.data['@graph']) {
        for (const item of response.data['@graph']) {
          const subject = item['@id'];
          
          // Extract all properties as triples
          for (const [predicate, objectValue] of Object.entries(item)) {
            if (predicate === '@id' || predicate === '@type') continue;
            
            let object: string;
            let objectType: 'uri' | 'literal';
            
            if (typeof objectValue === 'object' && objectValue !== null) {
              if ('@id' in objectValue) {
                object = String((objectValue as any)['@id']);
                objectType = 'uri';
              } else if ('@value' in objectValue) {
                object = String((objectValue as any)['@value']);
                objectType = 'literal';
              } else {
                object = JSON.stringify(objectValue);
                objectType = 'literal';
              }
            } else {
              object = String(objectValue);
              objectType = 'literal';
            }
            
            convertedTriples.push({
              id: tripleId++,
              space_id: selectedSpace,
              graph_id: selectedGraphObj.id,
              subject: subject,
              predicate: predicate,
              object: object,
              object_type: objectType,
              created_time: new Date().toISOString(),
              last_modified: new Date().toISOString()
            });
          }
        }
      }
      
      setTriples(convertedTriples);
      
      // Calculate total pages from pagination info
      if (response.pagination) {
        const totalPages = response.pagination.pages || 1;
        setTotalPages(totalPages);
      } else {
        setTotalPages(1);
      }
      
    } catch (err) {
      console.error('Error fetching triples:', err);
      setError('Failed to load triples. Please try again later.');
      setTriples([]);
      setTotalPages(1);
    } finally {
      setLoading(false);
    }
  }, [selectedSpace, selectedGraph, debouncedSearchTerm, currentPage, itemsPerPage, graphs]);

  useEffect(() => {
    fetchTriples();
  }, [fetchTriples]);

  return (
    <div className="space-y-6">
      <NavigationBreadcrumb
        spaceId={spaceId}
        graphId={graphId}
        currentPageName="Triples"
        currentPageIcon={TriplesIcon}
      />

      <div className="mb-6">
        <div className="flex items-center gap-2 mb-4">
          <TriplesIcon className="w-6 h-6 text-blue-600" />
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Triples</h1>
        </div>
      </div>

      {/* Space and Graph Selection */}
      <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-end mb-6">
        <div className="flex-1 max-w-xs">
          <Label htmlFor="space-select">Select Space</Label>
          <Select
            id="space-select"
            value={selectedSpace}
            onChange={(e) => {
              setSelectedSpace(e.target.value);
              setSelectedGraph(''); // Clear graph selection when space changes
            }}
            disabled={spacesLoading}
          >
            <option value="">Choose a space...</option>
            {spaces.map((space) => (
              <option key={space.space} value={space.space}>
                {space.space_name}
              </option>
            ))}
          </Select>
        </div>

        <div className="flex-1 max-w-xs">
          <Label htmlFor="graph-select">Select Graph</Label>
          <Select
            id="graph-select"
            value={selectedGraph}
            onChange={(e) => setSelectedGraph(e.target.value)}
            disabled={!selectedSpace || graphsLoading}
          >
            <option value="">Choose a graph...</option>
            {graphs.map((graph) => (
              <option key={graph.id} value={graph.graph_uri}>
                {graph.graph_name}
              </option>
            ))}
          </Select>
        </div>
      </div>

      {/* Add Triple Button */}
      {selectedSpace && selectedGraph !== '' && (
        <div className="mb-6">
          <Button onClick={() => setShowAddModal(true)} color="blue">
            <HiPlus className="mr-2 h-4 w-4" />
            Add Triple
          </Button>
        </div>
      )}

      {/* Search and Filter */}
      {selectedSpace && selectedGraph !== '' && (
        <div className="mb-6">
          <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-end">
            <div className="flex-1">
              <div className="relative">
                <HiSearch className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400" />
                <TextInput
                  type="text"
                  placeholder="Search triples by subject, predicate, or object..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="pl-10"
                />
                {isSearching && (
                  <div className="absolute right-3 top-1/2 transform -translate-y-1/2">
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-600"></div>
                  </div>
                )}
              </div>
            </div>
            <div className="flex-shrink-0">
              <Label htmlFor="page-size">Items per page</Label>
              <Select
                id="page-size"
                value={itemsPerPage}
                onChange={(e) => {
                  setItemsPerPage(parseInt(e.target.value));
                  setCurrentPage(1); // Reset to first page when changing page size
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

      {/* Error Message */}
      {error && (
        <Alert color="failure" className="mb-6">
          {error}
        </Alert>
      )}

      {/* Selection Required Messages */}
      {!selectedSpace && !spacesLoading && (
        <div className="text-center py-12">
          <div className="text-gray-500 dark:text-gray-400">
            <p className="text-lg mb-2">Select a space to view triples</p>
            <p className="text-sm">Choose a space from the dropdown above to see available graphs.</p>
          </div>
        </div>
      )}
      
      {selectedSpace && selectedGraph === '' && !graphsLoading && (
        <div className="text-center py-12">
          <div className="text-gray-500 dark:text-gray-400">
            <p className="text-lg mb-2">Select a graph to view triples</p>
            <p className="text-sm">Choose a graph from the dropdown above to see its RDF triples.</p>
          </div>
        </div>
      )}

      {/* Loading Spinner for Triples */}
      {selectedSpace && selectedGraph !== '' && loading && (
        <div className="mt-8 flex justify-center">
          <div className="text-gray-600 dark:text-gray-400">Loading triples...</div>
        </div>
      )}

      {/* Triples Table */}
      {selectedSpace && selectedGraph !== '' && !loading && triples.length === 0 && !error ? (
        <Alert color="info">
          {debouncedSearchTerm ? 
            `No triples found matching "${debouncedSearchTerm}". Try a different search term.` :
            'No triples found in this graph. Add your first triple to get started.'
          }
        </Alert>
      ) : selectedSpace && selectedGraph !== '' && !loading && triples.length > 0 && (
        <>
          <div className="overflow-x-auto">
            <Table striped>
              <TableHead>
                <TableRow>
                  <TableHeadCell>Subject</TableHeadCell>
                  <TableHeadCell>Predicate</TableHeadCell>
                  <TableHeadCell>Object</TableHeadCell>
                  <TableHeadCell>Type</TableHeadCell>
                  <TableHeadCell>Created</TableHeadCell>
                  <TableHeadCell>Actions</TableHeadCell>
                </TableRow>
              </TableHead>
              <TableBody className="divide-y">
                {triples.map((triple) => (
                  <TableRow key={triple.id} className="bg-white dark:border-gray-700 dark:bg-gray-800">
                    <TableCell className="font-medium text-gray-900 dark:text-white max-w-xs truncate">
                      {triple.subject}
                    </TableCell>
                    <TableCell className="text-gray-500 dark:text-gray-400 max-w-xs truncate">
                      {triple.predicate}
                    </TableCell>
                    <TableCell className="text-gray-500 dark:text-gray-400 max-w-xs truncate">
                      {triple.object}
                    </TableCell>
                    <TableCell>
                      <Badge color={triple.object_type === 'uri' ? 'blue' : 'green'}>
                        {triple.object_type}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-gray-500 dark:text-gray-400">
                      {new Date(triple.created_time).toLocaleDateString()}
                    </TableCell>
                    <TableCell>
                      <div className="flex gap-2">
                        <Button
                          size="sm"
                          color="blue"
                          onClick={() => handleEditClick(triple)}
                        >
                          <HiPencil className="h-4 w-4" />
                        </Button>
                        <Button
                          size="sm"
                          color="red"
                          onClick={() => handleDeleteClick(triple)}
                        >
                          <HiTrash className="h-4 w-4" />
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

      {/* Add Triple Modal */}
      <Modal show={showAddModal} onClose={() => setShowAddModal(false)} size="lg">
        <div className="p-6">
          <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">Add New Triple</h3>
          <div className="space-y-4">
            <div>
              <Label htmlFor="subject">Subject</Label>
              <TextInput
                id="subject"
                placeholder="Enter subject URI or blank node"
                value={tripleForm.subject}
                onChange={(e) => setTripleForm({...tripleForm, subject: e.target.value})}
              />
            </div>
            <div>
              <Label htmlFor="predicate">Predicate</Label>
              <TextInput
                id="predicate"
                placeholder="Enter predicate URI"
                value={tripleForm.predicate}
                onChange={(e) => setTripleForm({...tripleForm, predicate: e.target.value})}
              />
            </div>
            <div>
              <Label htmlFor="objectType">Object Type</Label>
              <Select
                id="objectType"
                value={tripleForm.objectType}
                onChange={(e) => setTripleForm({...tripleForm, objectType: e.target.value as 'uri' | 'literal'})}
              >
                <option value="uri">URI</option>
                <option value="literal">Literal</option>
              </Select>
            </div>
            <div>
              <Label htmlFor="object">Object</Label>
              {tripleForm.objectType === 'literal' ? (
                <Textarea
                  id="object"
                  placeholder="Enter literal value"
                  value={tripleForm.object}
                  onChange={(e) => setTripleForm({...tripleForm, object: e.target.value})}
                  rows={3}
                />
              ) : (
                <TextInput
                  id="object"
                  placeholder="Enter object URI"
                  value={tripleForm.object}
                  onChange={(e) => setTripleForm({...tripleForm, object: e.target.value})}
                />
              )}
            </div>
          </div>
          <div className="flex justify-end gap-3 mt-6">
            <Button onClick={handleAddTriple} color="blue">
              Add Triple
            </Button>
            <Button color="gray" onClick={() => setShowAddModal(false)}>
              Cancel
            </Button>
          </div>
        </div>
      </Modal>

      {/* Edit Triple Modal */}
      <Modal show={showEditModal} onClose={() => setShowEditModal(false)} size="lg">
        <div className="p-6">
          <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">Edit Triple</h3>
          <div className="space-y-4">
            <div>
              <Label htmlFor="edit-subject">Subject</Label>
              <TextInput
                id="edit-subject"
                placeholder="Enter subject URI or blank node"
                value={tripleForm.subject}
                onChange={(e) => setTripleForm({...tripleForm, subject: e.target.value})}
              />
            </div>
            <div>
              <Label htmlFor="edit-predicate">Predicate</Label>
              <TextInput
                id="edit-predicate"
                placeholder="Enter predicate URI"
                value={tripleForm.predicate}
                onChange={(e) => setTripleForm({...tripleForm, predicate: e.target.value})}
              />
            </div>
            <div>
              <Label htmlFor="edit-objectType">Object Type</Label>
              <Select
                id="edit-objectType"
                value={tripleForm.objectType}
                onChange={(e) => setTripleForm({...tripleForm, objectType: e.target.value as 'uri' | 'literal'})}
              >
                <option value="uri">URI</option>
                <option value="literal">Literal</option>
              </Select>
            </div>
            <div>
              <Label htmlFor="edit-object">Object</Label>
              {tripleForm.objectType === 'literal' ? (
                <Textarea
                  id="edit-object"
                  placeholder="Enter literal value"
                  value={tripleForm.object}
                  onChange={(e) => setTripleForm({...tripleForm, object: e.target.value})}
                  rows={3}
                />
              ) : (
                <TextInput
                  id="edit-object"
                  placeholder="Enter object URI"
                  value={tripleForm.object}
                  onChange={(e) => setTripleForm({...tripleForm, object: e.target.value})}
                />
              )}
            </div>
          </div>
          <div className="flex justify-end gap-3 mt-6">
            <Button onClick={handleEditTriple} color="blue">
              Save Changes
            </Button>
            <Button color="gray" onClick={() => setShowEditModal(false)}>
              Cancel
            </Button>
          </div>
        </div>
      </Modal>

      {/* Delete Confirmation Modal */}
      <Modal show={showDeleteModal} onClose={() => setShowDeleteModal(false)} size="md">
        <div className="p-6">
          <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">Delete Triple</h3>
          <p className="text-gray-600 dark:text-gray-400 mb-6">
            Are you sure you want to delete this triple? This action cannot be undone.
          </p>
          <div className="flex justify-end gap-3">
            <Button onClick={handleConfirmDelete} color="failure">
              Delete
            </Button>
            <Button color="gray" onClick={() => setShowDeleteModal(false)}>
              Cancel
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
};

export default Triples;
