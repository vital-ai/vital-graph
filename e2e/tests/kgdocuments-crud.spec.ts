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

/**
 * Delete the FileNode + link edge created for an uploaded document.
 *
 * The upload endpoint stores the original bytes as a FileNode in the SAME
 * shared graph the Files specs list. Leaving them behind grows that list every
 * run and eventually pushes `files-crud`'s own fixture off page 1 — the exact
 * shared-fixture failure documented in issues/022. Clean up what we create.
 */
async function deleteUploadArtifacts(documentUri: string) {
  if (!documentUri) return;
  const { ctx, headers } = await getAuthHeaders();
  await ctx.delete('/api/files', {
    params: { space_id: SPACE_ID, graph_id: GRAPH_ID, uri: `${documentUri}:source` },
    headers,
  }).catch(() => {});
  // The edge is a plain graph object, removed with the document's other quads.
  await ctx.delete('/api/graphs/kgdocuments', {
    params: { space_id: SPACE_ID, graph_id: GRAPH_ID, uri: `${documentUri}:filenode_edge` },
    headers,
  }).catch(() => {});
  await ctx.dispose();
}

/**
 * Remove FileNodes orphaned by document uploads.
 *
 * Deleting the KGDocument does not remove the FileNode holding its original
 * bytes, and a document deleted through the UI is gone before any per-test
 * cleanup can look up its URI. Sweeping by URI shape catches every path —
 * `urn:kgdocument:…:source` is only ever minted by the upload endpoint.
 */
async function cleanupUploadFileNodes() {
  const { ctx, headers } = await getAuthHeaders();
  for (let offset = 0; offset < 1000; offset += 100) {
    const resp = await ctx.get('/api/files', {
      params: { space_id: SPACE_ID, graph_id: GRAPH_ID, page_size: 100, offset },
      headers,
    });
    if (!resp.ok()) break;
    const data = await resp.json();
    const results = data.results || [];
    if (results.length === 0) break;
    const uris = [...new Set(
      results.map((q: { s: string }) => String(q.s).replace(/^<|>$/g, '')),
    )] as string[];
    const mine = uris.filter((u) => u.startsWith('urn:kgdocument:') && u.endsWith(':source'));
    for (const u of mine) {
      await ctx.delete('/api/files', {
        params: { space_id: SPACE_ID, graph_id: GRAPH_ID, uri: u },
        headers,
      }).catch(() => {});
      await ctx.delete('/api/graphs/kgdocuments', {
        params: { space_id: SPACE_ID, graph_id: GRAPH_ID, uri: u.replace(/:source$/, ':filenode_edge') },
        headers,
      }).catch(() => {});
    }
    if (mine.length === 0 && uris.length < 100) break;
  }
  await ctx.dispose();
}

/** Cleanup any E2E test documents (not the seeded one). */
async function cleanupTestDocuments() {
  await cleanupUploadFileNodes();
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
        // Uploads also create a FileNode for the original and a link edge, both
        // in the shared graph the Files specs list. Remove them with the
        // document, or they accumulate and push files-crud's fixture off page 1.
        await ctx.delete('/api/files', {
          params: { space_id: SPACE_ID, graph_id: GRAPH_ID, uri: `${uri}:source` },
          headers,
        }).catch(() => {});
        await ctx.delete('/api/graphs/kgdocuments', {
          params: { space_id: SPACE_ID, graph_id: GRAPH_ID, uri: `${uri}:filenode_edge` },
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

    // Plain text with no headings → the modal must advertise the paragraph
    // split, matching what the segmenter would choose.
    await expect(page.getByTestId('upload-format-hint')).toContainText('Plain text');

    // This test covers creation only — leave segmentation to the block below,
    // which drives the trigger explicitly.
    await page.getByTestId('upload-segment-toggle').getByRole('switch').click();

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
    // The upload leaves a FileNode behind even when the document itself is
    // deleted through the UI in the last test of this block.
    await cleanupUploadFileNodes();
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

    // 41 headings → the modal must advertise the heading-based split.
    await expect(page.getByTestId('upload-format-hint')).toContainText('Markdown detected');

    // Segmentation must NOT be queued here: the next test asserts
    // "No segmentation jobs found" and then drives the trigger itself.
    await page.getByTestId('upload-segment-toggle').getByRole('switch').click();

    // Create
    await page.locator('button', { hasText: 'Create Document' }).click();
    await expect(page.locator('[data-testid="document-card"]', { hasText: MARKDOWN_DOC_HEADLINE })).toBeVisible({ timeout: 10_000 });
  });

  // ─── Segmentation lifecycle test (manual trigger, no auto-seg) ────────────
  test('trigger segmentation and verify status transitions', async ({ page }) => {
    // Budget from a measured worst case, not a guess. On a FRESH database
    // (empty tables, first index build, nothing cached) vectorising this
    // article's 80 segments took 39.4s wall-clock — from
    // "Job N → vectorizing (80 segments)" to "vectorization completed for 81
    // subjects" in the worker log. Stage 3 below therefore needs well over 30s,
    // and the whole test needs room for that plus the earlier stages.
    test.setTimeout(180_000);

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
    // Vectorization finishes → badge shows "✅ Ready".
    //
    // 90s, not 30s: 39.4s measured on a fresh database (see the note at the top
    // of this test), and this ran right at the edge — it failed on fresh-DB runs
    // and passed on warm ones, which reads like flake but is simply the work
    // taking longer than the budget allowed. Raise the budget rather than
    // re-running until it is green; if this ever times out again, the
    // vectorization itself has genuinely regressed and is worth investigating.
    await expect(page.getByText('✅ Ready', { exact: true })).toBeVisible({ timeout: 90_000 });

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
    // Contract: create is HTTP 200 (already-exists is 200 + status=already_exists in body, not 409)
    expect(createResp.status()).toBe(200);

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
      expect(mappingResp.status()).toBe(200);
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

// ─── Upload-time segmentation (issue 018 item 3) ──────────────────────────
//
// Its own block with its own document: the block above asserts that NO
// segmentation job exists before it triggers one, so it must not share a
// document with a test that queues segmentation at upload time.
test.describe('KG Documents — segment on upload', () => {
  test.describe.configure({ mode: 'serial' });

  const AUTO_SEG_HEADLINE = `E2E AutoSeg Doc ${Date.now()}`;

  test.afterAll(async () => { await cleanupTestDocuments(); });

  test('upload with "Segment & index" on queues a segmentation job', async ({ page }) => {
    test.setTimeout(90_000);

    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/kgdocuments`);
    await expect(page.locator('[data-testid="kgdocuments-page"]')).toBeVisible({ timeout: 10_000 });

    await page.locator('button', { hasText: 'Upload Document' }).click();
    await expect(page.getByText('Upload Document').last()).toBeVisible({ timeout: 5_000 });
    await page.fill('#upload-headline', AUTO_SEG_HEADLINE);

    // Small markdown doc — enough headings to take the heading split, small
    // enough that segmentation finishes quickly.
    const content = '# Alpha\n\nFirst section body.\n\n## Beta\n\nSecond section body.\n';
    await page.locator('#upload-file').setInputFiles({
      name: 'e2e_autoseg.md',
      mimeType: 'text/markdown',
      buffer: Buffer.from(content),
    });
    await expect(page.getByTestId('upload-format-hint')).toContainText('Markdown detected');

    // Toggle is ON by default — assert that rather than clicking it, since the
    // default is the behaviour issue 018 asks for.
    await expect(page.getByTestId('upload-segment-toggle').getByRole('switch')).toBeChecked();

    // Pin the segment call: without this the test would pass if the UI silently
    // stopped queueing segmentation, which is the whole point of the feature.
    const segmentPost = page.waitForResponse(
      (r) => r.url().includes('/api/graphs/kgdocuments/segment') && r.request().method() === 'POST',
      { timeout: 30_000 },
    );
    await page.locator('button', { hasText: 'Create Document' }).click();
    const segmentResp = await segmentPost;
    expect(segmentResp.status(), 'segment POST should succeed').toBe(200);

    // The user is told what happened.
    await expect(page.getByTestId('upload-notice')).toContainText('Segmentation queued', { timeout: 10_000 });

    // And the job is real, not just a UI claim.
    const { ctx, headers } = await getAuthHeaders();
    await expect(async () => {
      const resp = await ctx.get('/api/graphs/kgdocuments/segmentation-status', {
        params: { space_id: SPACE_ID, limit: 100 },
        headers,
      });
      const body = await resp.json();
      const jobs = body.jobs || body.results || [];
      const mine = jobs.filter((j: { document_uri?: string }) =>
        String(j.document_uri || '').includes('e2e_autoseg'));
      expect(mine.length, 'a segmentation job should exist for the uploaded doc').toBeGreaterThan(0);
    }).toPass({ timeout: 30_000 });
    await ctx.dispose();
  });

  test('upload with "Segment & index" off queues nothing', async ({ page }) => {
    const headline = `${AUTO_SEG_HEADLINE} Manual`;

    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/kgdocuments`);
    await expect(page.locator('[data-testid="kgdocuments-page"]')).toBeVisible({ timeout: 10_000 });

    await page.locator('button', { hasText: 'Upload Document' }).click();
    await expect(page.getByText('Upload Document').last()).toBeVisible({ timeout: 5_000 });
    await page.fill('#upload-headline', headline);
    await page.locator('#upload-file').setInputFiles({
      name: 'e2e_manual.md',
      mimeType: 'text/markdown',
      buffer: Buffer.from('# One\n\nBody.\n\n## Two\n\nBody.\n'),
    });

    await page.getByTestId('upload-segment-toggle').getByRole('switch').click();
    await expect(page.getByTestId('upload-segment-toggle').getByRole('switch')).not.toBeChecked();

    let segmentCalled = false;
    page.on('request', (req) => {
      if (req.url().includes('/api/graphs/kgdocuments/segment') && req.method() === 'POST') segmentCalled = true;
    });

    await page.locator('button', { hasText: 'Create Document' }).click();
    await expect(page.locator('[data-testid="document-card"]', { hasText: headline })).toBeVisible({ timeout: 10_000 });
    expect(segmentCalled, 'no segment request should be sent when the toggle is off').toBe(false);
  });
});

// ─── Server-side conversion to Markdown (issue 018 item 4) ────────────────
//
// HTML/DOCX/PDF are converted on upload so the segmenter can use
// markdown_heading_split. Its own block and its own documents: uploading here
// queues segmentation, which the manual-trigger block above must not see.
test.describe('KG Documents — upload conversion', () => {
  test.describe.configure({ mode: 'serial' });

  const STAMP = Date.now();
  const HTML_HEADLINE = `E2E Convert HTML ${STAMP}`;
  const DOCX_HEADLINE = `E2E Convert DOCX ${STAMP}`;

  const HTML_SOURCE =
    '<html><body><h1>Coffee</h1><p>A <strong>brewed</strong> drink.</p>'
    + '<h2>History</h2><p>Origins in Ethiopia.</p></body></html>';

  /** Minimal real .docx: a zip whose document.xml uses Word heading styles. */
  function docxBytes(): Buffer {
    const documentXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Quarterly Report</w:t></w:r></w:p>
    <w:p><w:r><w:t>Revenue rose.</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>Outlook</w:t></w:r></w:p>
  </w:body>
</w:document>`;
    const contentTypes = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>`;
    const rels = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>`;
    // Store entries uncompressed so no zip library is needed.
    const files: { name: string; data: Buffer }[] = [
      { name: '[Content_Types].xml', data: Buffer.from(contentTypes) },
      { name: '_rels/.rels', data: Buffer.from(rels) },
      { name: 'word/document.xml', data: Buffer.from(documentXml) },
    ];
    const crcTable: number[] = [];
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      crcTable[n] = c >>> 0;
    }
    const crc32 = (buf: Buffer) => {
      let c = 0xffffffff;
      for (const b of buf) c = crcTable[(c ^ b) & 0xff] ^ (c >>> 8);
      return (c ^ 0xffffffff) >>> 0;
    };
    const locals: Buffer[] = [];
    const centrals: Buffer[] = [];
    let offset = 0;
    for (const f of files) {
      const nameBuf = Buffer.from(f.name);
      const crc = crc32(f.data);
      const local = Buffer.alloc(30);
      local.writeUInt32LE(0x04034b50, 0);
      local.writeUInt16LE(20, 4);
      local.writeUInt16LE(0, 8); // stored
      local.writeUInt32LE(crc, 14);
      local.writeUInt32LE(f.data.length, 18);
      local.writeUInt32LE(f.data.length, 22);
      local.writeUInt16LE(nameBuf.length, 26);
      locals.push(local, nameBuf, f.data);

      const central = Buffer.alloc(46);
      central.writeUInt32LE(0x02014b50, 0);
      central.writeUInt16LE(20, 4);
      central.writeUInt16LE(20, 6);
      central.writeUInt16LE(0, 10);
      central.writeUInt32LE(crc, 16);
      central.writeUInt32LE(f.data.length, 20);
      central.writeUInt32LE(f.data.length, 24);
      central.writeUInt16LE(nameBuf.length, 28);
      central.writeUInt32LE(offset, 42);
      centrals.push(central, nameBuf);

      offset += local.length + nameBuf.length + f.data.length;
    }
    const centralBuf = Buffer.concat(centrals);
    const end = Buffer.alloc(22);
    end.writeUInt32LE(0x06054b50, 0);
    end.writeUInt16LE(files.length, 8);
    end.writeUInt16LE(files.length, 10);
    end.writeUInt32LE(centralBuf.length, 12);
    end.writeUInt32LE(offset, 16);
    return Buffer.concat([Buffer.concat(locals), centralBuf, end]);
  }

  /** Read one predicate's value for a document, via API. */
  async function propertyOf(uri: string, predicateSuffix: string): Promise<string> {
    const { ctx, headers } = await getAuthHeaders();
    const resp = await ctx.get('/api/graphs/kgdocuments', {
      params: { space_id: SPACE_ID, graph_id: GRAPH_ID, uri },
      headers,
    });
    const data = await resp.json();
    await ctx.dispose();
    const match = (data.results || []).find((q: { p: string }) => String(q.p).includes(predicateSuffix));
    return match ? String(match.o) : '';
  }

  const uploadedDocUris: string[] = [];

  test.afterAll(async () => {
    for (const uri of uploadedDocUris) await deleteUploadArtifacts(uri);
    await cleanupTestDocuments();
  });

  test('HTML is converted to Markdown and the original is preserved', async ({ page }) => {
    test.setTimeout(60_000);

    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/kgdocuments`);
    await expect(page.locator('[data-testid="kgdocuments-page"]')).toBeVisible({ timeout: 10_000 });

    await page.locator('button', { hasText: 'Upload Document' }).click();
    await expect(page.getByText('Upload Document').last()).toBeVisible({ timeout: 5_000 });
    await page.fill('#upload-headline', HTML_HEADLINE);
    await page.locator('#upload-file').setInputFiles({
      name: 'coffee.html',
      mimeType: 'text/html',
      buffer: Buffer.from(HTML_SOURCE),
    });

    // Raw HTML has no '#' headings, so the pre-upload hint must not claim a
    // heading split — the headings only exist after conversion.
    await expect(page.getByTestId('upload-format-hint')).not.toContainText('Markdown detected');

    const uploadPost = page.waitForResponse(
      (r) => r.url().includes('/api/graphs/kgdocuments/upload') && r.request().method() === 'POST',
      { timeout: 30_000 },
    );
    await page.locator('button', { hasText: 'Create Document' }).click();
    const body = await (await uploadPost).json();

    uploadedDocUris.push(body.document_uri);
    expect(body.success, 'upload should succeed').toBe(true);
    expect(body.converted, 'HTML must be converted').toBe(true);
    expect(body.source_format).toBe('.html');
    expect(body.heading_count, 'h1 + h2 become two Markdown headings').toBeGreaterThanOrEqual(2);
    expect(body.file_node_uri, 'the original should be retained').toBeTruthy();

    const markdown = await propertyOf(body.document_uri, 'hasKGDocumentExtractedContent');
    expect(markdown).toContain('# Coffee');
    expect(markdown).toContain('## History');
    expect(markdown).toContain('**brewed**');

    // The original HTML must survive byte-for-byte. It previously lost its
    // outer angle brackets because the quad literal was not N-Quads encoded.
    const html = await propertyOf(body.document_uri, 'hasKGDocumentHTMLContent');
    expect(html.replace(/^"|"$/g, '')).toBe(HTML_SOURCE);

    await expect(page.getByTestId('upload-notice')).toContainText('converted', { timeout: 10_000 });
  });

  test('DOCX heading styles survive as Markdown headings', async ({ page }) => {
    test.setTimeout(60_000);

    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/kgdocuments`);
    await expect(page.locator('[data-testid="kgdocuments-page"]')).toBeVisible({ timeout: 10_000 });

    await page.locator('button', { hasText: 'Upload Document' }).click();
    await expect(page.getByText('Upload Document').last()).toBeVisible({ timeout: 5_000 });
    await page.fill('#upload-headline', DOCX_HEADLINE);
    await page.locator('#upload-file').setInputFiles({
      name: 'report.docx',
      mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      buffer: docxBytes(),
    });

    // Binary source — the browser cannot inspect it, so the hint states intent.
    await expect(page.getByTestId('upload-format-hint')).toContainText('converted to Markdown');

    const uploadPost = page.waitForResponse(
      (r) => r.url().includes('/api/graphs/kgdocuments/upload') && r.request().method() === 'POST',
      { timeout: 30_000 },
    );
    await page.locator('button', { hasText: 'Create Document' }).click();
    const body = await (await uploadPost).json();

    uploadedDocUris.push(body.document_uri);
    expect(body.success, 'upload should succeed').toBe(true);
    expect(body.source_format).toBe('.docx');
    expect(body.converted).toBe(true);

    const markdown = await propertyOf(body.document_uri, 'hasKGDocumentExtractedContent');
    // Word heading STYLES, not bold text — this is why mammoth was chosen.
    expect(markdown).toContain('# Quarterly Report');
    expect(markdown).toContain('## Outlook');
    expect(markdown).toContain('Revenue rose.');
  });

  test('an unsupported file type is refused with a readable message', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/kgdocuments`);
    await expect(page.locator('[data-testid="kgdocuments-page"]')).toBeVisible({ timeout: 10_000 });

    await page.locator('button', { hasText: 'Upload Document' }).click();
    await expect(page.getByText('Upload Document').last()).toBeVisible({ timeout: 5_000 });
    await page.fill('#upload-headline', `E2E Unsupported ${STAMP}`);
    await page.locator('#upload-file').setInputFiles({
      name: 'sheet.xlsx',
      mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      buffer: Buffer.from('not really a spreadsheet'),
    });

    const uploadPost = page.waitForResponse(
      (r) => r.url().includes('/api/graphs/kgdocuments/upload') && r.request().method() === 'POST',
      { timeout: 30_000 },
    );
    await page.locator('button', { hasText: 'Create Document' }).click();
    const resp = await uploadPost;

    // Domain outcome: HTTP 200 with success:false, not a 4xx/5xx.
    expect(resp.status()).toBe(200);
    const body = await resp.json();
    expect(body.success).toBe(false);
    expect(body.message).toContain('Unsupported file type');

    // And the user is told, rather than the modal silently closing.
    await expect(page.getByText(/Unsupported file type/)).toBeVisible({ timeout: 10_000 });
  });
});

}); // end outer KG Documents describe
