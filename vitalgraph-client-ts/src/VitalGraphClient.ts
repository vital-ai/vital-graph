import { ClientConfig, type VitalGraphClientOptions } from './config/ClientConfig.js';
import { VitalGraphClientError } from './utils/errors.js';

// Endpoint imports
import { SpacesEndpoint } from './endpoint/SpacesEndpoint.js';
import { GraphsEndpoint } from './endpoint/GraphsEndpoint.js';
import { ObjectsEndpoint } from './endpoint/ObjectsEndpoint.js';
import { KGTypesEndpoint } from './endpoint/KGTypesEndpoint.js';
import { KGEntitiesEndpoint } from './endpoint/KGEntitiesEndpoint.js';
import { KGFramesEndpoint } from './endpoint/KGFramesEndpoint.js';
import { KGRelationsEndpoint } from './endpoint/KGRelationsEndpoint.js';
import { KGQueriesEndpoint } from './endpoint/KGQueriesEndpoint.js';
import { KGDocumentsEndpoint } from './endpoint/KGDocumentsEndpoint.js';
import { UsersEndpoint } from './endpoint/UsersEndpoint.js';
import { ApiKeysEndpoint } from './endpoint/ApiKeysEndpoint.js';
import { FilesEndpoint } from './endpoint/FilesEndpoint.js';
import { SparqlEndpoint } from './endpoint/SparqlEndpoint.js';
import { TriplesEndpoint } from './endpoint/TriplesEndpoint.js';
import { ImportEndpoint } from './endpoint/ImportEndpoint.js';
import { ExportEndpoint } from './endpoint/ExportEndpoint.js';
import { MetricsEndpoint } from './endpoint/MetricsEndpoint.js';
import { AdminEndpoint } from './endpoint/AdminEndpoint.js';
import { ProcessEndpoint } from './endpoint/ProcessEndpoint.js';
import { VectorMappingsEndpoint } from './endpoint/VectorMappingsEndpoint.js';
import { FuzzyMappingsEndpoint } from './endpoint/FuzzyMappingsEndpoint.js';
import { VectorIndexesEndpoint } from './endpoint/VectorIndexesEndpoint.js';
import { SearchMappingsEndpoint } from './endpoint/SearchMappingsEndpoint.js';
import { FtsIndexesEndpoint } from './endpoint/FtsIndexesEndpoint.js';
import { GeoConfigEndpoint } from './endpoint/GeoConfigEndpoint.js';
import { GeoPointsEndpoint } from './endpoint/GeoPointsEndpoint.js';
import { AgentRegistryEndpoint } from './endpoint/AgentRegistryEndpoint.js';
import { EntityRegistryEndpoint } from './endpoint/EntityRegistryEndpoint.js';
import { OntologyEndpoint } from './endpoint/OntologyEndpoint.js';

interface AuthState {
  accessToken: string;
  refreshToken?: string;
  tokenExpiry?: number;
}

export class VitalGraphClient {
  readonly config: ClientConfig;
  private auth: AuthState | null = null;
  private _isOpen = false;

  // Endpoint instances
  readonly spaces: SpacesEndpoint;
  readonly graphs: GraphsEndpoint;
  readonly objects: ObjectsEndpoint;
  readonly kgtypes: KGTypesEndpoint;
  readonly kgentities: KGEntitiesEndpoint;
  readonly kgframes: KGFramesEndpoint;
  readonly kgrelations: KGRelationsEndpoint;
  readonly kgqueries: KGQueriesEndpoint;
  readonly kgdocuments: KGDocumentsEndpoint;
  readonly users: UsersEndpoint;
  readonly apiKeys: ApiKeysEndpoint;
  readonly files: FilesEndpoint;
  readonly sparql: SparqlEndpoint;
  readonly triples: TriplesEndpoint;
  readonly imports: ImportEndpoint;
  readonly exports: ExportEndpoint;
  readonly metrics: MetricsEndpoint;
  readonly admin: AdminEndpoint;
  readonly processes: ProcessEndpoint;
  readonly vectorMappings: VectorMappingsEndpoint;
  readonly fuzzyMappings: FuzzyMappingsEndpoint;
  readonly vectorIndexes: VectorIndexesEndpoint;
  readonly searchMappings: SearchMappingsEndpoint;
  readonly ftsIndexes: FtsIndexesEndpoint;
  readonly geoConfig: GeoConfigEndpoint;
  readonly geoPoints: GeoPointsEndpoint;
  readonly agentRegistry: AgentRegistryEndpoint;
  readonly entityRegistry: EntityRegistryEndpoint;
  readonly ontology: OntologyEndpoint;

  constructor(options: VitalGraphClientOptions) {
    this.config = new ClientConfig(options);

    this.spaces = new SpacesEndpoint(this);
    this.graphs = new GraphsEndpoint(this);
    this.objects = new ObjectsEndpoint(this);
    this.kgtypes = new KGTypesEndpoint(this);
    this.kgentities = new KGEntitiesEndpoint(this);
    this.kgframes = new KGFramesEndpoint(this);
    this.kgrelations = new KGRelationsEndpoint(this);
    this.kgqueries = new KGQueriesEndpoint(this);
    this.kgdocuments = new KGDocumentsEndpoint(this);
    this.users = new UsersEndpoint(this);
    this.apiKeys = new ApiKeysEndpoint(this);
    this.files = new FilesEndpoint(this);
    this.sparql = new SparqlEndpoint(this);
    this.triples = new TriplesEndpoint(this);
    this.imports = new ImportEndpoint(this);
    this.exports = new ExportEndpoint(this);
    this.metrics = new MetricsEndpoint(this);
    this.admin = new AdminEndpoint(this);
    this.processes = new ProcessEndpoint(this);
    this.vectorMappings = new VectorMappingsEndpoint(this);
    this.fuzzyMappings = new FuzzyMappingsEndpoint(this);
    this.vectorIndexes = new VectorIndexesEndpoint(this);
    this.searchMappings = new SearchMappingsEndpoint(this);
    this.ftsIndexes = new FtsIndexesEndpoint(this);
    this.geoConfig = new GeoConfigEndpoint(this);
    this.geoPoints = new GeoPointsEndpoint(this);
    this.agentRegistry = new AgentRegistryEndpoint(this);
    this.entityRegistry = new EntityRegistryEndpoint(this);
    this.ontology = new OntologyEndpoint(this);
  }

  /**
   * Create a client from environment variables (Node.js only).
   */
  static fromEnvironment(): VitalGraphClient {
    const config = ClientConfig.fromEnvironment();
    return new VitalGraphClient({
      serverUrl: config.serverUrl,
      username: config.username,
      password: config.password,
      apiKey: config.apiKey,
      timeout: config.timeout,
      maxRetries: config.maxRetries,
      retryDelay: config.retryDelay,
    });
  }

  // ---------------------------------------------------------------------------
  // Connection lifecycle
  // ---------------------------------------------------------------------------

  isConnected(): boolean {
    return this._isOpen;
  }

  /**
   * Open the client connection. Authenticates with the server via JWT login
   * or sets the API key as the Bearer token.
   */
  async open(): Promise<void> {
    if (this._isOpen) return;

    if (this.config.apiKey) {
      this.auth = { accessToken: this.config.apiKey };
      this._isOpen = true;
      return;
    }

    if (!this.config.username || !this.config.password) {
      throw new VitalGraphClientError(
        'Either apiKey or username/password must be provided',
      );
    }

    await this.authenticate();
    this._isOpen = true;
  }

  /**
   * Close the client connection.
   */
  async close(): Promise<void> {
    this.auth = null;
    this._isOpen = false;
  }

  // ---------------------------------------------------------------------------
  // Authentication
  // ---------------------------------------------------------------------------

  private async authenticate(): Promise<void> {
    const loginUrl = `${this.config.serverUrl}/api/login`;

    const body = new URLSearchParams({
      username: this.config.username!,
      password: this.config.password!,
    });

    const response = await fetch(loginUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body.toString(),
      signal: AbortSignal.timeout(this.config.timeout),
    });

    if (!response.ok) {
      throw new VitalGraphClientError(
        `Authentication failed with status ${response.status}`,
        response.status,
      );
    }

    const data = (await response.json()) as Record<string, unknown>;

    if (!data.access_token) {
      throw new VitalGraphClientError(
        "Server response missing 'access_token' field",
      );
    }

    const expiresIn = (data.expires_in as number) ?? 1800;

    this.auth = {
      accessToken: data.access_token as string,
      refreshToken: data.refresh_token as string | undefined,
      tokenExpiry: Date.now() + expiresIn * 1000,
    };
  }

  private async refreshAccessToken(): Promise<void> {
    if (!this.auth?.refreshToken) {
      await this.authenticate();
      return;
    }

    const refreshUrl = `${this.config.serverUrl}/api/refresh`;

    const response = await fetch(refreshUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${this.auth.refreshToken}`,
      },
      signal: AbortSignal.timeout(this.config.timeout),
    });

    if (!response.ok) {
      await this.authenticate();
      return;
    }

    const data = (await response.json()) as Record<string, unknown>;
    const expiresIn = (data.expires_in as number) ?? 1800;

    this.auth = {
      accessToken: (data.access_token as string) ?? this.auth.accessToken,
      refreshToken: (data.refresh_token as string) ?? this.auth.refreshToken,
      tokenExpiry: Date.now() + expiresIn * 1000,
    };
  }

  private isTokenExpiringSoon(): boolean {
    if (!this.auth?.tokenExpiry) return false;
    return Date.now() > this.auth.tokenExpiry - 60_000;
  }

  // ---------------------------------------------------------------------------
  // Request execution with retry
  // ---------------------------------------------------------------------------

  /**
   * Make an authenticated fetch request. Handles proactive token refresh
   * and reactive 401 retry.
   */
  async makeAuthenticatedRequest(
    url: string,
    init: RequestInit,
  ): Promise<Response> {
    if (!this.auth) {
      throw new VitalGraphClientError('Client is not authenticated');
    }

    // Proactive refresh
    if (this.isTokenExpiringSoon() && !this.config.apiKey) {
      await this.refreshAccessToken();
    }

    let lastError: Error | undefined;

    for (let attempt = 0; attempt <= this.config.maxRetries; attempt++) {
      const headers = new Headers(init.headers);
      headers.set('Authorization', `Bearer ${this.auth.accessToken}`);
      headers.set('Accept', 'application/json');

      try {
        const response = await fetch(url, {
          ...init,
          headers,
          signal: AbortSignal.timeout(this.config.timeout),
        });

        // Reactive 401 retry
        if (response.status === 401 && !this.config.apiKey && attempt < this.config.maxRetries) {
          await this.refreshAccessToken();
          continue;
        }

        if (!response.ok) {
          const body = await response.text().catch(() => '');
          throw new VitalGraphClientError(
            `Request failed: ${response.status} ${response.statusText} — ${body}`,
            response.status,
          );
        }

        return response;
      } catch (err) {
        lastError = err instanceof Error ? err : new Error(String(err));

        if (err instanceof VitalGraphClientError) throw err;

        // Exponential backoff for transient errors
        if (attempt < this.config.maxRetries) {
          const delay = this.config.retryDelay * Math.pow(2, attempt);
          await new Promise((r) => setTimeout(r, delay));
          continue;
        }
      }
    }

    throw lastError ?? new VitalGraphClientError('Request failed after retries');
  }
}
