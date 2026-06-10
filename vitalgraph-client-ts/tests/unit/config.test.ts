import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { ClientConfig } from '../../src/config/ClientConfig.js';

describe('ClientConfig', () => {
  it('should store serverUrl with trailing slash stripped', () => {
    const cfg = new ClientConfig({ serverUrl: 'http://localhost:8001/' });
    expect(cfg.serverUrl).toBe('http://localhost:8001');
  });

  it('should strip multiple trailing slashes', () => {
    const cfg = new ClientConfig({ serverUrl: 'http://localhost:8001///' });
    expect(cfg.serverUrl).toBe('http://localhost:8001');
  });

  it('should leave serverUrl without trailing slash untouched', () => {
    const cfg = new ClientConfig({ serverUrl: 'http://localhost:8001' });
    expect(cfg.serverUrl).toBe('http://localhost:8001');
  });

  it('should apply default timeout', () => {
    const cfg = new ClientConfig({ serverUrl: 'http://localhost' });
    expect(cfg.timeout).toBe(30_000);
  });

  it('should apply default maxRetries', () => {
    const cfg = new ClientConfig({ serverUrl: 'http://localhost' });
    expect(cfg.maxRetries).toBe(3);
  });

  it('should apply default retryDelay', () => {
    const cfg = new ClientConfig({ serverUrl: 'http://localhost' });
    expect(cfg.retryDelay).toBe(1_000);
  });

  it('should accept custom timeout', () => {
    const cfg = new ClientConfig({ serverUrl: 'http://localhost', timeout: 60_000 });
    expect(cfg.timeout).toBe(60_000);
  });

  it('should accept custom maxRetries', () => {
    const cfg = new ClientConfig({ serverUrl: 'http://localhost', maxRetries: 5 });
    expect(cfg.maxRetries).toBe(5);
  });

  it('should store credentials', () => {
    const cfg = new ClientConfig({
      serverUrl: 'http://localhost',
      username: 'admin',
      password: 'secret',
      apiKey: 'vg_key',
    });
    expect(cfg.username).toBe('admin');
    expect(cfg.password).toBe('secret');
    expect(cfg.apiKey).toBe('vg_key');
  });

  it('should leave optional fields undefined when not provided', () => {
    const cfg = new ClientConfig({ serverUrl: 'http://localhost' });
    expect(cfg.username).toBeUndefined();
    expect(cfg.password).toBeUndefined();
    expect(cfg.apiKey).toBeUndefined();
  });
});

describe('ClientConfig.fromEnvironment', () => {
  const origEnv = { ...process.env };

  beforeEach(() => {
    process.env = { ...origEnv };
  });

  afterEach(() => {
    process.env = origEnv;
  });

  it('should load config from LOCAL profile by default', () => {
    process.env.LOCAL_CLIENT_SERVER_URL = 'http://test-server:8001';
    process.env.LOCAL_CLIENT_AUTH_USERNAME = 'testuser';
    process.env.LOCAL_CLIENT_AUTH_PASSWORD = 'testpass';

    const cfg = ClientConfig.fromEnvironment();
    expect(cfg.serverUrl).toBe('http://test-server:8001');
    expect(cfg.username).toBe('testuser');
    expect(cfg.password).toBe('testpass');
  });

  it('should use VITALGRAPH_CLIENT_ENVIRONMENT to select profile', () => {
    process.env.VITALGRAPH_CLIENT_ENVIRONMENT = 'staging';
    process.env.STAGING_CLIENT_SERVER_URL = 'http://staging:8001';
    process.env.STAGING_CLIENT_AUTH_USERNAME = 'staginguser';

    const cfg = ClientConfig.fromEnvironment();
    expect(cfg.serverUrl).toBe('http://staging:8001');
    expect(cfg.username).toBe('staginguser');
  });

  it('should throw if SERVER_URL is missing', () => {
    delete process.env.LOCAL_CLIENT_SERVER_URL;
    expect(() => ClientConfig.fromEnvironment()).toThrow('Missing LOCAL_CLIENT_SERVER_URL');
  });

  it('should parse timeout from env (seconds → ms)', () => {
    process.env.LOCAL_CLIENT_SERVER_URL = 'http://test:8001';
    process.env.LOCAL_CLIENT_TIMEOUT = '60';

    const cfg = ClientConfig.fromEnvironment();
    expect(cfg.timeout).toBe(60_000);
  });

  it('should parse maxRetries from env', () => {
    process.env.LOCAL_CLIENT_SERVER_URL = 'http://test:8001';
    process.env.LOCAL_CLIENT_MAX_RETRIES = '5';

    const cfg = ClientConfig.fromEnvironment();
    expect(cfg.maxRetries).toBe(5);
  });

  it('should leave username undefined when env var is empty', () => {
    process.env.LOCAL_CLIENT_SERVER_URL = 'http://test:8001';
    process.env.LOCAL_CLIENT_AUTH_USERNAME = '';

    const cfg = ClientConfig.fromEnvironment();
    expect(cfg.username).toBeUndefined();
  });
});
