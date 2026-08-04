import { useCallback, useEffect, useRef, useState } from 'react';
import { apiService } from '../services/ApiService';
import { hydrateQuads } from './entityGraphBuilder';
import type { SlotEntry } from './entityGraphBuilder';
import { framesFromPage, slotsFromPage, clampOffset } from './entityGraphPage';
import { FRAME_SEQUENCE_PROPERTY, SLOT_SEQUENCE_PROPERTY } from './sortProperties';
import type { KGFrame } from '@vital-ai/vital-kg-model-ts';

/** One paged level: top-level frames, a frame's child frames, or its slots. */
export interface LevelState<T> {
  items: T[];
  offset: number;
  totalCount: number;
  loading: boolean;
  /** False until the first fetch completes — lets a collapsed frame fetch nothing. */
  loaded: boolean;
  error: string | null;
}

const emptyLevel = <T,>(): LevelState<T> => ({
  items: [], offset: 0, totalCount: 0, loading: false, loaded: false, error: null,
});

interface Args {
  spaceId: string;
  graphId: string;
  entityUri: string;
  pageSize: number;
}

/**
 * Paging state for the entity graph, keyed by frame URI.
 *
 * Per-frame state lives here rather than inside FrameSection so that it
 * survives re-renders and reordering of the frame list, and so the header can
 * see the slot counts needed to gate expand-all.
 *
 * Ordering is the server's: every fetch requests the sequence sort, and
 * nothing here re-sorts a page (that would scramble page boundaries).
 */
export function useEntityGraphPaging({ spaceId, graphId, entityUri, pageSize }: Args) {
  const [topFrames, setTopFrames] = useState<LevelState<KGFrame>>(emptyLevel<KGFrame>());
  const [slotCounts, setSlotCounts] = useState<Record<string, number>>({});
  const [slotsByFrame, setSlotsByFrame] = useState<Record<string, LevelState<SlotEntry>>>({});
  const [childrenByFrame, setChildrenByFrame] = useState<Record<string, LevelState<KGFrame>>>({});

  // Guards against a stale response overwriting a newer one. The list pages
  // elsewhere in this app do not sequence their requests, which is a known
  // source of stale renders — see issues/022.
  const reqSeq = useRef<Record<string, number>>({});
  const nextSeq = (key: string) => {
    reqSeq.current[key] = (reqSeq.current[key] ?? 0) + 1;
    return reqSeq.current[key];
  };
  const isCurrent = (key: string, seq: number) => reqSeq.current[key] === seq;

  const fetchTopFrames = useCallback(async (offset: number) => {
    const key = 'top';
    const seq = nextSeq(key);
    setTopFrames(prev => ({ ...prev, loading: true, error: null }));
    try {
      const resp: any = await apiService.getEntityFrames(spaceId, graphId, entityUri, {
        page_size: pageSize,
        offset,
        sort_by: FRAME_SEQUENCE_PROPERTY,
        sort_order: 'asc',
        include_slot_counts: true,
      });
      if (!isCurrent(key, seq)) return;
      const objects = hydrateQuads(resp.results || []);
      setTopFrames({
        items: framesFromPage(objects),
        offset,
        totalCount: resp.total_count ?? 0,
        loading: false,
        loaded: true,
        error: null,
      });
      // Counts accumulate across pages so previously seen frames keep theirs.
      if (resp.slot_counts) {
        setSlotCounts(prev => ({ ...prev, ...resp.slot_counts }));
      }
    } catch (err) {
      if (!isCurrent(key, seq)) return;
      setTopFrames(prev => ({
        ...prev, loading: false, loaded: true,
        error: err instanceof Error ? err.message : 'Failed to load frames',
      }));
    }
  }, [spaceId, graphId, entityUri, pageSize]);

  const fetchSlots = useCallback(async (frameUri: string, offset: number) => {
    const key = `slots:${frameUri}`;
    const seq = nextSeq(key);
    setSlotsByFrame(prev => ({
      ...prev,
      [frameUri]: { ...(prev[frameUri] ?? emptyLevel<SlotEntry>()), loading: true, error: null },
    }));
    try {
      const resp: any = await apiService.getEntityFrameSlots(spaceId, graphId, frameUri, {
        entity_uri: entityUri,
        page_size: pageSize,
        offset,
        sort_by: SLOT_SEQUENCE_PROPERTY,
        sort_order: 'asc',
      });
      if (!isCurrent(key, seq)) return;
      const objects = hydrateQuads(resp.results || []);
      setSlotsByFrame(prev => ({
        ...prev,
        [frameUri]: {
          items: slotsFromPage(objects),
          offset,
          totalCount: resp.total_count ?? 0,
          loading: false, loaded: true, error: null,
        },
      }));
    } catch (err) {
      if (!isCurrent(key, seq)) return;
      setSlotsByFrame(prev => ({
        ...prev,
        [frameUri]: {
          ...(prev[frameUri] ?? emptyLevel<SlotEntry>()),
          loading: false, loaded: true,
          error: err instanceof Error ? err.message : 'Failed to load slots',
        },
      }));
    }
  }, [spaceId, graphId, entityUri, pageSize]);

  const fetchChildFrames = useCallback(async (frameUri: string, offset: number) => {
    const key = `children:${frameUri}`;
    const seq = nextSeq(key);
    setChildrenByFrame(prev => ({
      ...prev,
      [frameUri]: { ...(prev[frameUri] ?? emptyLevel<KGFrame>()), loading: true, error: null },
    }));
    try {
      const resp: any = await apiService.getEntityFrames(spaceId, graphId, entityUri, {
        page_size: pageSize,
        offset,
        parent_frame_uri: frameUri,
        sort_by: FRAME_SEQUENCE_PROPERTY,
        sort_order: 'asc',
        include_slot_counts: true,
      });
      if (!isCurrent(key, seq)) return;
      const objects = hydrateQuads(resp.results || []);
      setChildrenByFrame(prev => ({
        ...prev,
        [frameUri]: {
          items: framesFromPage(objects),
          offset,
          totalCount: resp.total_count ?? 0,
          loading: false, loaded: true, error: null,
        },
      }));
      if (resp.slot_counts) {
        setSlotCounts(prev => ({ ...prev, ...resp.slot_counts }));
      }
    } catch (err) {
      if (!isCurrent(key, seq)) return;
      setChildrenByFrame(prev => ({
        ...prev,
        [frameUri]: {
          ...(prev[frameUri] ?? emptyLevel<KGFrame>()),
          loading: false, loaded: true,
          error: err instanceof Error ? err.message : 'Failed to load child frames',
        },
      }));
    }
  }, [spaceId, graphId, entityUri, pageSize]);

  /** Load a frame's slots and children once, on first expand. */
  const ensureFrameLoaded = useCallback((frameUri: string) => {
    setSlotsByFrame(prev => {
      if (prev[frameUri]?.loaded || prev[frameUri]?.loading) return prev;
      void fetchSlots(frameUri, 0);
      return { ...prev, [frameUri]: { ...emptyLevel<SlotEntry>(), loading: true } };
    });
    setChildrenByFrame(prev => {
      if (prev[frameUri]?.loaded || prev[frameUri]?.loading) return prev;
      void fetchChildFrames(frameUri, 0);
      return { ...prev, [frameUri]: { ...emptyLevel<KGFrame>(), loading: true } };
    });
  }, [fetchSlots, fetchChildFrames]);

  const setSlotOffset = useCallback((frameUri: string, offset: number) => {
    const level = slotsByFrame[frameUri];
    const next = clampOffset(offset, level?.totalCount ?? 0, pageSize);
    void fetchSlots(frameUri, next);
  }, [slotsByFrame, pageSize, fetchSlots]);

  const setChildOffset = useCallback((frameUri: string, offset: number) => {
    const level = childrenByFrame[frameUri];
    const next = clampOffset(offset, level?.totalCount ?? 0, pageSize);
    void fetchChildFrames(frameUri, next);
  }, [childrenByFrame, pageSize, fetchChildFrames]);

  const setTopOffset = useCallback((offset: number) => {
    void fetchTopFrames(clampOffset(offset, topFrames.totalCount, pageSize));
  }, [fetchTopFrames, topFrames.totalCount, pageSize]);

  // Reset everything when the entity or page size changes.
  useEffect(() => {
    setSlotsByFrame({});
    setChildrenByFrame({});
    setSlotCounts({});
    void fetchTopFrames(0);
  }, [fetchTopFrames]);

  return {
    topFrames,
    slotCounts,
    slotsByFrame,
    childrenByFrame,
    setTopOffset,
    setSlotOffset,
    setChildOffset,
    ensureFrameLoaded,
    refresh: () => fetchTopFrames(topFrames.offset),
  };
}
