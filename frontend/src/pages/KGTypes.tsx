import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
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
  Pagination,
  Modal,
  ModalHeader,
  ModalBody,
  ModalFooter,
  Label,
  Textarea,
  Spinner,
  Select
} from 'flowbite-react';
import {
  HiPlus,
  HiTrash,
  HiSearch,
  HiExclamation
} from 'react-icons/hi';
// Define KGType interface for JSON-LD data
interface KGType {
  id?: number;
  space_id?: string;
  graph_id?: number;
  uri?: string;
  type_name?: string;
  description?: string;
  type_uri?: string;
  properties?: string[];
  created_at?: string;
  updated_at?: string;
  // JSON-LD properties
  '@id'?: string;
  '@type'?: string;
  [key: string]: any; // Allow additional JSON-LD properties
}
import KGTypesIcon from '../components/icons/KGTypesIcon';
import NavigationBreadcrumb from '../components/NavigationBreadcrumb';

// Define interfaces for API data
interface Space {
  id: number;
  tenant: string;
  space: string;
  space_name: string;
  description: string;
  created_time: string;
  last_modified: string;
}

interface Graph {
  id: number;
  space_id: string;
  graph_name: string;
  graph_uri: string;
  graph_type: string;
  triple_count: number;
  created_time: string;
  last_modified: string;
  description: string;
  status: string;
}

const KGTypes: React.FC = () => {
  const navigate = useNavigate();
  const { spaceId, graphId } = useParams<{ spaceId?: string; graphId?: string }>();
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [selectedSpace, setSelectedSpace] = useState<string>(spaceId || '');
  const [spacesLoading, setSpacesLoading] = useState<boolean>(true);
  const [graphs, setGraphs] = useState<Graph[]>([]);
  const [selectedGraph, setSelectedGraph] = useState<number | ''>('');

  // Navigate to hierarchical URL when space/graph selection changes
  useEffect(() => {
    if (selectedSpace && selectedGraph !== '' && !spaceId && !graphId) {
      // Find the selected graph to get its URI for the URL
      const selectedGraphObj = graphs.find(g => g.id === selectedGraph);
      const graphUri = selectedGraphObj ? selectedGraphObj.graph_uri : selectedGraph;
      navigate(`/space/${selectedSpace}/graph/${encodeURIComponent(graphUri)}/kg-types`);
    }
  }, [selectedSpace, selectedGraph, navigate, spaceId, graphId, graphs]);

  const [searchTerm, setSearchTerm] = useState<string>('');
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [itemsPerPage, setItemsPerPage] = useState<number>(10);
  const [kgTypes, setKGTypes] = useState<KGType[]>([]);
  const [filteredKGTypes, setFilteredKGTypes] = useState<KGType[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [graphsLoading, setGraphsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Modal states
  const [showAddModal, setShowAddModal] = useState<boolean>(false);
  const [showEditModal, setShowEditModal] = useState<boolean>(false);
  const [showDeleteModal, setShowDeleteModal] = useState<boolean>(false);
  const [selectedKGType, setSelectedKGType] = useState<KGType | null>(null);

  // Form state
  const [formData, setFormData] = useState({
    uri: '',
    type_name: '',
    description: '',
    type_uri: ''
  });

  // Fetch spaces
  const fetchSpaces = useCallback(async () => {
    try {
      setSpacesLoading(true);
      const response = await axios.get('/api/spaces');
      // Handle both array response and wrapped response
      const spacesData = Array.isArray(response.data) ? response.data : response.data.spaces || [];
      setSpaces(spacesData);
      setError(null);
    } catch (err) {
      console.error('Error fetching spaces:', err);
      setError('Failed to load spaces. Please try again later.');
      setSpaces([]);
    } finally {
      setSpacesLoading(false);
    }
  }, []);

  // Fetch graphs based on selected space
  const fetchGraphs = useCallback(async (space: string) => {
    try {
      setGraphsLoading(true);
      const response = await axios.get(`/api/graphs/sparql/${space}/graphs`);
      // The API returns List[GraphInfo] directly
      const graphsData = Array.isArray(response.data) ? response.data : [];
      console.log('Fetched graphs for space', space, ':', graphsData);
      
      // Transform GraphInfo objects to match our Graph interface
      const transformedGraphs = graphsData.map((graphInfo: any, index: number) => {
        console.log(`Processing graph ${index}:`, graphInfo);
        return {
          id: index, // Use index as ID since GraphInfo doesn't have an ID field
          space_id: space,
          graph_name: graphInfo.graph_uri ? (graphInfo.graph_uri.split('/').pop() || graphInfo.graph_uri) : `Graph ${index}`,
          graph_uri: graphInfo.graph_uri || `http://example.org/graph${index}`,
          graph_type: 'Graph', // Default type
          triple_count: graphInfo.triple_count || 0,
          created_time: graphInfo.created_time || new Date().toISOString(),
          last_modified: graphInfo.updated_time || new Date().toISOString(),
          description: `Graph: ${graphInfo.graph_uri || 'Unknown'}`,
          status: 'active'
        };
      });
      
      // If no graphs exist, add a default graph option
      if (transformedGraphs.length === 0) {
        console.log('No graphs found, adding default graph');
        transformedGraphs.push({
          id: 0,
          space_id: space,
          graph_name: 'Default Graph',
          graph_uri: 'http://vital.ai/graph/default',
          graph_type: 'Default',
          triple_count: 0,
          created_time: new Date().toISOString(),
          last_modified: new Date().toISOString(),
          description: 'Default graph for this space',
          status: 'active'
        });
      }
      
      console.log('Final transformed graphs:', transformedGraphs);
      setGraphs(transformedGraphs);
      setError(null);
    } catch (err) {
      console.error('Error fetching graphs:', err);
      setError('Failed to load graphs. Please try again later.');
      setGraphs([]);
    } finally {
      setGraphsLoading(false);
    }
  }, []);

  // Fetch KG types
  const fetchKGTypes = useCallback(async () => {
    if (!selectedSpace || selectedGraph === '') {
      setKGTypes([]);
      setLoading(false);
      return;
    }

    try {
      setLoading(true);
      // Find the selected graph to get its URI
      const selectedGraphObj = graphs.find(g => g.id === selectedGraph);
      const graphId = selectedGraphObj ? selectedGraphObj.graph_uri : selectedGraph;
      
      console.log('Using graph ID:', graphId, 'for selected graph:', selectedGraph);
      
      const response = await axios.get(`/api/graphs/kgtypes`, {
        params: {
          space_id: selectedSpace,
          graph_id: graphId,
          page_size: 100, // Get more items by default
          offset: 0
        }
      });
      
      // The response should be a KGTypeListResponse with data containing JSON-LD
      const responseData = response.data;
      // Extract KG types from the JSON-LD data structure
      let kgTypesData = [];
      if (responseData.data && responseData.data['@graph']) {
        kgTypesData = responseData.data['@graph'];
      } else if (Array.isArray(responseData)) {
        kgTypesData = responseData;
      } else if (responseData.kgtypes) {
        kgTypesData = responseData.kgtypes;
      }
      
      console.log('Loaded', kgTypesData.length, 'KG types for space:', selectedSpace, 'graph:', selectedGraph);
      console.log('Raw KG types data:', kgTypesData);
      
      setKGTypes(kgTypesData);
      setError(null);
    } catch (err) {
      console.error('Error fetching KG types:', err);
      setError('Failed to load KG types. Please try again later.');
      setKGTypes([]);
    } finally {
      setLoading(false);
    }
  }, [selectedSpace, selectedGraph, graphs]);

  // Filter KG types based on search term
  useEffect(() => {
    const filtered = kgTypes.filter(type => {
      const typeName = type.type_name || type['@id'] || '';
      const description = type.description || '';
      const uri = type.uri || type['@id'] || '';
      const typeUri = type.type_uri || type['@type'] || '';
      
      return typeName.toLowerCase().includes(searchTerm.toLowerCase()) ||
             description.toLowerCase().includes(searchTerm.toLowerCase()) ||
             uri.toLowerCase().includes(searchTerm.toLowerCase()) ||
             typeUri.toLowerCase().includes(searchTerm.toLowerCase());
    });
    setFilteredKGTypes(filtered);
    setCurrentPage(1);
  }, [kgTypes, searchTerm, itemsPerPage]);

  // Handle space selection
  const handleSpaceChange = (space: string) => {
    setSelectedSpace(space);
    setSelectedGraph('');
    if (space) {
      fetchGraphs(space);
    } else {
      setGraphs([]);
    }
  };

  // Handle graph selection
  const handleGraphChange = (graph: number | '') => {
    setSelectedGraph(graph);
  };

  // Initialize data
  useEffect(() => {
    fetchSpaces();
  }, [fetchSpaces]);

  useEffect(() => {
    if (selectedSpace) {
      fetchGraphs(selectedSpace);
    }
  }, [selectedSpace, fetchGraphs]);

  // Handle URL with graph URI - find matching graph after graphs are loaded
  useEffect(() => {
    if (graphId && graphs.length > 0 && selectedGraph === '') {
      console.log('Looking for graph with URI:', decodeURIComponent(graphId));
      console.log('Available graphs:', graphs);
      
      // Try to find graph by URI (if graphId is a URI)
      const graphByUri = graphs.find(g => g.graph_uri === decodeURIComponent(graphId));
      if (graphByUri) {
        console.log('Found matching graph:', graphByUri);
        setSelectedGraph(graphByUri.id);
      } else {
        console.log('No matching graph found, trying as index');
        // Try as index if it's a number
        const graphIndex = parseInt(graphId);
        if (!isNaN(graphIndex) && graphs[graphIndex]) {
          setSelectedGraph(graphIndex);
        }
      }
    }
  }, [graphId, graphs, selectedGraph]);

  useEffect(() => {
    fetchKGTypes();
  }, [fetchKGTypes]);


  // Pagination
  const totalPages = Math.ceil(filteredKGTypes.length / itemsPerPage);
  const startIndex = (currentPage - 1) * itemsPerPage;
  const endIndex = startIndex + itemsPerPage;
  const currentKGTypes = filteredKGTypes.slice(startIndex, endIndex);

  // Navigation handlers
  const handleAddKGType = () => {
    // Navigate to KG type details page with create mode
    const selectedGraphObj = graphs.find(g => g.id === selectedGraph);
    const graphUri = selectedGraphObj ? selectedGraphObj.graph_uri : selectedGraph;
    navigate(`/space/${selectedSpace}/graph/${encodeURIComponent(graphUri)}/kg-types/new?mode=create`);
  };

  // Removed unused handleEditKGType function

  const handleDeleteKGType = (kgType: KGType) => {
    setSelectedKGType(kgType);
    setShowDeleteModal(true);
  };

  const handleViewKGType = (kgType: KGType) => {
    // Navigate to KG type details page with view mode
    const kgTypeId = kgType.id || kgType['@id'] || 'unknown';
    const selectedGraphObj = graphs.find(g => g.id === selectedGraph);
    const graphUri = selectedGraphObj ? selectedGraphObj.graph_uri : selectedGraph;
    navigate(`/space/${selectedSpace}/graph/${encodeURIComponent(graphUri)}/kg-types/${encodeURIComponent(kgTypeId)}?mode=view`);
  };

  const confirmDelete = () => {
    if (selectedKGType) {
      setKGTypes(prev => prev.filter(type => type.id !== selectedKGType.id));
      setShowDeleteModal(false);
      setSelectedKGType(null);
    }
  };

  const handleSubmit = () => {
    const newKGType: KGType = {
      id: showEditModal && selectedKGType ? selectedKGType.id : Date.now(),
      space_id: selectedSpace,
      graph_id: selectedGraph as number,
      uri: formData.uri,
      type_name: formData.type_name,
      description: formData.description,
      type_uri: formData.type_uri,
      properties: [],
      created_at: showEditModal && selectedKGType ? selectedKGType.created_at : new Date().toISOString(),
      updated_at: new Date().toISOString()
    };

    if (showEditModal && selectedKGType) {
      setKGTypes(prev => prev.map(type => 
        type.id === selectedKGType.id 
          ? { ...newKGType, id: selectedKGType.id, created_at: selectedKGType.created_at }
          : type
      ));
      setShowEditModal(false);
    } else {
      setKGTypes(prev => [...prev, newKGType]);
      setShowAddModal(false);
      setFormData({
        uri: '',
        type_name: '',
        description: '',
        type_uri: ''
      });
    }
    
    setSelectedKGType(null);
  };


  return (
    <div className="space-y-6">
      <NavigationBreadcrumb
        spaceId={spaceId}
        graphId={graphId}
        currentPageName="KG Types"
        currentPageIcon={KGTypesIcon}
      />
      

      <div className="mb-6">
        <div className="flex items-center gap-2 mb-4">
          <KGTypesIcon className="w-6 h-6 text-indigo-600" />
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">KG Types</h1>
        </div>
      </div>

      {/* Space and Graph Selection */}
      <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-end mb-6">
        <div className="flex-1 max-w-xs">
          <Label htmlFor="space-select">Select Space</Label>
          <Select
            id="space-select"
            value={selectedSpace}
            onChange={(e) => handleSpaceChange(e.target.value)}
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
            onChange={(e) => handleGraphChange(e.target.value ? parseInt(e.target.value) : '')}
            disabled={!selectedSpace || graphsLoading}
          >
            <option value="">Choose a graph...</option>
            {graphs.map((graph) => (
              <option key={graph.id} value={graph.id}>
                {graph.graph_name}
              </option>
            ))}
          </Select>
        </div>
      </div>

      {/* Add KG Type Button */}
      {selectedSpace && selectedGraph !== '' && (
        <div className="mb-6">
          <Button onClick={handleAddKGType} color="blue">
            <HiPlus className="mr-2 h-4 w-4" />
            Add KG Type
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
                  placeholder="Search KG types by name, description, or URI..."
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

      {/* Loading Spinner for Spaces */}
      {spacesLoading && (
        <div className="text-center py-12">
          <Spinner size="xl" />
          <p className="mt-4 text-gray-600 dark:text-gray-400">Loading spaces...</p>
        </div>
      )}

      {/* Selection Required Messages */}
      {!selectedSpace && !spacesLoading && (
        <div className="text-center py-12">
          <div className="text-gray-500 dark:text-gray-400">
            <p className="text-lg mb-2">Select a space to view KG types</p>
            <p className="text-sm">Choose a space from the dropdown above to see available graphs.</p>
          </div>
        </div>
      )}
      
      {selectedSpace && selectedGraph === '' && graphs.length > 0 && (
        <div className="text-center py-12">
          <div className="text-gray-500 dark:text-gray-400">
            <p className="text-lg mb-2">Select a graph to view KG types</p>
            <p className="text-sm">Choose a graph from the dropdown above to see its knowledge graph types.</p>
          </div>
        </div>
      )}

      {/* Loading Spinner for KG Types */}
      {selectedSpace && selectedGraph !== '' && loading && (
        <div className="text-center py-12">
          <Spinner size="xl" />
          <p className="mt-4 text-gray-600 dark:text-gray-400">Loading KG types...</p>
        </div>
      )}

      {error && (
        <Alert color="failure">
          {error}
        </Alert>
      )}

      {/* KG Types Table */}
      {selectedSpace && selectedGraph !== '' && !loading && filteredKGTypes.length === 0 && !error ? (
        <Alert color="info">
          {searchTerm ? 
            `No KG types found matching "${searchTerm}". Try a different search term.` :
            'No KG types found in this graph. Add your first KG type to get started.'
          }
        </Alert>
      ) : selectedSpace && selectedGraph !== '' && !loading && currentKGTypes.length > 0 ? (
        <>
          {console.log('Rendering table with KG types:', currentKGTypes)}
          {currentKGTypes.length > 0 && console.log('First KG type properties:', Object.keys(currentKGTypes[0]))}
          <div className="overflow-x-auto">
            <Table>
              <TableHead>
                <TableRow>
                  <TableHeadCell>URI</TableHeadCell>
                  <TableHeadCell>Type Name</TableHeadCell>
                  <TableHeadCell className="hidden md:table-cell">Description</TableHeadCell>
                  <TableHeadCell className="hidden lg:table-cell">Type URI</TableHeadCell>
                  <TableHeadCell>Actions</TableHeadCell>
                </TableRow>
              </TableHead>
              <TableBody className="divide-y">
                {currentKGTypes.map((kgType, index) => (
                  <TableRow key={kgType.id || kgType['@id'] || index}>
                    <TableCell className="font-medium">
                      <div className="max-w-xs">
                        <div className="font-mono text-sm text-blue-600 truncate">
                          {kgType['@id'] || kgType.uri || 'No URI'}
                        </div>
                        <div className="text-xs text-gray-500 truncate">
                          {kgType['@type'] || kgType.type_uri || 'No Type'}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      {kgType.type_name || kgType['rdfs:label'] || kgType['@id']?.split('/').pop() || 'Unnamed'}
                    </TableCell>
                    <TableCell className="hidden md:table-cell">
                      <div className="max-w-xs truncate">
                        {kgType.description || kgType['rdfs:comment'] || 'No description'}
                      </div>
                    </TableCell>
                    <TableCell className="hidden lg:table-cell">
                      <div className="max-w-xs">
                        <div className="font-mono text-xs text-gray-600 truncate">
                          {kgType['@type'] || kgType.type_uri || 'No type URI'}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex space-x-2">
                        <Button
                          size="xs"
                          color="gray"
                          onClick={() => handleViewKGType(kgType)}
                          title="View Details"
                        >
                          <HiSearch className="h-3 w-3" />
                        </Button>
                        <Button
                          size="xs"
                          color="red"
                          onClick={() => handleDeleteKGType(kgType)}
                          title="Delete"
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
      ) : null}

      {/* Add/Edit Modal */}
      <Modal show={showAddModal || showEditModal} onClose={() => {
        setShowAddModal(false);
        setShowEditModal(false);
        setSelectedKGType(null);
      }}>
        <ModalHeader>
          {showEditModal ? 'Edit KG Type' : 'Add KG Type'}
        </ModalHeader>
        <ModalBody>
          <div className="space-y-4">
            <div>
              <Label htmlFor="uri">URI</Label>
              <TextInput
                id="uri"
                value={formData.uri}
                onChange={(e) => setFormData(prev => ({ ...prev, uri: e.target.value }))}
                required
              />
            </div>
            <div>
              <Label htmlFor="type-name">Type Name</Label>
              <TextInput
                id="type-name"
                value={formData.type_name}
                onChange={(e) => setFormData(prev => ({ ...prev, type_name: e.target.value }))}
                required
              />
            </div>
            <div>
              <Label htmlFor="description">Description</Label>
              <Textarea
                id="description"
                value={formData.description}
                onChange={(e) => setFormData(prev => ({ ...prev, description: e.target.value }))}
                rows={3}
              />
            </div>
            <div>
              <Label htmlFor="type-uri">Type URI</Label>
              <TextInput
                id="type-uri"
                value={formData.type_uri}
                onChange={(e) => setFormData(prev => ({ ...prev, type_uri: e.target.value }))}
                required
              />
            </div>
          </div>
        </ModalBody>
        <ModalFooter>
          <Button onClick={handleSubmit} disabled={!formData.type_name?.trim()}>
            {showEditModal ? 'Update' : 'Create'}
          </Button>
          <Button color="gray" onClick={() => {
            setShowAddModal(false);
            setShowEditModal(false);
            setSelectedKGType(null);
          }}>
            Cancel
          </Button>
        </ModalFooter>
      </Modal>

      {/* Delete Confirmation Modal */}
      <Modal show={showDeleteModal} onClose={() => setShowDeleteModal(false)}>
        <ModalHeader>
          <div className="flex items-center">
            <HiExclamation className="h-6 w-6 text-red-600 mr-2" />
            Confirm Delete
          </div>
        </ModalHeader>
        <ModalBody>
          <p>
            Are you sure you want to delete the KG type "{selectedKGType?.type_name}"? 
            This action cannot be undone.
          </p>
        </ModalBody>
        <ModalFooter>
          <Button color="red" onClick={confirmDelete}>
            Delete
          </Button>
          <Button color="gray" onClick={() => setShowDeleteModal(false)}>
            Cancel
          </Button>
        </ModalFooter>
      </Modal>
    </div>
  );
};

export default KGTypes;
