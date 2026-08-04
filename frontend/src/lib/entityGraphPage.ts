/**
 * Page assembly for the entity graph.
 *
 * `buildEntityGraphTree` (entityGraphBuilder.ts) assembles a COMPLETE entity
 * subgraph and sorts it client-side. That is correct only when the caller has
 * everything. These helpers are the paged counterpart: they convert one
 * server-returned page into renderable items and **never reorder** — the
 * server already applied the ordering (sequence numeric, unsequenced last,
 * URI tiebreak), and re-sorting a single page would scramble page boundaries.
 *
 * See planning/planning_ui/entity_graph_frame_slot_paging_plan.md.
 */

import { isKGFrame, isKGSlot, type GraphObject } from '@vital-ai/vital-kg-model-ts';
import type { KGFrame } from '@vital-ai/vital-kg-model-ts';
import type { KGSlot } from '@vital-ai/vital-kg-model-ts';

import { getSlotDisplayValue, type SlotEntry } from './entityGraphBuilder';

/** Frames from one page, in the order the server returned them. */
export function framesFromPage(objects: GraphObject[]): KGFrame[] {
  return objects.filter(isKGFrame) as KGFrame[];
}

/** Slots from one page, in the order the server returned them. */
export function slotsFromPage(objects: GraphObject[]): SlotEntry[] {
  return (objects.filter(isKGSlot) as KGSlot[]).map(slot => {
    const { value, dataType } = getSlotDisplayValue(slot);
    return {
      slot,
      // The slot endpoint returns slots only — the connecting edge is not part
      // of the page, and nothing in the row rendering needs it.
      edge: null,
      displayValue: value,
      dataType,
    } as SlotEntry;
  });
}

/** How many pages `total` items span at `pageSize` (at least 1). */
export function pageCount(total: number, pageSize: number): number {
  if (pageSize <= 0) return 1;
  return Math.max(1, Math.ceil(total / pageSize));
}

/**
 * Whether a level should show paging controls.
 *
 * Strictly greater: a level that exactly fills one page needs no controls.
 */
export function needsPaging(total: number, pageSize: number): boolean {
  return total > pageSize;
}

/**
 * Clamp an offset so it always lands on a real page.
 *
 * Deleting the last item on the final page would otherwise leave the caller
 * requesting an offset past the end and rendering an empty page.
 */
export function clampOffset(offset: number, total: number, pageSize: number): number {
  if (offset <= 0 || total <= 0 || pageSize <= 0) return 0;
  const lastPageOffset = (pageCount(total, pageSize) - 1) * pageSize;
  return Math.min(offset, lastPageOffset);
}

/** 1-based page number for an offset. */
export function pageNumber(offset: number, pageSize: number): number {
  if (pageSize <= 0) return 1;
  return Math.floor(offset / pageSize) + 1;
}

/**
 * "21–40 of 250" — the position line shown next to nested paging controls,
 * where scroll position is a poor cue for where you are.
 */
export function rangeLabel(offset: number, shown: number, total: number): string {
  if (total === 0 || shown === 0) return `0 of ${total}`;
  const first = offset + 1;
  const last = offset + shown;
  return `${first}–${last} of ${total}`;
}

/**
 * Slot count for a frame from a `slot_counts` map.
 *
 * A frame with zero slots is OMITTED from the server's map (a grouped COUNT
 * produces no row for it), so a missing key means 0 — not unknown.
 */
export function slotCountFor(
  counts: Record<string, number> | undefined | null,
  frameUri: string | undefined,
): number {
  if (!counts || !frameUri) return 0;
  return counts[frameUri] ?? 0;
}
