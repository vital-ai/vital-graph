import { test, expect, request } from '@playwright/test';
import { ADMIN_USER, ADMIN_PASS, SPACE_ID, GRAPH_ID, SEEDED_DOCUMENT } from '../seed-constants';
import * as path from 'path';
import * as fs from 'fs';

/**
 * KG Documents CRUD — UI lifecycle tests.
 *
 * Tests:
 * 1. Seeded document appears in the list page.
 * 2. Create a document via the Upload modal.
 * 3. New document appears in the list.
 * 4. Navigate to detail and delete it.
 */

const ENCODED_GRAPH = encodeURIComponent(GRAPH_ID);
const TEST_DOC_HEADLINE = `E2E Upload Doc ${Date.now()}`;
const BASE_URL = process.env.VG_TEST_URL || 'http://localhost:8002';

// Use the actual Wikipedia coffee article (~59KB, many headings) so segmentation
// takes long enough to observe all status transitions in the UI.
const MARKDOWN_DOC_HEADLINE = `E2E Markdown Doc ${Date.now()}`;
const WIKI_FILE = path.resolve(__dirname, '../../test_files/wikipedia/coffee.md');
const MARKDOWN_CONTENT = fs.readFileSync(WIKI_FILE, 'utf-8');

async function getAuthHeaders() {
  const ctx = await request.newContext({ baseURL: BASE_URL });
  const loginResp = await ctx.post('/api/login', {
    form: { username: ADMIN_USER, password: ADMIN_PASS },
  });
  const { access_token } = await loginResp.json();
  const headers = { Authorization: `Bearer ${access_token}` };
  return { ctx, headers };
}

/** Create a KGDocument via API for testing. */
async function createTestDocument(headline: string): Promise<string> {
  const { ctx, headers } = await getAuthHeaders();
  const docUri = `urn:e2e:document:test_${Date.now()}`;
  const quads = [
    { s: docUri, p: 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', o: 'http://vital.ai/ontology/haley-ai-kg#KGDocument', o_type: 'uri' },
    { s: docUri, p: 'http://vital.ai/ontology/vital-core#hasName', o: headline, o_type: 'literal' },
    { s: docUri, p: 'http://vital.ai/ontology/haley-ai-kg#hasKGDocumentHeadline', o: headline, o_type: 'literal' },
    { s: docUri, p: 'http://vital.ai/ontology/haley-ai-kg#hasKGDocumentContent', o: `Content of ${headline}`, o_type: 'literal' },
  ];
  const resp = await ctx.post('/api/graphs/kgdocuments', {
    params: { space_id: SPACE_ID, graph_id: GRAPH_ID },
    headers,
    data: { quads },
  });
  expect(resp.ok()).toBe(true);
  await ctx.dispose();
  return docUri;
}

/** Delete a KGDocument by URI via API (idempotent). */
async function deleteDocument(uri: string) {
  const { ctx, headers } = await getAuthHeaders();
  await ctx.delete('/api/graphs/kgdocuments', {
    params: { space_id: SPACE_ID, graph_id: GRAPH_ID, uri },
    headers,
  }).catch(() => {});
  await ctx.dispose();
}

/** Cleanup any E2E test documents (not the seeded one). */
async function cleanupTestDocuments() {
  const { ctx, headers } = await getAuthHeaders();
  const resp = await ctx.get('/api/graphs/kgdocuments', {
    params: { space_id: SPACE_ID, graph_id: GRAPH_ID, search: 'E2E', page_size: 100 },
    headers,
  });
  if (resp.ok()) {
    const data = await resp.json();
    const docs = data.results || [];
    for (const doc of docs) {
      const uri = doc.uri || doc.s?.replace(/^<|>$/g, '');
      if (uri && uri !== SEEDED_DOCUMENT.uri) {
        await ctx.delete('/api/graphs/kgdocuments', {
          params: { space_id: SPACE_ID, graph_id: GRAPH_ID, uri },
          headers,
        }).catch(() => {});
      }
    }
  }
  await ctx.dispose();
}

test.describe('KG Documents', () => {
  test.describe.configure({ mode: 'serial' });

test.describe('KG Documents CRUD — UI lifecycle', () => {
  test.describe.configure({ mode: 'serial' });

  let uploadedDocUri = '';

  test.beforeAll(async () => { await cleanupTestDocuments(); });
  test.afterAll(async () => {
    if (uploadedDocUri) await deleteDocument(uploadedDocUri);
    await cleanupTestDocuments();
  });

  test('seeded document appears in the list', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/kgdocuments`);
    await expect(page.locator('[data-testid="kgdocuments-page"]')).toBeVisible({ timeout: 10_000 });

    // Search for the seeded document to bypass pagination with accumulated docs
    const searchInput = page.locator('input[placeholder*="Search documents"]');
    if (await searchInput.isVisible({ timeout: 3_000 }).catch(() => false)) {
      await searchInput.fill(SEEDED_DOCUMENT.title);
      await page.waitForTimeout(500);
    }

    // Seeded document should be visible
    await expect(page.getByText(SEEDED_DOCUMENT.title).first()).toBeVisible({ timeout: 15_000 });
  });

  test('create a document via the Upload modal', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/kgdocuments`);
    await expect(page.locator('[data-testid="kgdocuments-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('[data-testid="document-card"]').first()).toBeVisible({ timeout: 10_000 });

    // Click Upload Document button
    await page.locator('button', { hasText: 'Upload Document' }).click();

    // Modal should appear
    await expect(page.getByText('Upload Document').last()).toBeVisible({ timeout: 5_000 });

    // Fill in the headline
    await page.fill('#upload-headline', TEST_DOC_HEADLINE);

    // Create a test file and attach it
    const fileContent = `This is test document content for ${TEST_DOC_HEADLINE}.\nLine two.`;
    const buffer = Buffer.from(fileContent);
    await page.locator('#upload-file').setInputFiles({
      name: 'e2e_test_doc.txt',
      mimeType: 'text/plain',
      buffer,
    });

    // Click Create Document button
    await page.locator('button', { hasText: 'Create Document' }).click();

    // Modal should close and document should appear in list
    await expect(page.locator('[data-testid="document-card"]', { hasText: TEST_DOC_HEADLINE })).toBeVisible({ timeout: 10_000 });
  });

  test('new document detail page loads', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/kgdocuments`);
    await expect(page.locator('[data-testid="kgdocuments-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('[data-testid="document-card"]', { hasText: TEST_DOC_HEADLINE })).toBeVisible({ timeout: 10_000 });

    // Click the document card to navigate to detail
    await page.locator('[data-testid="document-card"]', { hasText: TEST_DOC_HEADLINE }).click();
    await expect(page.locator('[data-testid="kgdocument-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // Should show the headline somewhere on the detail page
    await expect(page.locator('[data-testid="kgdocument-detail-page"]').getByText(TEST_DOC_HEADLINE).first()).toBeVisible();
  });

  test('delete document via the detail page', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/kgdocuments`);
    await expect(page.locator('[data-testid="kgdocuments-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('[data-testid="document-card"]', { hasText: TEST_DOC_HEADLINE })).toBeVisible({ timeout: 10_000 });

    // Navigate to detail
    await page.locator('[data-testid="document-card"]', { hasText: TEST_DOC_HEADLINE }).click();
    await expect(page.locator('[data-testid="kgdocument-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // Click Delete button
    await page.locator('button', { hasText: /Delete KG Document/ }).click();

    // Confirm in modal
    await page.locator('button', { hasText: 'Delete' }).last().click();

    // Should navigate back to list
    await expect(page.locator('[data-testid="kgdocuments-page"]')).toBeVisible({ timeout: 10_000 });

    // Document should no longer be in the list
    await expect(page.locator('[data-testid="document-card"]', { hasText: TEST_DOC_HEADLINE })).not.toBeVisible({ timeout: 5_000 });
  });
});

// ---------------------------------------------------------------------------
// Segmentation + Search Tests (longer timeouts)
// ---------------------------------------------------------------------------

const SEG_VECTOR_INDEX = 'e2e_segment_vec';

test.describe('KG Documents — Segmentation & Search', () => {
  test.describe.configure({ mode: 'serial' });

  let markdownDocUri = '';

  test.afterAll(async () => {
    if (markdownDocUri) await deleteDocument(markdownDocUri);
  });

  // ─── Upload FIRST (before creating search mappings to prevent auto-seg) ───
  test('upload markdown document for segmentation', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/kgdocuments`);
    await expect(page.locator('[data-testid="kgdocuments-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('[data-testid="document-card"]').first()).toBeVisible({ timeout: 10_000 });

    // Click Upload Document button
    await page.locator('button', { hasText: 'Upload Document' }).click();
    await expect(page.getByText('Upload Document').last()).toBeVisible({ timeout: 5_000 });

    // Fill headline
    await page.fill('#upload-headline', MARKDOWN_DOC_HEADLINE);

    // Attach markdown file
    const buffer = Buffer.from(MARKDOWN_CONTENT);
    await page.locator('#upload-file').setInputFiles({
      name: 'coffee_wikipedia.md',
      mimeType: 'text/markdown',
      buffer,
    });

    // Create
    await page.locator('button', { hasText: 'Create Document' }).click();
    await expect(page.locator('[data-testid="document-card"]', { hasText: MARKDOWN_DOC_HEADLINE })).toBeVisible({ timeout: 10_000 });
  });

  // ─── Segmentation lifecycle test (manual trigger, no auto-seg) ────────────
  test('trigger segmentation and verify status transitions', async ({ page }) => {
    test.setTimeout(90_000); // segmentation + vectorization can take up to ~60s

    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/kgdocuments`);
    await expect(page.locator('[data-testid="document-card"]', { hasText: MARKDOWN_DOC_HEADLINE })).toBeVisible({ timeout: 10_000 });

    // Navigate to detail
    await page.locator('[data-testid="document-card"]', { hasText: MARKDOWN_DOC_HEADLINE }).click();
    await expect(page.locator('[data-testid="kgdocument-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // No segmentation status should exist yet
    await expect(page.getByText('No segmentation jobs found')).toBeVisible({ timeout: 5_000 });

    // Click Segment button to start the lifecycle
    await page.locator('button', { hasText: 'Segment' }).click();

    // ─── Stage 1: pending or in_progress ───────────────────────────────
    // The job should appear as pending/segmenting. With small docs, this
    // stage may be very brief — also accept vectorizing if it transitions
    // before the first UI poll catches it.
    // Use exact badge text (with emoji) to avoid matching document content.
    await expect(
      page.getByText('⏳ Pending', { exact: true })
        .or(page.getByText('🔄 Segmenting…', { exact: true }))
        .or(page.getByText('✅🔄 Segmented — vectorizing…', { exact: true }))
    ).toBeVisible({ timeout: 15_000 });

    // ─── Stage 2: vectorizing ──────────────────────────────────────────
    // After segmentation finishes, segments are stored and the job
    // transitions to "vectorizing". Badge: "✅🔄 Segmented — vectorizing…"
    // This confirms segments are available before vectorization completes.
    await expect(
      page.getByText('✅🔄 Segmented — vectorizing…', { exact: true })
        .or(page.getByText('✅ Ready', { exact: true }))
    ).toBeVisible({ timeout: 60_000 });

    // Segments should be loaded in the UI (auto-refresh on vectorizing/completed).
    // The Wikipedia coffee article has 41 headings → many segments.
    await expect(page.getByText(/[1-9]\d+ segments/)).toBeVisible({ timeout: 15_000 });

    // Verify actual segment entries are rendered (type label + heading from article)
    await expect(page.locator('text=Markdown Section').first()).toBeVisible({ timeout: 10_000 });

    // ─── Stage 3: completed ────────────────────────────────────────────
    // Vectorization finishes → badge shows "✅ Ready"
    await expect(page.getByText('✅ Ready', { exact: true })).toBeVisible({ timeout: 30_000 });

    // "Segmented — vectorizing…" should no longer be visible (transitioned away)
    await expect(page.getByText('✅🔄 Segmented — vectorizing…', { exact: true })).not.toBeVisible({ timeout: 5_000 });
  });

  test('list page shows "Ready" badge after segmentation completes', async ({ page }) => {
    test.setTimeout(90_000); // vectorization may still be finishing from previous test
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/kgdocuments`);
    await expect(page.locator('[data-testid="kgdocuments-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('[data-testid="document-card"]', { hasText: MARKDOWN_DOC_HEADLINE })).toBeVisible({ timeout: 10_000 });

    // After the lifecycle completes (previous test), the list page should
    // show "✅ Ready" on the document card (status == completed).
    // Allow up to 60s for vectorization to finish if still in progress.
    const card = page.locator('[data-testid="document-card"]', { hasText: MARKDOWN_DOC_HEADLINE });
    await expect(card.getByText('✅ Ready', { exact: true })).toBeVisible({ timeout: 60_000 });
  });

  // ─── NOW create vector index + mapping (segments already exist) ───────────
  test('create ONNX vector index and search mapping', async () => {
    // Reindex embeds ~80 existing segments with the ONNX model (CPU-bound) —
    // give the background job room to finish before the search test runs.
    test.setTimeout(180_000);

    const { ctx, headers } = await getAuthHeaders();
    const jsonHeaders = { ...headers, 'Content-Type': 'application/json' };

    // Delete the OpenAI-backed document_segments index (auto_sync fails without API key).
    // This silently 404s if it doesn't exist — that's fine.
    await ctx.delete(`${BASE_URL}/api/vector-indexes?space_id=${SPACE_ID}&index_name=document_segments`, {
      headers,
    });

    // Create a vector index using the built-in ONNX model (vitalsigns provider, 384 dims)
    const createResp = await ctx.post(`${BASE_URL}/api/vector-indexes?space_id=${SPACE_ID}`, {
      headers: jsonHeaders,
      data: {
        index_name: SEG_VECTOR_INDEX,
        dimensions: 384,
        distance_metric: 'cosine',
        provider: 'vitalsigns',
        description: 'E2E test — ONNX segment vectors',
      },
    });
    // Index may already exist from a previous test run — 409 is acceptable
    expect([201, 409]).toContain(createResp.status());

    // Create a search mapping for kgdocument_segment → our ONNX index
    // First check if one already exists (from a previous test run)
    const listResp = await ctx.get(`${BASE_URL}/api/search-mappings?space_id=${SPACE_ID}&mapping_type=kgdocument_segment`, {
      headers,
    });
    const existing = await listResp.json();
    let mappingId: number | null = null;

    if (existing.mappings?.length > 0) {
      mappingId = existing.mappings[0].mapping_id;
    } else {
      const mappingResp = await ctx.post(`${BASE_URL}/api/search-mappings?space_id=${SPACE_ID}`, {
        headers: jsonHeaders,
        data: {
          index_name: SEG_VECTOR_INDEX,
          mapping_type: 'kgdocument_segment',
          enabled: true,
          source_type: 'default',
        },
      });
      expect(mappingResp.status()).toBe(201);
      const mapping = await mappingResp.json();
      mappingId = mapping.mapping_id;

      // Add the vector index to the mapping
      await ctx.post(`${BASE_URL}/api/search-mappings/${mappingId}/indexes?space_id=${SPACE_ID}`, {
        headers: jsonHeaders,
        data: {
          index_type: 'vector',
          index_name: SEG_VECTOR_INDEX,
        },
      });
    }

    // The segments were created BEFORE this index/mapping existed, so auto_sync
    // never embedded them — reindex now to backfill embeddings from the graph.
    // (Without this, embedding_count stays 0 and semantic search returns nothing.)
    const reindexResp = await ctx.post(
      `${BASE_URL}/api/vector-indexes/reindex?space_id=${SPACE_ID}&index_name=${SEG_VECTOR_INDEX}`,
      {
        headers: jsonHeaders,
        data: { graph_uri: GRAPH_ID, mapping_type: 'kgdocument_segment', batch_size: 50 },
      },
    );
    expect(reindexResp.ok()).toBeTruthy();
    const reindexBody = await reindexResp.json();
    const jobId: string | undefined = reindexBody.job_id;

    // Reindex runs as a background job — poll status until it completes.
    let embeddingsStored = 0;
    const deadline = Date.now() + 150_000;
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 2_000));
      const statusResp = await ctx.get(
        `${BASE_URL}/api/vector-indexes/reindex/status?space_id=${SPACE_ID}` +
          (jobId ? `&job_id=${jobId}` : `&index_name=${SEG_VECTOR_INDEX}`),
        { headers },
      );
      const statusBody = await statusResp.json();
      const job = statusBody.jobs?.[0];
      if (!job) continue;
      if (job.status === 'completed') {
        embeddingsStored = job.embeddings_stored;
        break;
      }
      if (job.status === 'failed') {
        throw new Error(`Reindex failed: ${JSON.stringify(job.errors ?? job)}`);
      }
    }
    expect(embeddingsStored, 'reindex should embed at least one segment').toBeGreaterThan(0);

    await ctx.dispose();
  });

  test('semantic search returns the segmented document', async ({ page }) => {
    test.setTimeout(30_000);

    await page.goto('/semantic-search');
    await expect(page.locator('[data-testid="semantic-search-page"]')).toBeVisible({ timeout: 10_000 });

    // Select the test space
    await page.locator('#space').selectOption(SPACE_ID);

    // Wait for indexes to load, then select the ONNX vector index we created
    await page.locator('#indexName').waitFor({ state: 'visible', timeout: 10_000 });
    await page.locator('#indexName').selectOption(SEG_VECTOR_INDEX);

    // Search for content that exists in the document
    await page.fill('#searchText', 'coffee beans roasted beverage caffeine');

    // Execute search
    await page.getByRole('button', { name: 'Search' }).click();

    // Wait for results — should find at least 1 row (vector search can be slow in CI)
    await expect(page.getByText(/[1-9]\d* rows/)).toBeVisible({ timeout: 30_000 });

    // Verify at least one result row is visible in the table
    const firstRow = page.locator('table tbody tr').first();
    await expect(firstRow).toBeVisible();

    // Confirm the result is from our segmented document (URI contains "kgdocument")
    await expect(firstRow).toContainText(/kgdocument/i);
  });

  test('delete segmented document cleans up', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/kgdocuments`);
    await expect(page.locator('[data-testid="document-card"]', { hasText: MARKDOWN_DOC_HEADLINE })).toBeVisible({ timeout: 10_000 });

    // Navigate to detail
    await page.locator('[data-testid="document-card"]', { hasText: MARKDOWN_DOC_HEADLINE }).click();
    await expect(page.locator('[data-testid="kgdocument-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // Delete
    await page.locator('button', { hasText: /Delete KG Document/ }).click();
    await page.locator('button', { hasText: 'Delete' }).last().click();

    // Should return to list without the document
    await expect(page.locator('[data-testid="kgdocuments-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('[data-testid="document-card"]', { hasText: MARKDOWN_DOC_HEADLINE })).not.toBeVisible({ timeout: 5_000 });
    markdownDocUri = ''; // already deleted
  });
});

}); // end outer KG Documents describe
