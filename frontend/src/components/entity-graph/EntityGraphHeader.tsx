import React from 'react';
import { Badge } from 'flowbite-react';
import { HiCube } from 'react-icons/hi';
import type { KGEntity } from '@vital-ai/vital-kg-model-ts';
import { getEntityLabel, getShortClassName, humanizeUrn } from '../../lib/entityGraphBuilder';
import CopyButton from '../CopyButton';

interface EntityGraphHeaderProps {
  entity: KGEntity | null;
  /**
   * Total frames for the entity — from the server's `total_count`, NOT from
   * what happens to be loaded. Deriving it from the rendered tree would
   * silently under-report once the view pages.
   */
  frameCount: number;
  onExpandAll: () => void;
  onCollapseAll: () => void;
  /** See EntityGraphViewer: expand-all is gated on nothing being paged. */
  expandAllDisabled?: boolean;
  expandAllReason?: string;
}

const EntityGraphHeader: React.FC<EntityGraphHeaderProps> = ({
  entity,
  frameCount,
  onExpandAll,
  onCollapseAll,
  expandAllDisabled = false,
  expandAllReason,
}) => {
  const label = entity ? getEntityLabel(entity) : '—';
  const entityClass = entity ? getShortClassName(entity.vitaltype) : '';
  const entityTypeLabel = entity?.kGEntityType ? humanizeUrn(entity.kGEntityType) : null;

  const btn =
    'text-xs px-2 py-1 rounded border border-gray-300 dark:border-gray-600 ' +
    'text-gray-600 dark:text-gray-300 enabled:hover:bg-gray-50 ' +
    'dark:enabled:hover:bg-gray-800 disabled:opacity-40 ' +
    'disabled:cursor-not-allowed transition-colors';

  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4 mb-4 shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3 min-w-0">
          <div className="p-2 rounded-lg bg-green-100 dark:bg-green-900/30 flex-shrink-0">
            <HiCube className="w-5 h-5 text-green-600 dark:text-green-400" />
          </div>
          <div className="min-w-0">
            <h2 className="text-lg font-bold text-gray-900 dark:text-white truncate" title={label}>
              {label}
            </h2>
            <div className="flex items-center gap-2 mt-1 flex-wrap">
              {entityTypeLabel && <Badge color="success" size="xs">{entityTypeLabel}</Badge>}
              {entityClass && <Badge color="gray" size="xs">{entityClass}</Badge>}
              <span className="text-xs text-gray-400" data-testid="entity-graph-frame-count">
                {frameCount} frame{frameCount !== 1 ? 's' : ''}
              </span>
            </div>
            {entity?.URI && (
              <div className="flex items-center gap-1 mt-1.5">
                <span
                  className="text-xs text-gray-400 dark:text-gray-500 font-mono truncate"
                  title={String(entity.URI)}
                >
                  {String(entity.URI)}
                </span>
                <CopyButton text={String(entity.URI)} size="sm" />
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2 flex-shrink-0">
          <button
            onClick={onExpandAll}
            className={btn}
            data-testid="entity-graph-expand-all"
            disabled={expandAllDisabled}
            title={expandAllReason}
          >
            Expand All
          </button>
          <button
            onClick={onCollapseAll}
            className={btn}
            data-testid="entity-graph-collapse-all"
          >
            Collapse All
          </button>
        </div>
      </div>
    </div>
  );
};

export default EntityGraphHeader;
