import React, { useState } from 'react';
import { Badge } from 'flowbite-react';
import { HiChevronDown, HiChevronRight } from 'react-icons/hi';
import type { FrameNode } from '../../lib/entityGraphBuilder';
import { getFrameLabel, getShortClassName, humanizeUrn } from '../../lib/entityGraphBuilder';
import SlotFieldRow from './SlotFieldRow';

interface FrameSectionProps {
  node: FrameNode;
  depth?: number;
  defaultExpanded?: boolean;
}

const FrameSection: React.FC<FrameSectionProps> = ({
  node,
  depth = 0,
  defaultExpanded = true,
}) => {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const { frame, slots, childFrames } = node;

  const label = getFrameLabel(frame);
  const frameClass = getShortClassName(frame.vitaltype);
  const frameTypeLabel = frame.kGFrameType ? humanizeUrn(frame.kGFrameType) : null;
  const filledSlots = slots.filter(s => s.displayValue !== undefined && s.displayValue !== null && s.displayValue !== '');
  const completionText = `${filledSlots.length}/${slots.length} slots`;

  return (
    <div className={`${depth > 0 ? 'border-l-2 border-blue-300 dark:border-blue-700 pl-3 ml-1' : ''}`}>
      <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 mb-2 shadow-sm">
        {/* Section header */}
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full flex items-center gap-2 px-4 py-3 text-left hover:bg-gray-50 dark:hover:bg-gray-800/50 rounded-t-lg transition-colors"
        >
          {expanded ? (
            <HiChevronDown className="w-4 h-4 text-gray-500 flex-shrink-0" />
          ) : (
            <HiChevronRight className="w-4 h-4 text-gray-500 flex-shrink-0" />
          )}

          <span className="text-sm font-semibold text-gray-800 dark:text-gray-200 truncate">
            {label}
          </span>

          {frameTypeLabel && (
            <Badge color="purple" size="xs" className="flex-shrink-0">
              {frameTypeLabel}
            </Badge>
          )}

          {frameClass && frameClass !== 'KGFrame' && (
            <Badge color="gray" size="xs" className="flex-shrink-0">
              {frameClass}
            </Badge>
          )}

          <span className="ml-auto text-xs text-gray-400 dark:text-gray-500 flex-shrink-0">
            {completionText}
          </span>
        </button>

        {/* Slots grid */}
        {expanded && (
          <div className="border-t border-gray-100 dark:border-gray-800">
            {slots.length > 0 ? (
              <div className="grid grid-cols-1 md:grid-cols-2 divide-y md:divide-y-0 divide-gray-100 dark:divide-gray-800">
                {slots.map((entry, idx) => (
                  <SlotFieldRow key={entry.slot.URI || idx} entry={entry} />
                ))}
              </div>
            ) : (
              <div className="px-4 py-3 text-xs text-gray-400 italic">No slots</div>
            )}
          </div>
        )}
      </div>

      {/* Child frames (recursive) */}
      {expanded && childFrames.length > 0 && (
        <div className="mt-1">
          {childFrames.map((childNode, idx) => (
            <FrameSection
              key={childNode.frame.URI || idx}
              node={childNode}
              depth={depth + 1}
              defaultExpanded={depth < 1}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export default FrameSection;
