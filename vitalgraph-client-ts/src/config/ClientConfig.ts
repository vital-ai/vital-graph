/**
 * VitalGraph client configuration.
 *
 * Can be provided directly via constructor options or loaded from
 * profile-based environment variables (Node.js only).
 */

export interface VitalGraphClientOptions {
  serverUrl: string;
  username?: string;
  password?: string;
  apiKey?: string;
  timeout?: number;
  maxRetries?: number;
  retryDelay?: number;
}

const DEFAULT_TIMEOUT = 30_000;
const DEFAULT_MAX_RETRIES = 3;
const DEFAULT_RETRY_DELAY = 1_000;

export class ClientConfig {
  readonly serverUrl: string;
  readonly username?: string;
  readonly password?: string;
  readonly apiKey?: string;
  readonly timeout: number;
  readonly maxRetries: number;
  readonly retryDelay: number;

  constructor(options: VitalGraphClientOptions) {
    this.serverUrl = options.serverUrl.replace(/\/+$/, '');
    this.username = options.username;
    this.password = options.password;
    this.apiKey = options.apiKey;
    this.timeout = options.timeout ?? DEFAULT_TIMEOUT;
    this.maxRetries = options.maxRetries ?? DEFAULT_MAX_RETRIES;
    this.retryDelay = options.retryDelay ?? DEFAULT_RETRY_DELAY;
  }

  /**
   * Load configuration from profile-based environment variables (Node.js only).
   *
   * Reads VITALGRAPH_CLIENT_ENVIRONMENT to select profile, then loads
   * {PROFILE}_CLIENT_SERVER_URL, {PROFILE}_CLIENT_AUTH_USERNAME, etc.
   */
  static fromEnvironment(): ClientConfig {
    if (typeof process === 'undefined' || !process.env) {
      throw new Error('Environment variable loading is only available in Node.js');
    }

    const env = process.env.VITALGRAPH_CLIENT_ENVIRONMENT?.toUpperCase() ?? 'LOCAL';

    const get = (key: string, fallback = ''): string =>
      process.env[`${env}_CLIENT_${key}`] ?? fallback;

    const serverUrl = get('SERVER_URL');
    if (!serverUrl) {
      throw new Error(
        `Missing ${env}_CLIENT_SERVER_URL environment variable. ` +
        `Set VITALGRAPH_CLIENT_ENVIRONMENT and the corresponding profile variables.`,
      );
    }

    return new ClientConfig({
      serverUrl,
      username: get('AUTH_USERNAME') || undefined,
      password: get('AUTH_PASSWORD') || undefined,
      timeout: parseInt(get('TIMEOUT', '30'), 10) * 1000,
      maxRetries: parseInt(get('MAX_RETRIES', '3'), 10),
      retryDelay: parseInt(get('RETRY_DELAY', '1'), 10) * 1000,
    });
  }
}
