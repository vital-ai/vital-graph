import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { apiService } from '../services/ApiService';
import {
  Alert, Badge, Button, Label, Modal, ModalHeader, ModalBody, ModalFooter,
  Pagination, Select, Spinner, TextInput,
} from 'flowbite-react';
import { type SpaceInfo } from '../types/api';
import { type GraphInfo } from '../types/graphs';
import { HiTrash, HiArrowRight } from 'react-icons/hi2';
import { HiSearch, HiLink } from 'react-icons/hi';
import {
  parseEntitiesFromQuads,
  shortenUri,
  getFirstValue,
  type Quad,
} from '../utils/QuadUtils';

const HAS_EDGE_SOURCE = 'http://vital.ai/ontology/vital-core#hasEdgeSource';
const HAS_EDGE_DESTINATION = 'http://vital.ai/ontology/vital-core#hasEdgeDestination';

interface KGRelation {
  uri: string;
  rdf_type: string;
  name: string;
  source_uri: string;
  destination_uri: string;
  properties_count: number;
}

const KGRelations: React.FC = () => {
  const navigate = useNavigate();
  const { spaceId, graphId } = useParams<{ spaceId?: string; graphId?: string }>();

  const [spaces, setSpaces] = useState<SpaceInfo[]>([]);
  const [graphs, setGraphs] = useState<GraphInfo[]>([]);
  const [selectedSpace, setSelectedSpace] = useState(spaceId || '');
  const [selectedGraph, setSelectedGraph] = useState(graphId ? decodeURIComponent(graphId) : '');
  const [spacesLoading, setSpacesLoading] = useState(true);
  const [graphsLoading, setGraphsLoading] = useState(false);

  const [relations, setRelations] = useState<KGRelation[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [totalCount, setTotalCount] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [itemsPerPage, setItemsPerPage] = useState(25);
  const [sourceFilter, setSourceFilter] = useState('');
  const [destFilter, setDestFilter] = useState('');
  const [deletingRelation, setDeletingRelation] = useState<KGRelation | null>(null);

  const hasSelection = !!(selectedSpace && selectedGraph);

  // Fetch spaces
  const fetchSpaces = useCallback(async () => {
    try {
      setSpacesLoading(true);
      setSpaces(await apiService.getSpaces());
    } catch { /* ignore */ }
    finally { setSpacesLoading(false); }
  }, []);

  useEffect(() => { fetchSpaces(); }, [fetchSpaces]);

  // Fetch graphs
  const fetchGraphs = useCallback(async () => {
    if (!selectedSpace) { setGraphs([]); return; }
    try {
      setGraphsLoading(true);
      setGraphs(await apiService.getGraphs(selectedSpace));
    } catch { setGraphs([]); }
    finally { setGraphsLoading(false); }
  }, [selectedSpace]);

  useEffect(() => { fetchGraphs(); }, [fetchGraphs]);

  // Navigate to hierarchical URL when selection changes
  useEffect(() => {
    if (selectedSpace && selectedGraph && !spaceId) {
      navigate(`/space/${selectedSpace}/graph/${encodeURIComponent(selectedGraph)}/objects/kgrelations`, { replace: true });
    }
  }, [selectedSpace, selectedGraph, navigate, spaceId]);

  const fetchRelations = useCallback(async () => {
    if (!selectedSpace || !selectedGraph) return;
    try {
      setLoading(true);
      setError(null);
      const data = await apiService.getRelations(selectedSpace, selectedGraph, {
        page_size: itemsPerPage,
        offset: (currentPage - 1) * itemsPerPage,
        entity_source_uri: sourceFilter || undefined,
        entity_destination_uri: destFilter || undefined,
      });
      const quads: Quad[] = data.results || [];
      const grouped = parseEntitiesFromQuads(quads);
      const parsed: KGRelation[] = grouped.map(e => ({
        uri: e.uri,
        rdf_type: e.rdf_type,
        name: e.name,
        source_uri: getFirstValue(e.properties, HAS_EDGE_SOURCE),
        destination_uri: getFirstValue(e.properties, HAS_EDGE_DESTINATION),
        properties_count: e.properties_count,
      }));

      setRelations(parsed);
      setTotalCount(data.total_count ?? parsed.length);
    } catch {
      setError('Failed to load KG relations.');
      setRelations([]);
    } finally {
      setLoading(false);
    }
  }, [selectedSpace, selectedGraph, itemsPerPage, currentPage, sourceFilter, destFilter]);

  useEffect(() => { fetchRelations(); }, [fetchRelations]);

  const handleDelete = async (rel: KGRelation) => {
    try {
      await apiService.deleteRelation(selectedSpace, selectedGraph, rel.uri);
      setDeletingRelation(null);
      await fetchRelations();
    } catch {
      setError('Failed to delete relation.');
      setDeletingRelation(null);
    }
  };

  const totalPages = Math.max(1, Math.ceil(totalCount / itemsPerPage));

  return (
    <div className="space-y-5">
      {/* Page Title */}
      <div className="flex items-center gap-2 mb-2">
        <HiLink className="w-6 h-6 text-blue-600" />
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">KG Relations</h1>
      </div>

      {/* Space / Graph selectors */}
      <div className="flex flex-col sm:flex-row gap-4">
        <div className="flex-1 max-w-xs">
          <Label htmlFor="space-select" className="text-xs">Space</Label>
          <Select
            id="space-select"
            value={selectedSpace}
            onChange={(e) => { setSelectedSpace(e.target.value); setSelectedGraph(''); }}
            disabled={spacesLoading}
          >
            <option value="">Choose a space...</option>
            {spaces.map((s) => (
              <option key={s.space} value={s.space}>{s.space_name || s.space}</option>
            ))}
          </Select>
        </div>
        <div className="flex-1 max-w-xs">
          <Label htmlFor="graph-select" className="text-xs">Graph</Label>
          <Select
            id="graph-select"
            value={selectedGraph}
            onChange={(e) => setSelectedGraph(e.target.value)}
            disabled={!selectedSpace || graphsLoading}
          >
            <option value="">Choose a graph...</option>
            {graphs.map((g) => (
              <option key={g.graph_uri} value={g.graph_uri}>
                {g.graph_uri.split('/').pop() || g.graph_uri}
              </option>
            ))}
          </Select>
        </div>
      </div>

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <p className="text-gray-500 dark:text-gray-400 text-sm">
            Entity-to-entity edge relationships in the knowledge graph.
          </p>
        </div>
        {hasSelection && (
          <Badge color="info" size="sm">{totalCount} relation{totalCount !== 1 ? 's' : ''}</Badge>
        )}
      </div>

      {/* Filters */}
      {hasSelection && (
        <div className="flex flex-col sm:flex-row gap-3">
          <div className="flex-1">
            <TextInput
              icon={HiSearch}
              placeholder="Filter by source entity URI..."
              value={sourceFilter}
              onChange={(e) => { setSourceFilter(e.target.value); setCurrentPage(1); }}
            />
          </div>
          <div className="flex-1">
            <TextInput
              icon={HiSearch}
              placeholder="Filter by destination entity URI..."
              value={destFilter}
              onChange={(e) => { setDestFilter(e.target.value); setCurrentPage(1); }}
            />
          </div>
          <div className="w-32 flex-shrink-0">
            <Select value={itemsPerPage} onChange={(e) => { setItemsPerPage(parseInt(e.target.value)); setCurrentPage(1); }}>
              <option value={10}>10 / page</option>
              <option value={25}>25 / page</option>
              <option value={50}>50 / page</option>
              <option value={100}>100 / page</option>
            </Select>
          </div>
        </div>
      )}

      {/* Pagination */}
      {hasSelection && totalPages > 1 && (
        <div className="flex justify-center">
          <Pagination currentPage={currentPage} totalPages={totalPages} onPageChange={setCurrentPage} showIcons />
        </div>
      )}

      {error && <Alert color="failure" onDismiss={() => setError(null)}>{error}</Alert>}

      {/* Loading */}
      {loading && (
        <div className="flex justify-center py-12"><Spinner size="xl" /></div>
      )}

      {/* Empty states */}
      {!loading && !hasSelection && (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">
          <HiLink className="w-16 h-16 mx-auto mb-4 text-gray-300 dark:text-gray-600" />
          <p className="text-lg font-medium">Select a space and graph</p>
          <p className="text-sm mt-1">Choose a space and graph from the sidebar to view relations</p>
        </div>
      )}

      {!loading && hasSelection && relations.length === 0 && !error && (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">
          <HiLink className="w-16 h-16 mx-auto mb-4 text-gray-300 dark:text-gray-600" />
          <p className="text-lg font-medium">No relations found</p>
          <p className="text-sm mt-1">This graph has no edge relations{sourceFilter || destFilter ? ' matching your filters' : ''}</p>
        </div>
      )}

      {/* Relations table */}
      {!loading && relations.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
          <table className="w-full text-sm text-left">
            <thead className="text-xs text-gray-500 dark:text-gray-400 uppercase bg-gray-50 dark:bg-gray-800">
              <tr>
                <th className="px-4 py-3">Relation</th>
                <th className="px-4 py-3">Source → Destination</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3 w-20"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
              {relations.map((rel) => (
                <tr key={rel.uri} className="bg-white dark:bg-gray-900 hover:bg-gray-50 dark:hover:bg-gray-800">
                  <td className="px-4 py-3">
                    <div className="font-medium text-gray-900 dark:text-white truncate max-w-[200px]" title={rel.name}>
                      {rel.name}
                    </div>
                    <div className="text-xs text-gray-400 truncate max-w-[200px]" title={rel.uri}>
                      {shortenUri(rel.uri)}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1.5 text-xs">
                      <span className="bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 px-2 py-0.5 rounded truncate max-w-[180px]" title={rel.source_uri}>
                        {shortenUri(rel.source_uri) || '—'}
                      </span>
                      <HiArrowRight className="h-3.5 w-3.5 text-gray-400 flex-shrink-0" />
                      <span className="bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-300 px-2 py-0.5 rounded truncate max-w-[180px]" title={rel.destination_uri}>
                        {shortenUri(rel.destination_uri) || '—'}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <Badge color="purple" size="sm">{shortenUri(rel.rdf_type)}</Badge>
                  </td>
                  <td className="px-4 py-3">
                    <Button size="xs" color="failure" onClick={() => setDeletingRelation(rel)}>
                      <HiTrash className="h-3.5 w-3.5" />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Delete Confirmation */}
      <Modal show={!!deletingRelation} onClose={() => setDeletingRelation(null)} size="md">
        <ModalHeader>Delete Relation</ModalHeader>
        <ModalBody>
          <p className="text-gray-600 dark:text-gray-300">
            Are you sure you want to delete the relation <span className="font-semibold">{deletingRelation?.name}</span>?
            This will permanently remove the edge between the source and destination entities.
          </p>
        </ModalBody>
        <ModalFooter>
          <Button color="failure" onClick={() => deletingRelation && handleDelete(deletingRelation)}>
            Delete
          </Button>
          <Button color="gray" onClick={() => setDeletingRelation(null)}>Cancel</Button>
        </ModalFooter>
      </Modal>
    </div>
  );
};

export default KGRelations;
