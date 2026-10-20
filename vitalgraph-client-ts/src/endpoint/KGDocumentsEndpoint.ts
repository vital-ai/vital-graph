import { BaseEndpoint } from './BaseEndpoint.js';
import { validateRequired } from '../utils/params.js';
import type {
  VitalGraphResponse,
  KGDocumentResponse,
  KGDocumentsListResponse,
  KGDocumentCreateResponse,
  KGDocumentUploadResponse,
  KGDocumentUpdateResponse,
  KGDocumentDeleteResponse,
  KGDocumentSegmentsResponse,
} from '../response/types.js';

export class KGDocumentsEndpoint extends BaseEndpoint {
  async list(spaceId: string, graphId: string, pageSize = 10, offset = 0, search?: string, includeSegments = false): Promise<KGDocumentsListResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('GET', '/api/graphs/kgdocuments', {
      params: { space_id: spaceId, graph_id: graphId, page_size: pageSize, offset, search, include_segments: includeSegments },
    });
  }

  async get(spaceId: string, graphId: string, uri: string): Promise<KGDocumentResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, uri });
    return this.request('GET', '/api/graphs/kgdocuments', {
      params: { space_id: spaceId, graph_id: graphId, uri },
    });
  }

  /**
   * Upload a document file; the server converts it to Markdown and creates the
   * KGDocument. Handles HTML, DOCX and PDF as well as Markdown/plain text —
   * binary formats cannot be read in the browser, which is why this posts the
   * file rather than extracting text client-side.
   *
   * No Content-Type is set: the browser must add the multipart boundary itself.
   *
   * `documentType` sets the document's `kGDocumentType`: a type with an enabled
   * segmentation config is segmented on upload, and its `auto_vectorize`
   * decides whether it is embedded. `vectorize` overrides that per document —
   * false keeps the document and its segments out of every vector index, true
   * embeds them even if the type's default is off — and is stored on the
   * document, so later updates and re-segmentation keep it (server 0.0.48).
   */
  async upload(
    spaceId: string,
    graphId: string,
    file: File | Blob,
    options?: {
      filename?: string;
      headline?: string;
      sourceUrl?: string;
      storeOriginal?: boolean;
      documentType?: string;
      vectorize?: boolean;
    },
  ): Promise<KGDocumentUploadResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });

    const form = new FormData();
    const filename = options?.filename ?? (file instanceof File ? file.name : 'upload');
    form.append('file', file, filename);
    if (options?.headline) form.append('headline', options.headline);
    if (options?.sourceUrl) form.append('source_url', options.sourceUrl);
    if (options?.storeOriginal !== undefined) {
      form.append('store_original', String(options.storeOriginal));
    }
    if (options?.documentType) form.append('document_type', options.documentType);
    if (options?.vectorize !== undefined) {
      form.append('vectorize', String(options.vectorize));
    }

    return this.request('POST', '/api/graphs/kgdocuments/upload', {
      params: { space_id: spaceId, graph_id: graphId },
      body: form,
    });
  }

  /**
   * Create KGDocuments from a quad payload. A document whose `kGDocumentType`
   * has an enabled segmentation config is segmented automatically.
   *
   * `options.vectorize`: see `upload`. Omitted, each document follows its type.
   */
  async create(
    spaceId: string,
    graphId: string,
    data: unknown,
    options?: { vectorize?: boolean },
  ): Promise<KGDocumentCreateResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('POST', '/api/graphs/kgdocuments', {
      params: { space_id: spaceId, graph_id: graphId, vectorize: options?.vectorize },
      json: data,
    });
  }

  async update(spaceId: string, graphId: string, uri: string, data: unknown): Promise<KGDocumentUpdateResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, uri });
    return this.request('PUT', '/api/graphs/kgdocuments', {
      params: { space_id: spaceId, graph_id: graphId, uri },
      json: data,
    });
  }

  async delete(spaceId: string, graphId: string, uri: string): Promise<KGDocumentDeleteResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, uri });
    return this.request('DELETE', '/api/graphs/kgdocuments', {
      params: { space_id: spaceId, graph_id: graphId, uri },
    });
  }

  async getSegments(spaceId: string, graphId: string, documentUri: string): Promise<KGDocumentSegmentsResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId, document_uri: documentUri });
    return this.request('GET', '/api/graphs/kgdocuments/segments', {
      params: { space_id: spaceId, graph_id: graphId, document_uri: documentUri },
    });
  }

  async batchDelete(spaceId: string, graphId: string, uris: string[]): Promise<KGDocumentDeleteResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('DELETE', '/api/graphs/kgdocuments', {
      params: { space_id: spaceId, graph_id: graphId },
      json: { uris },
    });
  }

  /**
   * Queue segmentation of a document. `vectorize`, when given, is stored on the
   * document first (see `upload`); turning it off also removes vectors the
   * document already has.
   */
  async segment(spaceId: string, graphId: string, data: {
    document_uri: string;
    segment_method_uri?: string;
    max_segment_tokens?: number;
    config_id?: string;
    vectorize?: boolean;
  }): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId, graph_id: graphId });
    return this.request('POST', '/api/graphs/kgdocuments/segment', {
      params: { space_id: spaceId, graph_id: graphId },
      json: data,
    });
  }

  async getSegmentationStatus(spaceId: string, options?: {
    document_uri?: string;
    status?: string;
    limit?: number;
    offset?: number;
  }): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('GET', '/api/graphs/kgdocuments/segmentation-status', {
      params: { space_id: spaceId, ...options },
    });
  }

  async listSegmentationConfigs(spaceId: string): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('GET', '/api/graphs/kgdocuments/segmentation-configs', {
      params: { space_id: spaceId },
    });
  }

  async createSegmentationConfig(spaceId: string, data: unknown): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId });
    return this.request('POST', '/api/graphs/kgdocuments/segmentation-configs', {
      params: { space_id: spaceId },
      json: data,
    });
  }

  async updateSegmentationConfig(spaceId: string, configId: string, data: unknown): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId, config_id: configId });
    return this.request('PUT', '/api/graphs/kgdocuments/segmentation-configs', {
      params: { space_id: spaceId, config_id: configId },
      json: data,
    });
  }

  async deleteSegmentationConfig(spaceId: string, configId: string): Promise<VitalGraphResponse> {
    validateRequired({ space_id: spaceId, config_id: configId });
    return this.request('DELETE', '/api/graphs/kgdocuments/segmentation-configs', {
      params: { space_id: spaceId, config_id: configId },
    });
  }
}
