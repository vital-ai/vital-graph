import React from 'react';
import { HiChevronLeft, HiChevronRight } from 'react-icons/hi';
import { pageCount, pageNumber, rangeLabel } from '../../lib/entityGraphPage';

interface LevelPaginationProps {
  /** What is being paged, for the position line: "Slots 21–40 of 250". */
  label: string;
  offset: number;
  pageSize: number;
  /** Rows currently rendered at this level. */
  shown: number;
  totalCount: number;
  loading?: boolean;
  onOffsetChange: (offset: number) => void;
  testId?: string;
}

/**
 * Explicit prev/next paging for one level of the entity graph.
 *
 * Deliberately not "show more" or infinite scroll: inside a nested tree the
 * user needs to know where they are, so the control carries an explicit
 * position line. The caller decides whether to render it at all — it appears
 * only when a level's total exceeds one page.
 *
 * Controls are disabled rather than hidden while a page is in flight, so the
 * card does not change height mid-interaction.
 */
const LevelPagination: React.FC<LevelPaginationProps> = ({
  label,
  offset,
  pageSize,
  shown,
  totalCount,
  loading = false,
  onOffsetChange,
  testId,
}) => {
  const pages = pageCount(totalCount, pageSize);
  const current = pageNumber(offset, pageSize);
  const atFirst = current <= 1;
  const atLast = current >= pages;

  const btn =
    'p-1 rounded border border-gray-300 dark:border-gray-600 text-gray-600 ' +
    'dark:text-gray-300 enabled:hover:bg-gray-100 dark:enabled:hover:bg-gray-800 ' +
    'disabled:opacity-40 disabled:cursor-not-allowed transition-colors';

  return (
    <div
      className="flex items-center gap-2 px-4 py-2 text-xs text-gray-500 dark:text-gray-400 border-t border-gray-100 dark:border-gray-800"
      data-testid={testId}
    >
      <span data-testid={testId ? `${testId}-range` : undefined}>
        {label} {rangeLabel(offset, shown, totalCount)}
      </span>

      <div className="ml-auto flex items-center gap-1">
        <button
          type="button"
          className={btn}
          aria-label="Previous page"
          data-testid={testId ? `${testId}-prev` : undefined}
          disabled={atFirst || loading}
          onClick={() => onOffsetChange(Math.max(0, offset - pageSize))}
        >
          <HiChevronLeft className="w-3.5 h-3.5" />
        </button>

        <span className="tabular-nums px-1">
          {current} / {pages}
        </span>

        <button
          type="button"
          className={btn}
          aria-label="Next page"
          data-testid={testId ? `${testId}-next` : undefined}
          disabled={atLast || loading}
          onClick={() => onOffsetChange(offset + pageSize)}
        >
          <HiChevronRight className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
};

export default LevelPagination;
