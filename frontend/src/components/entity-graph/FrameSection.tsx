import React, { useEffect, useState } from 'react';
import { Badge, Spinner } from 'flowbite-react';
import { HiChevronDown, HiChevronRight } from 'react-icons/hi';
import type { KGFrame } from '@vital-ai/vital-kg-model-ts';
import { getFrameLabel, getShortClassName, humanizeUrn } from '../../lib/entityGraphBuilder';
import { needsPaging, slotCountFor } from '../../lib/entityGraphPage';
import type { useEntityGraphPaging } from '../../lib/useEntityGraphPaging';
import SlotFieldRow from './SlotFieldRow';
import LevelPagination from './LevelPagination';

type Paging = ReturnType<typeof useEntityGraphPaging>;

interface FrameSectionProps {
  frame: KGFrame;
  paging: Paging;
  pageSize: number;
  depth?: number;
  defaultExpanded?: boolean;
}

/**
 * One frame card: its slots, then its child frames, each paged independently.
 *
 * Slots and child frames are fetched on FIRST EXPAND, not up front — a
 * collapsed frame costs nothing. The slot COUNT is known ahead of time from
 * the frame page's `slot_counts`, so a large frame can advertise its slot
 * pagination without being expanded.
 *
 * Rows are rendered in the order the server returned them; nothing here
 * re-sorts, which would scramble page boundaries.
 */
const FrameSection: React.FC<FrameSectionProps> = ({
  frame,
  paging,
  pageSize,
  depth = 0,
  defaultExpanded = true,
}) => {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const frameUri = String(frame.URI ?? '');

  const slots = paging.slotsByFrame[frameUri];
  const children = paging.childrenByFrame[frameUri];
  // Known before expanding, from the frame page's slot_counts map.
  const knownSlotCount = slotCountFor(paging.slotCounts, frameUri);
  const slotTotal = slots?.loaded ? slots.totalCount : knownSlotCount;

  useEffect(() => {
    if (expanded && frameUri) paging.ensureFrameLoaded(frameUri);
    // ensureFrameLoaded is idempotent; re-running on re-render is harmless.
  }, [expanded, frameUri, paging]);

  const label = getFrameLabel(frame);
  const frameClass = getShortClassName(frame.vitaltype);
  const frameTypeLabel = frame.kGFrameType ? humanizeUrn(frame.kGFrameType) : null;

  const shownSlots = slots?.items ?? [];
  const filled = shownSlots.filter(
    s => s.displayValue !== undefined && s.displayValue !== null && s.displayValue !== '',
  );
  // Before expanding we only know the total; after, we can show filled/shown.
  const completionText = slots?.loaded
    ? `${filled.length}/${shownSlots.length} shown · ${slotTotal} slot${slotTotal !== 1 ? 's' : ''}`
    : `${slotTotal} slot${slotTotal !== 1 ? 's' : ''}`;

  return (
    <div
      className={depth > 0 ? 'border-l-2 border-blue-300 dark:border-blue-700 pl-3 ml-1' : ''}
      data-testid="frame-card"
      data-frame-uri={frameUri}
    >
      <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 mb-2 shadow-sm">
        <button
          onClick={() => setExpanded(!expanded)}
          data-testid="frame-toggle"
          className="w-full flex items-center gap-2 px-4 py-3 text-left hover:bg-gray-50 dark:hover:bg-gray-800/50 rounded-t-lg transition-colors"
        >
          {expanded
            ? <HiChevronDown className="w-4 h-4 text-gray-500 flex-shrink-0" />
            : <HiChevronRight className="w-4 h-4 text-gray-500 flex-shrink-0" />}

          <span className="text-sm font-semibold text-gray-800 dark:text-gray-200 truncate">
            {label}
          </span>

          {frameTypeLabel && (
            <Badge color="purple" size="xs" className="flex-shrink-0">{frameTypeLabel}</Badge>
          )}
          {frameClass && frameClass !== 'KGFrame' && (
            <Badge color="gray" size="xs" className="flex-shrink-0">{frameClass}</Badge>
          )}

          <span
            className="ml-auto text-xs text-gray-400 dark:text-gray-500 flex-shrink-0"
            data-testid="frame-slot-count"
          >
            {completionText}
          </span>
        </button>

        {expanded && (
          <div className="border-t border-gray-100 dark:border-gray-800">
            {slots?.loading && !slots?.loaded ? (
              <div className="px-4 py-3 flex items-center gap-2 text-xs text-gray-400">
                <Spinner size="sm" /> Loading slots…
              </div>
            ) : slots?.error ? (
              <div className="px-4 py-3 text-xs text-red-500">{slots.error}</div>
            ) : shownSlots.length > 0 ? (
              <div className="grid grid-cols-1 md:grid-cols-2 divide-y md:divide-y-0 divide-gray-100 dark:divide-gray-800">
                {shownSlots.map((entry, idx) => (
                  <SlotFieldRow key={String(entry.slot.URI ?? idx)} entry={entry} />
                ))}
              </div>
            ) : (
              <div className="px-4 py-3 text-xs text-gray-400 italic">No slots</div>
            )}

            {/* Only when this frame's slots exceed one page. */}
            {needsPaging(slotTotal, pageSize) && (
              <LevelPagination
                label="Slots"
                testId="slot-pagination"
                offset={slots?.offset ?? 0}
                pageSize={pageSize}
                shown={shownSlots.length}
                totalCount={slotTotal}
                loading={slots?.loading}
                onOffsetChange={o => paging.setSlotOffset(frameUri, o)}
              />
            )}
          </div>
        )}
      </div>

      {expanded && (children?.items?.length ?? 0) > 0 && (
        <div className="mt-1">
          {children!.items.map((child, idx) => (
            <FrameSection
              key={String(child.URI ?? idx)}
              frame={child}
              paging={paging}
              pageSize={pageSize}
              depth={depth + 1}
              defaultExpanded={depth < 1}
            />
          ))}

          {needsPaging(children!.totalCount, pageSize) && (
            <LevelPagination
              label="Child frames"
              testId="child-frame-pagination"
              offset={children!.offset}
              pageSize={pageSize}
              shown={children!.items.length}
              totalCount={children!.totalCount}
              loading={children!.loading}
              onOffsetChange={o => paging.setChildOffset(frameUri, o)}
            />
          )}
        </div>
      )}
    </div>
  );
};

export default FrameSection;
