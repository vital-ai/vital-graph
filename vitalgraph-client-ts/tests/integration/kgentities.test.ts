import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import type { VitalGraphClient } from '../../src/VitalGraphClient.js';
import { createTestClient, shouldSkip } from './setup.js';

describe.skipIf(shouldSkip())('KGEntitiesEndpoint (integration)', () => {
  let client: VitalGraphClient;
  let testSpaceId: string | undefined;
  let testGraphId: string | undefined;

  beforeAll(async () => {
    client = await createTestClient();

    // Pick the first available space + graph
    const spacesResp = await client.spaces.list();
    if (spacesResp.spaces.length > 0) {
      testSpaceId = spacesResp.spaces[0].space as string;
      const graphsResp = await client.graphs.list(testSpaceId);
      const resp = graphsResp as unknown as Record<string, unknown>;
      const graphs = (resp.graphs ?? resp) as Record<string, unknown>[];
      if (Array.isArray(graphs) && graphs.length > 0) {
        testGraphId = (graphs[0].graph_uri ?? graphs[0].graphURI ?? graphs[0].id) as string;
      }
    }
  });

  afterAll(async () => {
    await client?.close();
  });

  it('should list entities with pagination', async () => {
    if (!testSpaceId || !testGraphId) return;

    const response = await client.kgentities.list(testSpaceId, testGraphId, {
      pageSize: 5,
      offset: 0,
    });

    expect(response).toBeDefined();
  }, 30_000);

  it('should list entities with search filter', async () => {
    if (!testSpaceId || !testGraphId) return;

    const response = await client.kgentities.list(testSpaceId, testGraphId, {
      pageSize: 5,
      search: 'test',
    });

    expect(response).toBeDefined();
  }, 30_000);

  it('should handle entity type URI filter', async () => {
    if (!testSpaceId || !testGraphId) return;

    const response = await client.kgentities.list(testSpaceId, testGraphId, {
      pageSize: 5,
      entityTypeUri: 'http://vital.ai/ontology/haley-ai-kg#KGEntity',
    });

    expect(response).toBeDefined();
  }, 30_000);
});
