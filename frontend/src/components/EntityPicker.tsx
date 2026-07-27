import React, { useState, useEffect, useRef } from 'react';
import { TextInput, Spinner, Badge } from 'flowbite-react';
import { HiSearch, HiX } from 'react-icons/hi';
import { apiService } from '../services/ApiService';

const DEBOUNCE_MS = 250;
const RESULT_LIMIT = 10;

export interface PickedEntity {
  entity_id: string;
  primary_name: string;
  type_label?: string | null;
  type_key?: string | null;
}

interface EntityPickerProps {
  /** Currently selected entity, or null */
  value: PickedEntity | null;
  onChange: (entity: PickedEntity | null) => void;
  /** Entity IDs to omit from results (e.g. the entity being edited) */
  excludeIds?: string[];
  placeholder?: string;
  id?: string;
  'data-testid'?: string;
}

/**
 * Typeahead over the entity registry. Resolves a real entity_id so callers never
 * have to hand-type one — entity_relationship has FKs on both endpoints, so a
 * free-text ID field would fail server-side at save.
 */
const EntityPicker: React.FC<EntityPickerProps> = ({
  value, onChange, excludeIds = [], placeholder = 'Search entities...', id, 'data-testid': testId,
}) => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<PickedEntity[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Close the dropdown on outside click
  useEffect(() => {
    const onDocClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, []);

  useEffect(() => {
    if (!query.trim()) { setResults([]); return; }
    let cancelled = false;
    setLoading(true);
    const timer = setTimeout(async () => {
      try {
        const data = await apiService.listRegistryEntities({ query, limit: RESULT_LIMIT });
        if (cancelled) return;
        const entities: PickedEntity[] = (data.entities || [])
          .filter((e: PickedEntity) => !excludeIds.includes(e.entity_id));
        setResults(entities);
        setOpen(true);
      } catch {
        if (!cancelled) setResults([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, DEBOUNCE_MS);
    return () => { cancelled = true; clearTimeout(timer); };
    // excludeIds is a fresh array each render; join it so the effect keys on contents
  }, [query, excludeIds.join(',')]); // eslint-disable-line react-hooks/exhaustive-deps

  if (value) {
    return (
      <div className="flex items-center gap-2 h-[42px]" data-testid={testId}>
        <Badge color="purple" size="sm">{value.primary_name}</Badge>
        {value.type_label && <span className="text-xs text-gray-500">{value.type_label}</span>}
        <button
          type="button"
          aria-label="Clear selected entity"
          className="text-gray-400 hover:text-gray-600"
          onClick={() => { onChange(null); setQuery(''); setResults([]); }}
        >
          <HiX className="h-4 w-4" />
        </button>
      </div>
    );
  }

  return (
    <div className="relative" ref={containerRef}>
      <TextInput
        id={id}
        data-testid={testId}
        icon={HiSearch}
        placeholder={placeholder}
        value={query}
        autoComplete="off"
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => { if (results.length) setOpen(true); }}
      />
      {open && (loading || results.length > 0 || query.trim()) && (
        <div className="absolute z-20 mt-1 w-full max-h-64 overflow-y-auto rounded-lg border border-gray-200 bg-white shadow-lg dark:border-gray-600 dark:bg-gray-700">
          {loading ? (
            <div className="flex justify-center py-3"><Spinner size="sm" /></div>
          ) : results.length === 0 ? (
            <p className="px-3 py-2 text-sm text-gray-500">No matching entities.</p>
          ) : results.map((e) => (
            <button
              key={e.entity_id}
              type="button"
              className="block w-full px-3 py-2 text-left hover:bg-gray-50 dark:hover:bg-gray-600"
              onClick={() => { onChange(e); setOpen(false); setQuery(''); }}
            >
              <span className="text-sm text-gray-900 dark:text-white">{e.primary_name}</span>
              {(e.type_label || e.type_key) && (
                <span className="ml-2 text-xs text-gray-500">{e.type_label || e.type_key}</span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

export default EntityPicker;
