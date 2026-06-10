/**
 * Shared setup for integration tests.
 *
 * Reads environment variables to connect to a live VitalGraph server.
 * Tests are skipped if LOCAL_CLIENT_SERVER_URL is not set.
 */
import { VitalGraphClient } from '../../src/VitalGraphClient.js';

export function getTestConfig(): {
  serverUrl: string;
  username: string;
  password: string;
} {
  return {
    serverUrl: process.env.LOCAL_CLIENT_SERVER_URL ?? 'http://localhost:8001',
    username: process.env.LOCAL_CLIENT_AUTH_USERNAME ?? 'admin',
    password: process.env.LOCAL_CLIENT_AUTH_PASSWORD ?? 'admin',
  };
}

export function shouldSkip(): boolean {
  return !process.env.LOCAL_CLIENT_SERVER_URL;
}

export async function createTestClient(): Promise<VitalGraphClient> {
  const { serverUrl, username, password } = getTestConfig();
  const client = new VitalGraphClient({
    serverUrl,
    username,
    password,
    timeout: 30_000,
    maxRetries: 1,
    retryDelay: 500,
  });
  await client.open();
  return client;
}

/**
 * Generate a unique test space ID to avoid collisions.
 */
export function testSpaceId(): string {
  return `ts-client-test-${Date.now()}`;
}
