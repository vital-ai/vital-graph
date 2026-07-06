import React, { useState, useEffect } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { Alert, Button, Card, Spinner, Breadcrumb, BreadcrumbItem, TextInput } from 'flowbite-react';
import {
  HiHome, HiUpload, HiDownload, HiTrash, HiViewBoards, HiExclamation,
  HiDatabase, HiChevronRight, HiDocumentDuplicate, HiCollection, HiLink, HiSearch
} from 'react-icons/hi';
import { type GraphInfo } from '../types/graphs';
import { apiService } from '../services/ApiService';
import GraphIcon from '../components/icons/GraphIcon';
import TriplesIcon from '../components/icons/TriplesIcon';
import ObjectIcon from '../components/icons/ObjectIcon';
import { extractGraphName } from '../utils/QuadUtils';
import ConfirmDialog from '../components/ConfirmDialog';
import FormField from '../components/FormField';
import CopyButton from '../components/CopyButton';

interface BannerMessage {
  type: 'success' | 'error';
  message: string;
}

const GraphDetail: React.FC = () => {
  const { spaceId, graphId } = useParams<{ spaceId: string; graphId: string }>();
  const navigate = useNavigate();
  const isCreating = graphId === 'new' || !graphId;
  const graphUri = graphId ? decodeURIComponent(graphId) : '';

  const [graph, setGraph] = useState<GraphInfo | null>(null);
  const [spaceName, setSpaceName] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [bannerMessage, setBannerMessage] = useState<BannerMessage | null>(null);
  const [showPurgeModal, setShowPurgeModal] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [newGraphUri, setNewGraphUri] = useState('');
  const [graphUriError, setGraphUriError] = useState('');
  const [entityCount, setEntityCount] = useState<number | null>(null);
  const [frameCount, setFrameCount] = useState<number | null>(null);
  const [relationCount, setRelationCount] = useState<number | null>(null);

  useEffect(() => {
    const load = async () => {
      if (!spaceId) { setLoading(false); return; }

      try {
        // Fetch space name
        const spacesData = await apiService.getSpaces();
        const found = spacesData.find((s: { space: string; space_name?: string }) => s.space === spaceId);
        setSpaceName(found?.space_name || spaceId);

        if (isCreating) {
          setLoading(false);
          return;
        }

        // Find graph by URI
        const graphsData = await apiService.getGraphs(spaceId);
        const match = graphsData.find((g: GraphInfo) => g.graph_uri === graphUri);

        if (!match) {
          setBannerMessage({ type: 'error', message: `Graph not found: ${graphUri}` });
        } else {
          setGraph(match);
        }
      } catch {
        setBannerMessage({ type: 'error', message: 'Failed to load graph data' });
      } finally {
        setLoading(false);
      }

      // Fetch object counts via fast SQL-based endpoint
      if (!isCreating && graphUri) {
        apiService.getGraphCounts(spaceId, graphUri).then(counts => {
          setEntityCount(counts.entity_count ?? 0);
          setFrameCount(counts.frame_count ?? 0);
          setRelationCount(counts.relation_count ?? 0);
        }).catch(() => {
          // Counts are non-critical; leave as null on failure
        });
      }
    };
    load();
  }, [spaceId, graphId, graphUri, isCreating]);

  const handleCreate = async () => {
    if (!newGraphUri.trim()) {
      setGraphUriError('Graph URI is required');
      return;
    }
    try {
      new URL(newGraphUri.trim());
    } catch {
      setGraphUriError('Must be a valid URI (e.g., http://vital.ai/graph/my-graph or urn:uuid:123)');
      return;
    }
    if (!spaceId) return;
    setSaving(true);
    try {
      await apiService.createGraph(spaceId, newGraphUri.trim());
      setBannerMessage({ type: 'success', message: 'Graph created successfully!' });
      setTimeout(() => navigate(`/space/${spaceId}/graphs`), 1500);
    } catch {
      setBannerMessage({ type: 'error', message: 'Failed to create graph.' });
    } finally {
      setSaving(false);
    }
  };

  const handlePurge = async () => {
    if (!spaceId || !graph) return;
    try {
      await apiService.executeGraphOperation(spaceId, 'CLEAR', graph.graph_uri, undefined, true);
      setBannerMessage({ type: 'success', message: 'Graph purged successfully!' });
      setShowPurgeModal(false);
      // Refresh graph data
      const graphsData = await apiService.getGraphs(spaceId);
      const match = graphsData.find((g: GraphInfo) => g.graph_uri === graph.graph_uri);
      if (match) setGraph(match);
      setTimeout(() => setBannerMessage(null), 3000);
    } catch {
      setBannerMessage({ type: 'error', message: 'Failed to purge graph.' });
      setShowPurgeModal(false);
    }
  };

  const handleDelete = async () => {
    if (!spaceId || !graph) return;
    try {
      await apiService.deleteGraph(spaceId, graph.graph_uri, true);
      setBannerMessage({ type: 'success', message: 'Graph deleted successfully!' });
      setShowDeleteModal(false);
      setTimeout(() => navigate(`/space/${spaceId}/graphs`), 1500);
    } catch {
      setBannerMessage({ type: 'error', message: 'Failed to delete graph.' });
      setShowDeleteModal(false);
    }
  };

  const graphName = graph ? extractGraphName(graph.graph_uri) : '';
  const encodedGraphUri = graph ? encodeURIComponent(graph.graph_uri) : '';

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <Spinner size="xl" />
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="graph-detail-page">
      {/* Breadcrumb */}
      <Breadcrumb>
        <BreadcrumbItem href="/" icon={HiHome}>Home</BreadcrumbItem>
        <BreadcrumbItem href="/spaces" icon={HiViewBoards}>Spaces</BreadcrumbItem>
        <BreadcrumbItem href={`/space/${spaceId}`}>{spaceName}</BreadcrumbItem>
        <BreadcrumbItem href={`/space/${spaceId}/graphs`} icon={GraphIcon}>Graphs</BreadcrumbItem>
        <BreadcrumbItem>{isCreating ? 'New Graph' : graphName}</BreadcrumbItem>
      </Breadcrumb>

      {/* Banner */}
      {bannerMessage && (
        <Alert color={bannerMessage.type === 'success' ? 'success' : 'failure'}>
          {bannerMessage.message}
        </Alert>
      )}

      {/* Create Mode */}
      {isCreating && (
        <>
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Create New Graph</h1>
            <p className="text-gray-500 dark:text-gray-400 mt-1">in space {spaceName}</p>
          </div>
          <Card>
            <div className="space-y-4 max-w-lg">
              <FormField
                label="Graph URI"
                htmlFor="graph_uri"
                error={graphUriError}
                hint="Full URI that identifies this graph"
                required
              >
                <TextInput
                  id="graph_uri"
                  type="text"
                  value={newGraphUri}
                  onChange={(e) => { setNewGraphUri(e.target.value); setGraphUriError(''); }}
                  placeholder="http://vital.ai/graph/my-graph"
                  color={graphUriError ? 'failure' : undefined}
                />
              </FormField>
              <div className="flex gap-2 pt-2">
                <Button color="blue" onClick={handleCreate} disabled={saving || !newGraphUri.trim()}>
                  {saving ? 'Creating...' : 'Create Graph'}
                </Button>
                <Button color="gray" onClick={() => navigate(`/space/${spaceId}/graphs`)} disabled={saving}>
                  Cancel
                </Button>
              </div>
            </div>
          </Card>
        </>
      )}

      {/* View Mode */}
      {!isCreating && graph && (
        <>
          {/* Header */}
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <h1 className="text-2xl font-bold text-gray-900 dark:text-white">{graphName}</h1>
              <p className="text-xs text-gray-400 dark:text-gray-500 font-mono mt-1 break-all inline-flex items-center gap-1">{graph.graph_uri}<CopyButton text={graph.graph_uri} /></p>
            </div>
            <div className="flex gap-2 flex-shrink-0">
              <Button size="sm" color="blue" onClick={() => navigate(`/data/import/new?spaceId=${spaceId}&graphUri=${encodedGraphUri}`)}>
                <HiUpload className="mr-1.5 h-4 w-4" />Import
              </Button>
              <Button size="sm" color="gray" onClick={() => navigate(`/data/export/new?spaceId=${spaceId}&graphUri=${encodedGraphUri}`)}>
                <HiDownload className="mr-1.5 h-4 w-4" />Export
              </Button>
              <Button size="sm" color="warning" onClick={() => setShowPurgeModal(true)}>
                <HiExclamation className="mr-1.5 h-4 w-4" />Purge
              </Button>
              <Button size="sm" color="failure" onClick={() => setShowDeleteModal(true)}>
                <HiTrash className="mr-1.5 h-4 w-4" />Delete
              </Button>
            </div>
          </div>

          {/* Stats */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
            <Card>
              <div className="flex items-center gap-3">
                <HiDatabase className="w-7 h-7 text-indigo-500" />
                <div>
                  <p className="text-xl font-bold text-gray-900 dark:text-white">
                    {(graph.triple_count || 0).toLocaleString()}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Triples</p>
                </div>
              </div>
            </Card>
            <Card>
              <div className="flex items-center gap-3">
                <HiCollection className="w-7 h-7 text-blue-500" />
                <div>
                  <p className="text-xl font-bold text-gray-900 dark:text-white">
                    {entityCount != null ? entityCount.toLocaleString() : '—'}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Entities</p>
                </div>
              </div>
            </Card>
            <Card>
              <div className="flex items-center gap-3">
                <ObjectIcon className="w-7 h-7 text-teal-500" />
                <div>
                  <p className="text-xl font-bold text-gray-900 dark:text-white">
                    {frameCount != null ? frameCount.toLocaleString() : '—'}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Frames</p>
                </div>
              </div>
            </Card>
            <Card>
              <div className="flex items-center gap-3">
                <HiLink className="w-7 h-7 text-orange-500" />
                <div>
                  <p className="text-xl font-bold text-gray-900 dark:text-white">
                    {relationCount != null ? relationCount.toLocaleString() : '—'}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Relations</p>
                </div>
              </div>
            </Card>
            <Card>
              <div className="flex items-center gap-3">
                <GraphIcon className="w-7 h-7 text-purple-500" />
                <div>
                  <p className="text-xl font-bold text-gray-900 dark:text-white truncate max-w-[100px]" title={spaceName}>
                    {spaceName}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Space</p>
                </div>
              </div>
            </Card>
            <Card>
              <div className="flex items-center gap-3">
                <HiDatabase className="w-7 h-7 text-green-500" />
                <div>
                  <p className="text-xl font-bold text-gray-900 dark:text-white">
                    {graph.created_time ? new Date(graph.created_time).toLocaleDateString() : 'N/A'}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Created</p>
                </div>
              </div>
            </Card>
          </div>

          {/* Browse Content */}
          <Card>
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Browse Content</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {[
                { to: `/space/${spaceId}/graph/${encodedGraphUri}/triples`, icon: <TriplesIcon className="w-5 h-5" />, label: 'Triples', desc: 'RDF statements' },
                { to: `/space/${spaceId}/graph/${encodedGraphUri}/objects/graphobjects`, icon: <ObjectIcon className="w-5 h-5" />, label: 'Objects', desc: 'Graph objects' },
                { to: `/space/${spaceId}/graph/${encodedGraphUri}/objects/kgentities`, icon: <HiCollection className="w-5 h-5" />, label: 'Entities', desc: 'KG entities' },
                { to: `/space/${spaceId}/graph/${encodedGraphUri}/objects/kgframes`, icon: <HiDocumentDuplicate className="w-5 h-5" />, label: 'Frames', desc: 'KG frames' },
                { to: `/space/${spaceId}/graph/${encodedGraphUri}/objects/kgrelations`, icon: <HiLink className="w-5 h-5" />, label: 'Relations', desc: 'Edge relationships' },
                { to: `/sparql`, icon: <HiSearch className="w-5 h-5" />, label: 'SPARQL', desc: 'Query this graph' },
              ].map((item) => (
                <Link
                  key={item.label}
                  to={item.to}
                  className="flex items-center gap-3 p-3 rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700 hover:border-blue-300 dark:hover:border-blue-600 transition-all group"
                >
                  <div className="text-gray-400 group-hover:text-blue-500 transition-colors">{item.icon}</div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 dark:text-white">{item.label}</p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">{item.desc}</p>
                  </div>
                  <HiChevronRight className="w-4 h-4 text-gray-300 group-hover:text-gray-500" />
                </Link>
              ))}
            </div>
          </Card>

          {/* Details */}
          <Card>
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Details</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Graph URI</p>
                <p className="text-sm text-gray-900 dark:text-white font-mono break-all inline-flex items-center gap-1">{graph.graph_uri}<CopyButton text={graph.graph_uri} /></p>
              </div>
              <div>
                <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Space</p>
                <Link to={`/space/${spaceId}`} className="text-sm text-blue-600 hover:underline">{spaceName}</Link>
              </div>
              <div>
                <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Triple Count</p>
                <p className="text-sm text-gray-900 dark:text-white">{(graph.triple_count || 0).toLocaleString()}</p>
              </div>
              <div>
                <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Created</p>
                <p className="text-sm text-gray-900 dark:text-white">
                  {graph.created_time ? new Date(graph.created_time).toLocaleString() : 'N/A'}
                </p>
              </div>
              <div>
                <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Last Modified</p>
                <p className="text-sm text-gray-900 dark:text-white">
                  {graph.updated_time ? new Date(graph.updated_time).toLocaleString() : 'N/A'}
                </p>
              </div>
            </div>
          </Card>

          {/* Danger Zone */}
          <div className="rounded-lg border-2 border-red-200 dark:border-red-900/50 p-5">
            <h2 className="text-lg font-semibold text-red-700 dark:text-red-400 mb-3">Danger Zone</h2>
            <div className="space-y-3">
              <div className="flex items-center justify-between p-3 rounded border border-gray-200 dark:border-gray-700">
                <div>
                  <p className="text-sm font-medium text-gray-900 dark:text-white">Purge all data</p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Remove all triples but keep the graph.</p>
                </div>
                <Button size="sm" color="warning" onClick={() => setShowPurgeModal(true)}>
                  <HiExclamation className="mr-1.5 h-4 w-4" />Purge
                </Button>
              </div>
              <div className="flex items-center justify-between p-3 rounded border border-gray-200 dark:border-gray-700">
                <div>
                  <p className="text-sm font-medium text-gray-900 dark:text-white">Delete this graph</p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Permanently remove the graph and all its data.</p>
                </div>
                <Button size="sm" color="failure" onClick={() => setShowDeleteModal(true)}>
                  <HiTrash className="mr-1.5 h-4 w-4" />Delete
                </Button>
              </div>
            </div>
          </div>
        </>
      )}

      {/* Not found */}
      {!isCreating && !graph && !loading && (
        <div className="text-center py-16">
          <GraphIcon className="w-16 h-16 mx-auto mb-4 text-gray-300 dark:text-gray-600" />
          <p className="text-lg font-medium text-gray-500 dark:text-gray-400">Graph not found</p>
          <Link to={`/space/${spaceId}/graphs`} className="text-blue-600 hover:underline text-sm mt-2 inline-block">
            Back to Graphs
          </Link>
        </div>
      )}

      {/* Purge Modal */}
      <ConfirmDialog
        open={showPurgeModal}
        onConfirm={handlePurge}
        onCancel={() => setShowPurgeModal(false)}
        title="Purge Graph"
        description={<>Remove all triples from <strong>{graphName}</strong>?</>}
        confirmLabel="Purge"
        variant="warning"
      />

      {/* Delete Modal */}
      <ConfirmDialog
        open={showDeleteModal}
        onConfirm={handleDelete}
        onCancel={() => setShowDeleteModal(false)}
        title="Delete Graph"
        description={<>Permanently delete <strong>{graphName}</strong> and all its data?</>}
        confirmLabel="Delete"
        variant="danger"
      />
    </div>
  );
};

export default GraphDetail;
