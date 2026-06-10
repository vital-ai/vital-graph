import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import type { VitalGraphClient } from '../../src/VitalGraphClient.js';
import { createTestClient, shouldSkip } from './setup.js';

describe.skipIf(shouldSkip())('SpacesEndpoint (integration)', () => {
  let client: VitalGraphClient;

  beforeAll(async () => {
    client = await createTestClient();
  });

  afterAll(async () => {
    await client?.close();
  });

  it('should list spaces', async () => {
    const response = await client.spaces.list();
    expect(response).toBeDefined();
    expect(Array.isArray(response.spaces)).toBe(true);
    expect(response.spaces.length).toBeGreaterThan(0);
  });

  it('should have spaces with expected shape', async () => {
    const response = await client.spaces.list();
    if (response.spaces.length > 0) {
      const space = response.spaces[0];
      // Server Space model uses 'space' as the identifier field
      expect(space.space).toBeDefined();
    }
  });
});
