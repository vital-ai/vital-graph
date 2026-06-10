import { describe, it, expect, afterAll } from 'vitest';
import { VitalGraphClient } from '../../src/VitalGraphClient.js';
import { VitalGraphClientError } from '../../src/utils/errors.js';
import { getTestConfig, shouldSkip } from './setup.js';

describe.skipIf(shouldSkip())('Authentication (integration)', () => {
  const clients: VitalGraphClient[] = [];

  afterAll(async () => {
    for (const c of clients) {
      await c.close().catch(() => {});
    }
  });

  it('should successfully authenticate with valid credentials', async () => {
    const { serverUrl, username, password } = getTestConfig();
    const client = new VitalGraphClient({ serverUrl, username, password });
    clients.push(client);

    await client.open();
    expect(client.isConnected()).toBe(true);
  });

  it('should fail with bad credentials', async () => {
    const { serverUrl } = getTestConfig();
    const client = new VitalGraphClient({
      serverUrl,
      username: 'nonexistent_user_xyz',
      password: 'wrong_password_xyz',
    });
    clients.push(client);

    await expect(client.open()).rejects.toThrow(VitalGraphClientError);
  });

  it('should open and close cleanly', async () => {
    const { serverUrl, username, password } = getTestConfig();
    const client = new VitalGraphClient({ serverUrl, username, password });
    clients.push(client);

    await client.open();
    expect(client.isConnected()).toBe(true);

    await client.close();
    expect(client.isConnected()).toBe(false);
  });

  it('should make authenticated requests after open', async () => {
    const { serverUrl, username, password } = getTestConfig();
    const client = new VitalGraphClient({ serverUrl, username, password });
    clients.push(client);

    await client.open();

    // A simple request to verify the token works
    const response = await client.spaces.list();
    expect(response).toBeDefined();
  });
});
