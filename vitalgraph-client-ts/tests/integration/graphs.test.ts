import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import type { VitalGraphClient } from '../../src/VitalGraphClient.js';
import { createTestClient, shouldSkip } from './setup.js';

describe.skipIf(shouldSkip())('GraphsEndpoint (integration)', () => {
  let client: VitalGraphClient;
  let testSpaceId: string | undefined;

  beforeAll(async () => {
    client = await createTestClient();

    // Pick the first available space
    const spacesResp = await client.spaces.list();
    if (spacesResp.spaces.length > 0) {
      testSpaceId = spacesResp.spaces[0].space as string;
    }
  });

  afterAll(async () => {
    await client?.close();
  });

  it('should list graphs for a space', async () => {
    if (!testSpaceId) return;
    const response = await client.graphs.list(testSpaceId);
    expect(response).toBeDefined();
    // Server returns either a list response or an array
    expect(Array.isArray(response.graphs) || Array.isArray(response)).toBe(true);
  });
});
