import { test, expect, request } from '@playwright/test';
import * as crypto from 'crypto';
import { ADMIN_USER, ADMIN_PASS, SPACE_ID, GRAPH_ID } from '../seed-constants';

/**
 * Tier 7 — Files CRUD via streaming endpoints
 *
 * Tests Upload (create file node + stream content), Download with byte-level
 * verification, and larger file sizes to exercise the streaming path.
 * Uses /api/files/stream/upload and /api/files/stream/download.
 * Requires MinIO in the test Docker stack.
 */

const TEST_FILE_NAME = 'E2E Test File';
const TEST_FILENAME = 'e2e_test_file.txt';

// Small file (57 bytes)
const SMALL_CONTENT = Buffer.from('Hello from E2E streaming upload test!\nLine 2 of the file.');

// Medium file (~100KB of random binary data — exercises multi-chunk streaming)
const MEDIUM_SIZE = 100 * 1024;
const MEDIUM_CONTENT = crypto.randomBytes(MEDIUM_SIZE);

// Large file (~1MB — exercises multi-part upload path in MinIO)
const LARGE_SIZE = 1024 * 1024;
const LARGE_CONTENT = crypto.randomBytes(LARGE_SIZE);

const fileUris: string[] = [];

/** Get auth headers. */
async function getAuthHeaders() {
  const baseURL = process.env.VG_TEST_URL || 'http://localhost:8002';
  const ctx = await request.newContext({ baseURL });
  const loginResp = await ctx.post('/api/login', {
    form: { username: ADMIN_USER, password: ADMIN_PASS },
  });
  const { access_token } = await loginResp.json();
  const headers = { Authorization: `Bearer ${access_token}` };
  return { ctx, headers };
}

/** Create a FileNode and return its URI. */
async function createFileNode(name: string, filename: string): Promise<string> {
  const { ctx, headers } = await getAuthHeaders();
  const fileUri = `urn:e2e:file:${filename}-${Date.now()}`;
  const createResp = await ctx.post('/api/files', {
    params: { space_id: SPACE_ID, graph_id: GRAPH_ID },
    headers: { ...headers, 'Content-Type': 'application/json' },
    data: {
      quads: [
        { s: `<${fileUri}>`, p: '<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>', o: '<http://vital.ai/ontology/vital#FileNode>' },
        { s: `<${fileUri}>`, p: '<http://vital.ai/ontology/vital-core#hasName>', o: `"${name}"` },
        { s: `<${fileUri}>`, p: '<http://vital.ai/ontology/vital-core#hasFileName>', o: `"${filename}"` },
      ],
    },
  });
  expect(createResp.ok(), `Create file failed: ${await createResp.text()}`).toBeTruthy();
  const body = await createResp.json();
  const uri = body.created_uris?.[0] || fileUri;
  fileUris.push(uri);
  await ctx.dispose();
  return uri;
}

/** Upload content to a FileNode via streaming endpoint. */
async function uploadContent(uri: string, content: Buffer, filename: string, mimeType = 'application/octet-stream') {
  const { ctx, headers } = await getAuthHeaders();
  const uploadResp = await ctx.post('/api/files/stream/upload', {
    params: { space_id: SPACE_ID, graph_id: GRAPH_ID, uri },
    headers,
    multipart: {
      file: { name: filename, mimeType, buffer: content },
    },
  });
  expect(uploadResp.ok(), `Upload failed: ${await uploadResp.text()}`).toBeTruthy();
  await ctx.dispose();
}

/** Download content from a FileNode via streaming endpoint. */
async function downloadContent(uri: string): Promise<Buffer> {
  const { ctx, headers } = await getAuthHeaders();
  const downloadResp = await ctx.get('/api/files/stream/download', {
    params: { space_id: SPACE_ID, graph_id: GRAPH_ID, uri },
    headers,
  });
  expect(downloadResp.ok(), `Download failed: status ${downloadResp.status()}`).toBeTruthy();
  const buf = Buffer.from(await downloadResp.body());
  await ctx.dispose();
  return buf;
}

/** Cleanup all tracked file URIs. */
async function cleanupAll() {
  const { ctx, headers } = await getAuthHeaders();
  for (const uri of fileUris) {
    await ctx.delete('/api/files', {
      params: { space_id: SPACE_ID, uri },
      headers,
    }).catch(() => {});
  }
  // Also clean up any leftover test files by name
  const listResp = await ctx.get('/api/files', {
    params: { space_id: SPACE_ID, graph_id: GRAPH_ID, page_size: 200, file_filter: 'E2E' },
    headers,
  });
  if (listResp.ok()) {
    const data = await listResp.json();
    const results = data.results || [];
    const uris = [...new Set(results.map((q: { s: string }) => q.s.replace(/^<|>$/g, '')))];
    for (const u of uris) {
      await ctx.delete('/api/files', {
        params: { space_id: SPACE_ID, uri: u as string },
        headers,
      }).catch(() => {});
    }
  }
  await ctx.dispose();
  fileUris.length = 0;
}

test.describe('Files streaming — byte-level round-trip', () => {
  test.describe.configure({ mode: 'serial' });

  test.beforeAll(async () => { await cleanupAll(); });
  test.afterAll(async () => { await cleanupAll(); });

  test('small file (57B): upload and download match byte-for-byte', async () => {
    const uri = await createFileNode('E2E Small File', 'e2e_small.txt');
    await uploadContent(uri, SMALL_CONTENT, 'e2e_small.txt', 'text/plain');
    const downloaded = await downloadContent(uri);

    expect(downloaded.length).toBe(SMALL_CONTENT.length);
    expect(downloaded.equals(SMALL_CONTENT)).toBe(true);
  });

  test('medium file (100KB): upload and download match byte-for-byte', async () => {
    const uri = await createFileNode('E2E Medium File', 'e2e_medium.bin');
    await uploadContent(uri, MEDIUM_CONTENT, 'e2e_medium.bin');
    const downloaded = await downloadContent(uri);

    expect(downloaded.length).toBe(MEDIUM_CONTENT.length);
    expect(downloaded.equals(MEDIUM_CONTENT)).toBe(true);
  });

  test('large file (1MB): upload and download match byte-for-byte', async () => {
    const uri = await createFileNode('E2E Large File', 'e2e_large.bin');
    await uploadContent(uri, LARGE_CONTENT, 'e2e_large.bin');
    const downloaded = await downloadContent(uri);

    expect(downloaded.length).toBe(LARGE_CONTENT.length);
    expect(downloaded.equals(LARGE_CONTENT)).toBe(true);
  });
});

test.describe('Files CRUD — UI lifecycle', () => {
  test.describe.configure({ mode: 'serial' });

  let crudFileUri = '';

  test.beforeAll(async () => { await cleanupAll(); });
  test.afterAll(async () => { await cleanupAll(); });

  test('create and upload a file for UI tests', async () => {
    crudFileUri = await createFileNode(TEST_FILE_NAME, TEST_FILENAME);
    await uploadContent(crudFileUri, SMALL_CONTENT, TEST_FILENAME, 'text/plain');
  });

  test('file appears in the UI list', async ({ page }) => {
    const encodedGraph = encodeURIComponent(GRAPH_ID);
    await page.goto(`/space/${SPACE_ID}/graph/${encodedGraph}/files`);
    await expect(page.locator('[data-testid="files-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(TEST_FILE_NAME).first()).toBeVisible({ timeout: 10_000 });
  });

  test('delete file via the UI', async ({ page }) => {
    const encodedGraph = encodeURIComponent(GRAPH_ID);
    await page.goto(`/space/${SPACE_ID}/graph/${encodedGraph}/files`);
    await expect(page.locator('[data-testid="files-page"]')).toBeVisible({ timeout: 10_000 });

    // Find the row with our file URI and click "View details"
    const row = page.locator('table tbody tr', { hasText: crudFileUri });
    await expect(row).toBeVisible({ timeout: 10_000 });
    await row.locator('button[title="View details"]').click();
    await expect(page.locator('[data-testid="file-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // Click Delete button
    await page.locator('button', { hasText: 'Delete' }).click();

    // Confirm in modal
    const modal = page.locator('[role="dialog"]').first();
    await expect(modal.getByText('Confirm Deletion')).toBeVisible({ timeout: 5_000 });
    await modal.locator('button', { hasText: 'Delete File' }).click();

    // Should navigate back — file should no longer be listed
    await expect(page.locator('[data-testid="files-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('table tbody tr', { hasText: crudFileUri })).not.toBeVisible({ timeout: 5_000 });

    // Remove from tracked URIs
    const idx = fileUris.indexOf(crudFileUri);
    if (idx >= 0) fileUris.splice(idx, 1);
    crudFileUri = '';
  });
});
