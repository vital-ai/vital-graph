/**
 * API Service for VitalGraph with JWT authentication.
 * 
 * This service provides authenticated API calls with automatic token refresh
 * and proper Bearer token authentication headers.
 */

import { authService } from './AuthService';

export class ApiService {
  private baseUrl: string;

  constructor() {
    // Use current origin for API calls
    this.baseUrl = window.location.origin;
  }

  /**
   * Make authenticated API request with automatic token refresh
   */
  async makeRequest(url: string, options: RequestInit = {}): Promise<Response> {
    const fullUrl = url.startsWith('http') ? url : `${this.baseUrl}${url}`;
    
    // Get current token and add to headers
    const authHeader = authService.getAuthHeader();
    const headers = {
      'Content-Type': 'application/json',
      ...options.headers,
      ...authHeader,
    };

    const response = await fetch(fullUrl, {
      ...options,
      headers
    });

    // Handle 401 responses (token expired)
    if (response.status === 401 && 'Authorization' in authHeader) {
      console.log('🔄 Received 401, attempting token refresh...');
      
      const refreshed = await authService.refreshAccessToken();
      if (refreshed) {
        // Retry request with new token
        const newAuthHeader = authService.getAuthHeader();
        const retryHeaders = {
          ...headers,
          ...newAuthHeader
        };
        
        console.log('🔄 Retrying request with refreshed token...');
        return fetch(fullUrl, { ...options, headers: retryHeaders });
      }
      
      // If refresh failed, redirect to login
      console.log('🚪 Token refresh failed, redirecting to login');
      window.location.href = '/login';
    }

    return response;
  }

  /**
   * GET request with authentication
   */
  async get(url: string, options: RequestInit = {}): Promise<Response> {
    return this.makeRequest(url, {
      ...options,
      method: 'GET'
    });
  }

  /**
   * POST request with authentication
   */
  async post(url: string, data?: any, options: RequestInit = {}): Promise<Response> {
    return this.makeRequest(url, {
      ...options,
      method: 'POST',
      body: data ? JSON.stringify(data) : undefined
    });
  }

  /**
   * PUT request with authentication
   */
  async put(url: string, data?: any, options: RequestInit = {}): Promise<Response> {
    return this.makeRequest(url, {
      ...options,
      method: 'PUT',
      body: data ? JSON.stringify(data) : undefined
    });
  }

  /**
   * DELETE request with authentication
   */
  async delete(url: string, options: RequestInit = {}): Promise<Response> {
    return this.makeRequest(url, {
      ...options,
      method: 'DELETE'
    });
  }

  /**
   * PATCH request with authentication
   */
  async patch(url: string, data?: any, options: RequestInit = {}): Promise<Response> {
    return this.makeRequest(url, {
      ...options,
      method: 'PATCH',
      body: data ? JSON.stringify(data) : undefined
    });
  }

  // Convenience methods for common API calls

  /**
   * Get spaces
   */
  async getSpaces(): Promise<any[]> {
    const response = await this.get('/api/spaces');
    if (response.ok) {
      const data = await response.json();
      // Extract spaces array from SpacesListResponse structure
      return data.spaces || [];
    }
    throw new Error(`Failed to get spaces: ${response.status} ${response.statusText}`);
  }

  /**
   * Get users
   */
  async getUsers(): Promise<any[]> {
    const response = await this.get('/api/users');
    if (response.ok) {
      const data = await response.json();
      // Extract users array from UsersListResponse structure
      return data.users || [];
    }
    throw new Error(`Failed to get users: ${response.status} ${response.statusText}`);
  }

  /**
   * Create space
   */
  async createSpace(spaceData: any): Promise<any> {
    const response = await this.post('/api/spaces', spaceData);
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Failed to create space: ${response.status} ${response.statusText}`);
  }

  /**
   * Update space
   */
  async updateSpace(spaceId: string, spaceData: any): Promise<any> {
    const response = await this.put(`/api/spaces/${spaceId}`, spaceData);
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Failed to update space: ${response.status} ${response.statusText}`);
  }

  /**
   * Delete space
   */
  async deleteSpace(spaceId: string): Promise<any> {
    const response = await this.delete(`/api/spaces/${spaceId}`);
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Failed to delete space: ${response.status} ${response.statusText}`);
  }

  /**
   * Execute SPARQL query
   */
  async executeSparqlQuery(spaceId: string, query: string): Promise<any> {
    const response = await this.post(`/api/graphs/sparql/${spaceId}/query`, { query });
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Failed to execute SPARQL query: ${response.status} ${response.statusText}`);
  }

  // Graph management methods

  /**
   * Get graphs for a space
   */
  async getGraphs(spaceId: string): Promise<any[]> {
    const response = await this.get(`/api/graphs/sparql/${spaceId}/graphs`);
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Failed to get graphs: ${response.status} ${response.statusText}`);
  }

  /**
   * Get specific graph info
   */
  async getGraph(spaceId: string, graphUri: string): Promise<any> {
    const encodedGraphUri = encodeURIComponent(graphUri);
    const response = await this.get(`/api/graphs/sparql/${spaceId}/graph/${encodedGraphUri}`);
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Failed to get graph: ${response.status} ${response.statusText}`);
  }

  /**
   * Create a new graph
   */
  async createGraph(spaceId: string, graphUri: string): Promise<any> {
    const encodedGraphUri = encodeURIComponent(graphUri);
    const response = await this.put(`/api/graphs/sparql/${spaceId}/graph/${encodedGraphUri}`);
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Failed to create graph: ${response.status} ${response.statusText}`);
  }

  /**
   * Delete a graph
   */
  async deleteGraph(spaceId: string, graphUri: string, silent: boolean = false): Promise<any> {
    const encodedGraphUri = encodeURIComponent(graphUri);
    const url = silent 
      ? `/api/graphs/sparql/${spaceId}/graph/${encodedGraphUri}?silent=true`
      : `/api/graphs/sparql/${spaceId}/graph/${encodedGraphUri}`;
    const response = await this.delete(url);
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Failed to delete graph: ${response.status} ${response.statusText}`);
  }

  /**
   * Execute graph operation (CREATE, DROP, CLEAR, etc.)
   */
  async executeGraphOperation(spaceId: string, operation: string, targetGraphUri?: string, sourceGraphUri?: string, silent: boolean = false): Promise<any> {
    const requestBody = {
      operation,
      target_graph_uri: targetGraphUri,
      source_graph_uri: sourceGraphUri,
      silent
    };
    
    const response = await this.post(`/api/graphs/sparql/${spaceId}/graph`, requestBody);
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Failed to execute graph operation: ${response.status} ${response.statusText}`);
  }

  // Triples management methods

  /**
   * Get triples for a specific graph with pagination and filtering
   */
  async getTriples(spaceId: string, graphId: string, options: {
    page_size?: number;
    offset?: number;
    subject?: string;
    predicate?: string;
    object?: string;
    object_filter?: string;
  } = {}): Promise<any> {
    const params = new URLSearchParams();
    params.append('space_id', spaceId);
    params.append('graph_id', graphId);
    
    if (options.page_size) params.append('page_size', options.page_size.toString());
    if (options.offset) params.append('offset', options.offset.toString());
    if (options.subject) params.append('subject', options.subject);
    if (options.predicate) params.append('predicate', options.predicate);
    if (options.object) params.append('object', options.object);
    if (options.object_filter) params.append('object_filter', options.object_filter);

    const response = await this.get(`/api/graphs/triples?${params.toString()}`);
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Failed to get triples: ${response.status} ${response.statusText}`);
  }

  /**
   * Add triples via JSON-LD document
   */
  async addTriples(spaceId: string, graphId: string, document: any): Promise<any> {
    const params = new URLSearchParams();
    params.append('space_id', spaceId);
    params.append('graph_id', graphId);

    const response = await this.post(`/api/graphs/triples?${params.toString()}`, { document });
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Failed to add triples: ${response.status} ${response.statusText}`);
  }

  /**
   * Delete triples via JSON-LD document
   */
  async deleteTriples(spaceId: string, graphId: string, document: any): Promise<any> {
    const params = new URLSearchParams();
    params.append('space_id', spaceId);
    params.append('graph_id', graphId);

    const response = await this.delete(`/api/graphs/triples?${params.toString()}`, {
      body: JSON.stringify({ document })
    });
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Failed to delete triples: ${response.status} ${response.statusText}`);
  }

  /**
   * Health check
   */
  async healthCheck(): Promise<any> {
    const response = await this.get('/api/health');
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Health check failed: ${response.status} ${response.statusText}`);
  }
}

// Create singleton instance
export const apiService = new ApiService();
export default apiService;
