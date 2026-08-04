import React, { useCallback, useEffect, useState } from 'react';
import { Spinner, Alert, Select } from 'flowbite-react';
import { HiExclamationCircle, HiCubeTransparent } from 'react-icons/hi';
import { apiService } from '../../services/ApiService';
import { hydrateQuads } from '../../lib/entityGraphBuilder';
import { needsPaging, slotCountFor } from '../../lib/entityGraphPage';
import { useEntityGraphPaging } from '../../lib/useEntityGraphPaging';
import { isKGEntity, type GraphObject } from '@vital-ai/vital-kg-model-ts';
import type { KGEntity } from '@vital-ai/vital-kg-model-ts';
import EntityGraphHeader from './EntityGraphHeader';
import FrameSection from './FrameSection';
import LevelPagination from './LevelPagination';

interface EntityGraphViewerProps {
  spaceId: string;
  graphId: string;
  entityUri: string;
}

const PAGE_SIZE_OPTIONS = [10, 25, 50, 100];
const DEFAULT_PAGE_SIZE = 25;

/**
 * Entity graph, paged at every level.
 *
 * Previously this fetched the entity's ENTIRE subgraph in one call and sorted
 * it client-side, which does not scale (measured ~2s / 10k objects for 5k
 * frames). Now it pages top-level frames, and each frame pages its own slots
 * and child frames — see
 * planning/planning_ui/entity_graph_frame_slot_paging_plan.md.
 *
 * Paging controls appear at a level only when that level's total exceeds the
 * page size, so small entities look and behave exactly as before.
 */
const EntityGraphViewer: React.FC<EntityGraphViewerProps> = ({
  spaceId,
  graphId,
  entityUri,
}) => {
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [entity, setEntity] = useState<KGEntity | null>(null);
  const [entityError, setEntityError] = useState<string | null>(null);
  const [expandKey, setExpandKey] = useState(0);
  const [collapseKey, setCollapseKey] = useState(0);

  const paging = useEntityGraphPaging({ spaceId, graphId, entityUri, pageSize });

  // The entity itself, for the header. Cheap: no graph expansion.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setEntityError(null);
      try {
        const resp: any = await apiService.getEntity(spaceId, graphId, entityUri);
        if (cancelled) return;
        const objects: GraphObject[] = hydrateQuads(resp.results || []);
        setEntity((objects.find(isKGEntity) as KGEntity) ?? null);
      } catch (err) {
        if (!cancelled) {
          setEntityError(err instanceof Error ? err.message : 'Failed to load entity');
        }
      }
    })();
    return () => { cancelled = true; };
  }, [spaceId, graphId, entityUri]);

  const handleExpandAll = useCallback(() => setExpandKey(k => k + 1), []);
  const handleCollapseAll = useCallback(() => setCollapseKey(k => k + 1), []);
  const allExpanded = expandKey > collapseKey;

  const { topFrames } = paging;

  // Expand-all fans out one slot request per expanded frame, so it is offered
  // only when nothing would page: the frame list fits one page AND no frame on
  // it has more slots than one page. Slot counts come from the frame page, so
  // this is knowable without expanding anything.
  const framesFitOnePage = !needsPaging(topFrames.totalCount, pageSize);
  const anyFrameOverflowsSlots = topFrames.items.some(
    f => slotCountFor(paging.slotCounts, String(f.URI ?? '')) > pageSize,
  );
  const expandAllDisabled = !framesFitOnePage || anyFrameOverflowsSlots;
  const expandAllReason = !framesFitOnePage
    ? 'Not available while frames are paged — expand frames individually'
    : anyFrameOverflowsSlots
      ? 'Not available — a frame has more slots than one page'
      : undefined;

  if (topFrames.loading && !topFrames.loaded) {
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-3">
        <Spinner size="lg" />
        <span className="text-sm text-gray-500 dark:text-gray-400">Loading entity graph…</span>
      </div>
    );
  }

  const error = entityError || topFrames.error;
  if (error) {
    return (
      <Alert color="failure" icon={HiExclamationCircle} className="mb-4">
        <span className="font-medium">Error:</span> {error}
        <button onClick={() => paging.refresh()} className="ml-3 text-sm underline hover:no-underline">
          Retry
        </button>
      </Alert>
    );
  }

  return (
    <div data-testid="entity-graph-viewer">
      <EntityGraphHeader
        entity={entity}
        frameCount={topFrames.totalCount}
        onExpandAll={handleExpandAll}
        onCollapseAll={handleCollapseAll}
        expandAllDisabled={expandAllDisabled}
        expandAllReason={expandAllReason}
      />

      {/* Page size applies to every level. */}
      {needsPaging(topFrames.totalCount, PAGE_SIZE_OPTIONS[0]) && (
        <div className="flex justify-end mb-2">
          <div className="w-32">
            <Select
              data-testid="entity-graph-page-size"
              value={pageSize}
              onChange={e => setPageSize(parseInt(e.target.value, 10))}
            >
              {PAGE_SIZE_OPTIONS.map(n => (
                <option key={n} value={n}>{n} / page</option>
              ))}
            </Select>
          </div>
        </div>
      )}

      {topFrames.items.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 gap-3 text-gray-400 dark:text-gray-500">
          <HiCubeTransparent className="w-10 h-10" />
          <p className="text-sm">This entity has no frames.</p>
        </div>
      ) : (
        <>
          <div key={`${expandKey}-${collapseKey}`}>
            {topFrames.items.map((frame, idx) => (
              <FrameSection
                key={String(frame.URI ?? idx)}
                frame={frame}
                paging={paging}
                pageSize={pageSize}
                depth={0}
                // Auto-expanding a paged frame list would fire two requests
                // per frame on load — the very fan-out this design avoids.
                // Below the threshold the view behaves as it always did.
                defaultExpanded={allExpanded || (collapseKey === 0 && framesFitOnePage)}
              />
            ))}
          </div>

          {needsPaging(topFrames.totalCount, pageSize) && (
            <LevelPagination
              label="Frames"
              testId="frame-pagination"
              offset={topFrames.offset}
              pageSize={pageSize}
              shown={topFrames.items.length}
              totalCount={topFrames.totalCount}
              loading={topFrames.loading}
              onOffsetChange={paging.setTopOffset}
            />
          )}
        </>
      )}
    </div>
  );
};

export default EntityGraphViewer;
