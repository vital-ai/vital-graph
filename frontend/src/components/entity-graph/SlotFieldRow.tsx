import React from 'react';
import { Badge } from 'flowbite-react';
import { HiCheck, HiX, HiExternalLink } from 'react-icons/hi';
import type { SlotEntry } from '../../lib/entityGraphBuilder';
import { getSlotLabel, getShortClassName } from '../../lib/entityGraphBuilder';
import ExpandableText from '../ExpandableText';
import CopyButton from '../CopyButton';

interface SlotFieldRowProps {
  entry: SlotEntry;
}

const SlotFieldRow: React.FC<SlotFieldRowProps> = ({ entry }) => {
  const { slot, displayValue, dataType } = entry;
  const label = getSlotLabel(slot);
  const slotClass = getShortClassName(slot.vitaltype);

  return (
    <div className="flex items-start gap-3 py-2 px-3 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">
      {/* Label + type badge */}
      <div className="flex-shrink-0 w-1/3 min-w-0">
        <div className="text-sm font-medium text-gray-700 dark:text-gray-300 truncate" title={label}>
          {label}
        </div>
        {slotClass && (
          <Badge color="gray" size="xs" className="mt-0.5 inline-block">
            {slotClass}
          </Badge>
        )}
      </div>

      {/* Value */}
      <div className="flex-1 min-w-0">
        <SlotValue value={displayValue} dataType={dataType} />
      </div>
    </div>
  );
};

/** Render the slot value based on its data type */
const SlotValue: React.FC<{ value: unknown; dataType: string }> = ({ value, dataType }) => {
  if (value === undefined || value === null || value === '') {
    return <span className="text-xs text-gray-400 dark:text-gray-500 italic">empty</span>;
  }

  switch (dataType) {
    case 'boolean':
      return value ? (
        <HiCheck className="w-4 h-4 text-green-500" />
      ) : (
        <HiX className="w-4 h-4 text-red-400" />
      );

    case 'integer':
    case 'long':
      return (
        <span className="text-sm text-gray-900 dark:text-white font-mono">
          {Number(value).toLocaleString()}
        </span>
      );

    case 'double':
      return (
        <span className="text-sm text-gray-900 dark:text-white font-mono">
          {Number(value).toLocaleString(undefined, { maximumFractionDigits: 6 })}
        </span>
      );

    case 'currency':
      return (
        <span className="text-sm text-gray-900 dark:text-white font-mono">
          ${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </span>
      );

    case 'datetime':
      return (
        <span className="text-sm text-gray-900 dark:text-white">
          {formatDateValue(value)}
        </span>
      );

    case 'uri':
      return (
        <div className="flex items-center gap-1 min-w-0">
          <a
            href={String(value)}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm text-blue-600 dark:text-blue-400 hover:underline truncate"
            title={String(value)}
          >
            {String(value)}
          </a>
          <HiExternalLink className="w-3 h-3 flex-shrink-0 text-gray-400" />
          <CopyButton text={String(value)} size="sm" />
        </div>
      );

    case 'choice':
      return <Badge color="info" size="xs">{String(value)}</Badge>;

    case 'multichoice':
      return (
        <div className="flex flex-wrap gap-1">
          {(Array.isArray(value) ? value : [value]).map((v, i) => (
            <Badge key={i} color="info" size="xs">{String(v)}</Badge>
          ))}
        </div>
      );

    case 'json':
    case 'code':
      return (
        <div className="max-h-40 overflow-auto rounded bg-gray-100 dark:bg-gray-800 p-2">
          <pre className="text-xs text-gray-800 dark:text-gray-200 whitespace-pre-wrap break-words font-mono">
            {typeof value === 'string' ? value : JSON.stringify(value, null, 2)}
          </pre>
        </div>
      );

    case 'longtext':
      return <ExpandableText text={String(value)} maxLines={3} />;

    case 'image':
      return (
        <div className="flex items-center gap-2">
          <img
            src={String(value)}
            alt="slot image"
            className="h-10 w-10 rounded object-cover border border-gray-200 dark:border-gray-700"
            onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
          />
          <span className="text-xs text-gray-500 truncate">{String(value)}</span>
        </div>
      );

    default:
      return (
        <span className="text-sm text-gray-900 dark:text-white break-words">
          {String(value)}
        </span>
      );
  }
};

function formatDateValue(value: unknown): string {
  if (!value) return '';
  try {
    const d = new Date(String(value));
    if (isNaN(d.getTime())) return String(value);
    return d.toLocaleString();
  } catch {
    return String(value);
  }
}

export default SlotFieldRow;
