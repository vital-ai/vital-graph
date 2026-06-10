import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { VitalGraphClient } from '../../src/VitalGraphClient.js';
import { VitalGraphClientError } from '../../src/utils/errors.js';

describe('VitalGraphClient', () => {
  describe('constructor', () => {
    it('should create a client with config', () => {
      const client = new VitalGraphClient({ serverUrl: 'http://localhost:8001' });
      expect(client.config.serverUrl).toBe('http://localhost:8001');
      expect(client.isConnected()).toBe(false);
    });

    it('should initialize all endpoint instances', () => {
      const client = new VitalGraphClient({ serverUrl: 'http://localhost:8001' });
      expect(client.spaces).toBeDefined();
      expect(client.graphs).toBeDefined();
      expect(client.objects).toBeDefined();
      expect(client.kgtypes).toBeDefined();
      expect(client.kgentities).toBeDefined();
      expect(client.kgframes).toBeDefined();
      expect(client.kgrelations).toBeDefined();
      expect(client.kgqueries).toBeDefined();
      expect(client.kgdocuments).toBeDefined();
      expect(client.users).toBeDefined();
      expect(client.apiKeys).toBeDefined();
      expect(client.files).toBeDefined();
      expect(client.sparql).toBeDefined();
      expect(client.triples).toBeDefined();
      expect(client.imports).toBeDefined();
      expect(client.exports).toBeDefined();
      expect(client.metrics).toBeDefined();
      expect(client.admin).toBeDefined();
      expect(client.processes).toBeDefined();
      expect(client.vectorMappings).toBeDefined();
      expect(client.vectorIndexes).toBeDefined();
      expect(client.geoConfig).toBeDefined();
      expect(client.geoPoints).toBeDefined();
    });
  });

  describe('open / close', () => {
    it('should open with API key without network call', async () => {
      const client = new VitalGraphClient({
        serverUrl: 'http://localhost:8001',
        apiKey: 'vg_test_key',
      });
      await client.open();
      expect(client.isConnected()).toBe(true);
    });

    it('should throw if no credentials are provided', async () => {
      const client = new VitalGraphClient({ serverUrl: 'http://localhost:8001' });
      await expect(client.open()).rejects.toThrow(VitalGraphClientError);
      await expect(client.open()).rejects.toThrow('apiKey or username/password');
    });

    it('should close and reset state', async () => {
      const client = new VitalGraphClient({
        serverUrl: 'http://localhost:8001',
        apiKey: 'vg_test_key',
      });
      await client.open();
      expect(client.isConnected()).toBe(true);

      await client.close();
      expect(client.isConnected()).toBe(false);
    });

    it('should be idempotent when already open', async () => {
      const client = new VitalGraphClient({
        serverUrl: 'http://localhost:8001',
        apiKey: 'vg_test_key',
      });
      await client.open();
      await client.open(); // no-op
      expect(client.isConnected()).toBe(true);
    });
  });

  describe('makeAuthenticatedRequest', () => {
    let client: VitalGraphClient;

    beforeEach(async () => {
      client = new VitalGraphClient({
        serverUrl: 'http://localhost:8001',
        apiKey: 'vg_test_key',
        maxRetries: 0,
        timeout: 5000,
      });
      await client.open();
    });

    afterEach(async () => {
      await client.close();
      vi.restoreAllMocks();
    });

    it('should throw if not authenticated', async () => {
      const unauthClient = new VitalGraphClient({ serverUrl: 'http://localhost:8001' });
      await expect(
        unauthClient.makeAuthenticatedRequest('http://localhost:8001/api/spaces', { method: 'GET' }),
      ).rejects.toThrow('not authenticated');
    });

    it('should send Authorization header', async () => {
      let capturedHeaders: Headers | undefined;

      vi.spyOn(globalThis, 'fetch').mockImplementation(async (_url, init) => {
        capturedHeaders = init?.headers as Headers;
        return new Response(JSON.stringify({ spaces: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      });

      await client.makeAuthenticatedRequest('http://localhost:8001/api/spaces', {
        method: 'GET',
      });

      expect(capturedHeaders?.get('Authorization')).toBe('Bearer vg_test_key');
      expect(capturedHeaders?.get('Accept')).toBe('application/json');
    });

    it('should throw VitalGraphClientError on non-ok response', async () => {
      vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
        return new Response('Not Found', {
          status: 404,
          statusText: 'Not Found',
        });
      });

      await expect(
        client.makeAuthenticatedRequest('http://localhost:8001/api/spaces', { method: 'GET' }),
      ).rejects.toThrow(VitalGraphClientError);
    });

    it('should include status code in error', async () => {
      vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
        return new Response('Server Error', {
          status: 500,
          statusText: 'Internal Server Error',
        });
      });

      try {
        await client.makeAuthenticatedRequest('http://localhost:8001/api/test', { method: 'GET' });
        expect.unreachable('Should have thrown');
      } catch (err) {
        expect(err).toBeInstanceOf(VitalGraphClientError);
        expect((err as VitalGraphClientError).statusCode).toBe(500);
      }
    });
  });

  describe('JWT auth flow', () => {
    afterEach(() => {
      vi.restoreAllMocks();
    });

    it('should authenticate with username/password', async () => {
      let loginCalled = false;

      vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
        const urlStr = typeof url === 'string' ? url : url.toString();
        if (urlStr.includes('/api/login')) {
          loginCalled = true;
          return new Response(
            JSON.stringify({ access_token: 'jwt_token_abc', refresh_token: 'ref_123', expires_in: 3600 }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          );
        }
        return new Response('Not Found', { status: 404 });
      });

      const client = new VitalGraphClient({
        serverUrl: 'http://localhost:8001',
        username: 'admin',
        password: 'secret',
      });

      await client.open();
      expect(loginCalled).toBe(true);
      expect(client.isConnected()).toBe(true);
    });

    it('should throw on failed login', async () => {
      vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
        return new Response('Unauthorized', { status: 401, statusText: 'Unauthorized' });
      });

      const client = new VitalGraphClient({
        serverUrl: 'http://localhost:8001',
        username: 'bad',
        password: 'bad',
      });

      await expect(client.open()).rejects.toThrow('Authentication failed');
    });

    it('should throw when server response missing access_token', async () => {
      vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
        return new Response(
          JSON.stringify({ message: 'ok but no token' }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      });

      const client = new VitalGraphClient({
        serverUrl: 'http://localhost:8001',
        username: 'admin',
        password: 'pass',
      });

      await expect(client.open()).rejects.toThrow("missing 'access_token'");
    });
  });
});
