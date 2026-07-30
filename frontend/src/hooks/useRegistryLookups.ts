import { useState, useEffect } from 'react';
import { apiService } from '../services/ApiService';

export interface EntityTypeOption {
  type_id: number;
  type_key: string;
  type_label: string;
  type_description?: string | null;
}

export interface CategoryOption {
  category_id: number;
  category_key: string;
  category_label: string;
  category_description?: string | null;
}

export interface RelationshipTypeOption {
  relationship_type_id: number;
  type_key: string;
  type_label: string;
  inverse_key?: string | null;
}

/** Lookup tables change rarely — cache the in-flight promise for the session. */
const cache = new Map<string, Promise<unknown[]>>();

function useLookup<T>(key: string, fetcher: () => Promise<unknown[]>) {
  const [items, setItems] = useState<T[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!cache.has(key)) cache.set(key, fetcher());
    cache.get(key)!
      .then((data) => {
        if (cancelled) return;
        setItems((Array.isArray(data) ? data : []) as T[]);
        setLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        cache.delete(key); // allow a retry on next mount
        setError(err instanceof Error ? err.message : 'Failed to load lookup values');
        setLoading(false);
      });
    return () => { cancelled = true; };
  }, [key, fetcher]);

  return { items, loading, error };
}


// These routes return a ResultStatus envelope; pull the domain-named list out of
// it here so the shared useLookup hook keeps working with plain arrays.
const fetchEntityTypes = async () =>
  (await apiService.listRegistryEntityTypes()).entity_types ?? [];
const fetchCategories = async () =>
  (await apiService.listRegistryCategories()).categories ?? [];
const fetchRelationshipTypes = async () =>
  (await apiService.listRegistryRelationshipTypes()).relationship_types ?? [];

export const useEntityTypes = () =>
  useLookup<EntityTypeOption>('entity-types', fetchEntityTypes);

export const useCategories = () =>
  useLookup<CategoryOption>('categories', fetchCategories);

export const useRelationshipTypes = () =>
  useLookup<RelationshipTypeOption>('relationship-types', fetchRelationshipTypes);

/**
 * Identifier namespaces and alias types.
 *
 * These are now managed tables (identifier_type / alias_type), fetched via the
 * per-kind metadata list. Active-only, so a deactivated value stops being
 * suggested. New values still auto-register when an identifier/alias is written,
 * so the list stays complete without pre-declaration.
 */
interface MetadataListItem { key: string; label: string }

const fetchIdentifierTypes = () =>
  apiService.listRegistryMetadata('identifier-types') as Promise<unknown[]>;
const fetchAliasTypes = () =>
  apiService.listRegistryMetadata('alias-types') as Promise<unknown[]>;

function useTagValues(cacheKey: string, fetcher: () => Promise<unknown[]>) {
  const { items, loading, error } = useLookup<MetadataListItem>(cacheKey, fetcher);
  return { items, names: items.map((v) => v.key), loading, error };
}

export const useIdentifierNamespaces = () => useTagValues('identifier-type-values', fetchIdentifierTypes);
export const useAliasTypes = () => useTagValues('alias-type-values', fetchAliasTypes);

/** Invalidate cached lookups (call after creating a type/category). */
export function invalidateRegistryLookups() {
  cache.clear();
}
