import { VitalGraphClient } from './VitalGraphClient.js';
import type { VitalGraphClientOptions } from './config/ClientConfig.js';

/**
 * Create and open a VitalGraphClient in a single call.
 *
 * @example
 * ```typescript
 * import { createClient } from '@vital-ai/vitalgraph-client';
 *
 * const client = await createClient({
 *   serverUrl: 'http://localhost:8001',
 *   username: 'admin',
 *   password: 'admin',
 * });
 *
 * const spaces = await client.spaces.list();
 * await client.close();
 * ```
 */
export async function createClient(options: VitalGraphClientOptions): Promise<VitalGraphClient> {
  const client = new VitalGraphClient(options);
  await client.open();
  return client;
}
