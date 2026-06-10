import React, { useState, useEffect, useCallback } from 'react';
import { Spinner, Alert } from 'flowbite-react';
import { HiExclamationCircle, HiCubeTransparent } from 'react-icons/hi';
import { apiService } from '../../services/ApiService';
import {
  hydrateQuads,
  buildEntityGraphTree,
  type EntityGraphTree,
} from '../../lib/entityGraphBuilder';
import EntityGraphHeader from './EntityGraphHeader';
import FrameSection from './FrameSection';

interface EntityGraphViewerProps {
  spaceId: string;
  graphId: string;
  entityUri: string;
}

const EntityGraphViewer: React.FC<EntityGraphViewerProps> = ({
  spaceId,
  graphId,
  entityUri,
}) => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tree, setTree] = useState<EntityGraphTree | null>(null);
  const [expandKey, setExpandKey] = useState(0);
  const [collapseKey, setCollapseKey] = useState(0);

  // Fetch entity graph
  useEffect(() => {
    let cancelled = false;

    async function fetchGraph() {
      setLoading(true);
      setError(null);
      try {
        const response = await apiService.getEntityGraph(spaceId, graphId, entityUri);
        if (cancelled) return;

        const quads = response.results || [];
        if (quads.length === 0) {
          setTree(null);
          setError('No graph data returned for this entity.');
          return;
        }

        const graphObjects = hydrateQuads(quads);
        const entityTree = buildEntityGraphTree(graphObjects);

        if (!entityTree) {
          setError('Could not build entity graph tree. No KGEntity found in the response.');
          return;
        }

        setTree(entityTree);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load entity graph');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchGraph();
    return () => { cancelled = true; };
  }, [spaceId, graphId, entityUri]);

  const handleExpandAll = useCallback(() => setExpandKey(k => k + 1), []);
  const handleCollapseAll = useCallback(() => setCollapseKey(k => k + 1), []);

  // Use keys to force re-render of FrameSections with new default state
  const allExpanded = expandKey > collapseKey;

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-3">
        <Spinner size="lg" />
        <span className="text-sm text-gray-500 dark:text-gray-400">Loading entity graph…</span>
      </div>
    );
  }

  if (error) {
    return (
      <Alert color="failure" icon={HiExclamationCircle} className="mb-4">
        <span className="font-medium">Error:</span> {error}
        <button
          onClick={() => {
            setExpandKey(0);
            setCollapseKey(0);
            setLoading(true);
            setError(null);
            // Re-trigger fetch by updating entityUri effect
            const fetchAgain = async () => {
              try {
                const response = await apiService.getEntityGraph(spaceId, graphId, entityUri);
                const quads = response.results || [];
                const graphObjects = hydrateQuads(quads);
                const entityTree = buildEntityGraphTree(graphObjects);
                setTree(entityTree);
              } catch (err) {
                setError(err instanceof Error ? err.message : 'Failed to load entity graph');
              } finally {
                setLoading(false);
              }
            };
            fetchAgain();
          }}
          className="ml-3 text-sm underline hover:no-underline"
        >
          Retry
        </button>
      </Alert>
    );
  }

  if (!tree) {
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-3 text-gray-400 dark:text-gray-500">
        <HiCubeTransparent className="w-12 h-12" />
        <p className="text-sm">No frames or slots found for this entity.</p>
      </div>
    );
  }

  return (
    <div>
      <EntityGraphHeader
        tree={tree}
        onExpandAll={handleExpandAll}
        onCollapseAll={handleCollapseAll}
      />

      {tree.frames.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 gap-3 text-gray-400 dark:text-gray-500">
          <HiCubeTransparent className="w-10 h-10" />
          <p className="text-sm">This entity has no frames.</p>
        </div>
      ) : (
        <div key={`${expandKey}-${collapseKey}`}>
          {tree.frames.map((frameNode, idx) => (
            <FrameSection
              key={frameNode.frame.URI || idx}
              node={frameNode}
              depth={0}
              defaultExpanded={allExpanded || (collapseKey === 0)}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export default EntityGraphViewer;
