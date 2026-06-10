import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import type { VitalGraphClient } from '../../src/VitalGraphClient.js';
import { createTestClient, shouldSkip } from './setup.js';

describe.skipIf(shouldSkip())('SparqlEndpoint (integration)', () => {
  let client: VitalGraphClient;
  let testSpaceId: string | undefined;
  let testGraphId: string | undefined;

  beforeAll(async () => {
    client = await createTestClient();

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

  it('should execute a simple SPARQL SELECT query', async () => {
    if (!testSpaceId || !testGraphId) return;

    const response = await client.sparql.query(
      testSpaceId,
      'SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 5',
      testGraphId,
    );

    expect(response).toBeDefined();
  }, 30_000);
});
