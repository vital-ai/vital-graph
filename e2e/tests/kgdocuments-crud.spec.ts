import { test, expect, request } from '@playwright/test';
import { ADMIN_USER, ADMIN_PASS, SPACE_ID, GRAPH_ID, SEEDED_DOCUMENT } from '../seed-constants';

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

// Markdown content with headings for heading-based segmentation.
// Must stay under ~2.7KB to avoid the B-tree term index limit.
// Uses Wikipedia-style content with multiple headings.
const MARKDOWN_DOC_HEADLINE = `E2E Markdown Doc ${Date.now()}`;
const MARKDOWN_CONTENT = `# Coffee

**Coffee** is a beverage brewed from roasted ground coffee beans. Darkly colored and bitter, coffee has a stimulating effect on humans due to its caffeine content. Coffee production begins when the seeds from coffee cherries are separated to produce unroasted green coffee beans. The beans are roasted and then ground into fine particles.

## Etymology

The word coffee entered the English language in 1582 via the Dutch koffie, borrowed from the Ottoman Turkish kahve, borrowed from the Arabic qahwah. Medieval Arabic lexicons traditionally held that the etymology meant wine, given its distinctly dark color. The word most likely meant the dark one, referring to the brew or the bean.

## History

The earliest possible references to the coffee bean appear in al-Razi's 10th-century al-Hawi. By the late 15th century, coffee drinking was well established among Sufi communities in Yemen. Coffee was used by Sufi circles to stay awake for their religious rituals. By the 16th century, coffee had reached the rest of the Middle East and North Africa.

## Cultivation

The two most commonly grown coffee bean types are C. arabica and C. robusta. Coffee plants are cultivated in over 70 countries, primarily in the equatorial regions of the Americas, Southeast Asia, the Indian subcontinent, and Africa. Brazil was the leading grower in 2023, producing 31% of the world total.
`;

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

    // Wait for documents to load
    await expect(page.locator('[data-testid="document-card"]').first()).toBeVisible({ timeout: 10_000 });

    // Seeded document should be visible
    await expect(page.getByText(SEEDED_DOCUMENT.title).first()).toBeVisible({ timeout: 5_000 });
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

  test('create ONNX vector index and search mapping', async () => {
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

    await ctx.dispose();
  });

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

  test('trigger segmentation and poll until completed', async ({ page }) => {
    test.setTimeout(90_000); // segmentation + vectorization can take up to ~60s

    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/kgdocuments`);
    await expect(page.locator('[data-testid="document-card"]', { hasText: MARKDOWN_DOC_HEADLINE })).toBeVisible({ timeout: 10_000 });

    // Navigate to detail
    await page.locator('[data-testid="document-card"]', { hasText: MARKDOWN_DOC_HEADLINE }).click();
    await expect(page.locator('[data-testid="kgdocument-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // Click Segment button
    await page.locator('button', { hasText: 'Segment' }).click();

    // Poll: wait for the "Completed" badge to appear (segmentation + vectorization)
    await expect(page.getByText('Completed')).toBeVisible({ timeout: 60_000 });

    // Segments should auto-load after completion. Wait for segment count text.
    // The heading-based split of 4 sections (# + 3x##) should produce multiple segments.
    // Look for the segment count indicator "N segment(s)" showing at least 2.
    await expect(page.getByText(/[2-9] segments|[1-9]\d+ segments/)).toBeVisible({ timeout: 15_000 });

    // Verify actual segment entries are rendered in the Segments section
    // (validates the SPARQL edge-traversal query that populates the list)
    await expect(page.locator('text=Markdown Section').first()).toBeVisible({ timeout: 10_000 });
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

    // Wait for results — should find at least 1 row
    await expect(page.getByText(/[1-9]\d* rows/)).toBeVisible({ timeout: 15_000 });

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
