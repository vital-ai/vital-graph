/**
 * Shared seed constants — mirrors tests/shared/seed_ui_test_data.py.
 *
 * These constants ensure Playwright tests reference the exact same
 * URIs, IDs, and names produced by the Python seed script.
 */

export const ADMIN_USER = 'admin';
export const ADMIN_PASS = 'admin';

export const SPACE_ID = 'e2e_test_space';
export const SPACE_NAME = 'E2E Test Space';

export const GRAPH_ID = 'urn:e2e:graph:main';

export const ENTITIES = {
  alice: {
    uri: 'urn:e2e:entity:alice',
    name: 'Alice Anderson',
    description: 'Software engineer who likes sushi',
  },
  bob: {
    uri: 'urn:e2e:entity:bob',
    name: 'Bob Baker',
    description: 'Chef who likes pizza',
  },
  carol: {
    uri: 'urn:e2e:entity:carol',
    name: 'Carol Chen',
    description: 'Data scientist who likes ramen',
  },
} as const;

export const EXPECTED_ENTITY_COUNT = Object.keys(ENTITIES).length;

// Seeded KGDocument
export const SEEDED_DOCUMENT = {
  uri: 'urn:e2e:document:readme',
  title: 'E2E Readme',
} as const;

// Seeded registry entries
export const SEEDED_ENTITY_REGISTRY = {
  type_key: 'person',
  primary_name: 'E2E Registry Person',
} as const;

export const SEEDED_AGENT = {
  name: 'E2E Test Agent',
  agent_uri: 'urn:e2e:agent:test_bot',
} as const;

// Seeded indexes & mappings
export const SEEDED_FTS_INDEX = 'e2e_fts_idx' as const;
export const SEEDED_VECTOR_INDEX = 'e2e_vec_idx' as const;
export const SEEDED_SEARCH_MAPPING_TYPE = 'kgentity' as const;
export const SEEDED_FUZZY_MAPPING_TYPE = 'kgentity' as const;
