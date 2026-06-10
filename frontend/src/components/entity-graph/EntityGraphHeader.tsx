import React from 'react';
import { Badge } from 'flowbite-react';
import { HiCube } from 'react-icons/hi';
import type { EntityGraphTree } from '../../lib/entityGraphBuilder';
import { getEntityLabel, getShortClassName, humanizeUrn } from '../../lib/entityGraphBuilder';
import CopyButton from '../CopyButton';

interface EntityGraphHeaderProps {
  tree: EntityGraphTree;
  onExpandAll: () => void;
  onCollapseAll: () => void;
}

const EntityGraphHeader: React.FC<EntityGraphHeaderProps> = ({
  tree,
  onExpandAll,
  onCollapseAll,
}) => {
  const { entity, totalFrameCount, totalSlotCount } = tree;
  const label = getEntityLabel(entity);
  const entityClass = getShortClassName(entity.vitaltype);
  const entityTypeLabel = entity.kGEntityType ? humanizeUrn(entity.kGEntityType) : null;

  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4 mb-4 shadow-sm">
      <div className="flex items-start justify-between gap-4">
        {/* Left: entity info */}
        <div className="flex items-start gap-3 min-w-0">
          <div className="p-2 rounded-lg bg-green-100 dark:bg-green-900/30 flex-shrink-0">
            <HiCube className="w-5 h-5 text-green-600 dark:text-green-400" />
          </div>
          <div className="min-w-0">
            <h2 className="text-lg font-bold text-gray-900 dark:text-white truncate" title={label}>
              {label}
            </h2>
            <div className="flex items-center gap-2 mt-1 flex-wrap">
              {entityTypeLabel && (
                <Badge color="success" size="xs">{entityTypeLabel}</Badge>
              )}
              {entityClass && (
                <Badge color="gray" size="xs">{entityClass}</Badge>
              )}
              <span className="text-xs text-gray-400">
                {totalFrameCount} frame{totalFrameCount !== 1 ? 's' : ''}, {totalSlotCount} slot{totalSlotCount !== 1 ? 's' : ''}
              </span>
            </div>
            {entity.URI && (
              <div className="flex items-center gap-1 mt-1.5">
                <span className="text-xs text-gray-400 dark:text-gray-500 font-mono truncate" title={entity.URI}>
                  {entity.URI}
                </span>
                <CopyButton text={entity.URI} size="sm" />
              </div>
            )}
          </div>
        </div>

        {/* Right: expand/collapse */}
        <div className="flex items-center gap-2 flex-shrink-0">
          <button
            onClick={onExpandAll}
            className="text-xs px-2 py-1 rounded border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
          >
            Expand All
          </button>
          <button
            onClick={onCollapseAll}
            className="text-xs px-2 py-1 rounded border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
          >
            Collapse All
          </button>
        </div>
      </div>
    </div>
  );
};

export default EntityGraphHeader;
