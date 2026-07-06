import { test, expect, request } from '@playwright/test';
import { ADMIN_USER, ADMIN_PASS } from '../seed-constants';

/**
 * Tier 7 — Agent Registry CRUD Write Operations
 *
 * Tests the Create, List, Update, and Delete flows for agent registry entries.
 * Uses form-based UI similar to Entity Registry.
 */

const RUN_ID = Date.now();
const CRUD_AGENT_NAME = `E2E Agent ${RUN_ID}`;
const CRUD_AGENT_URI = `urn:e2e:agent:crud-${RUN_ID}`;
const CRUD_AGENT_TYPE = 'e2e_bot';
const UPDATED_AGENT_DESC = 'Updated by E2E CRUD test';

/** Soft-delete any agent with the test URI via API (best-effort cleanup). */
async function cleanupCrudAgent() {
  const baseURL = process.env.VG_TEST_URL || 'http://localhost:8002';
  const ctx = await request.newContext({ baseURL });
  const loginResp = await ctx.post('/api/login', {
    form: { username: ADMIN_USER, password: ADMIN_PASS },
  });
  const { access_token } = await loginResp.json();
  const headers = { Authorization: `Bearer ${access_token}` };

  // Search for our agent by URI (includes deleted status)
  const listResp = await ctx.get('/api/agents/agent', {
    params: { agent_uri: CRUD_AGENT_URI },
    headers,
  });
  const data = await listResp.json();
  const agents = data.agents || [];

  for (const agent of agents) {
    if (agent.status !== 'deleted') {
      await ctx.delete('/api/agents/agent', {
        params: { agent_id: agent.agent_id },
        headers,
      });
    }
  }
  await ctx.dispose();
}

test.describe('Agent Registry CRUD', () => {
  test.describe.configure({ mode: 'serial' });

  test.afterAll(async () => { await cleanupCrudAgent(); });

  test('create a new agent via the UI', async ({ page }) => {
    await page.goto('/agent-registry/new');
    await expect(page.locator('[data-testid="agent-registry-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // Fill in the create form
    await page.locator('#name').fill(CRUD_AGENT_NAME);
    await page.locator('#uri').fill(CRUD_AGENT_URI);
    await page.locator('#type').fill(CRUD_AGENT_TYPE);
    await page.locator('#desc').fill('Initial agent description');

    // Click Register Agent
    await page.locator('button', { hasText: 'Register Agent' }).click();

    // Should redirect back to the agent registry list
    await expect(page).toHaveURL(/\/agent-registry$/, { timeout: 10_000 });
  });

  test('new agent appears in the registry list', async ({ page }) => {
    await page.goto('/agent-registry');
    await expect(page.locator('[data-testid="agent-registry-page"]')).toBeVisible({ timeout: 10_000 });

    // Verify agent name appears in the table
    await expect(page.getByText(CRUD_AGENT_NAME)).toBeVisible({ timeout: 10_000 });
  });

  test('update the agent via the UI', async ({ page }) => {
    await page.goto('/agent-registry');
    await expect(page.locator('[data-testid="agent-registry-page"]')).toBeVisible({ timeout: 10_000 });

    // Click on the agent row to navigate to detail
    await page.getByText(CRUD_AGENT_NAME).click();

    // Wait for detail page
    await expect(page.locator('[data-testid="agent-registry-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // Switch to edit mode
    await page.locator('button', { hasText: 'Edit' }).click();

    // Update the description
    await page.locator('#desc').fill(UPDATED_AGENT_DESC);

    // Click Save
    await page.locator('button', { hasText: 'Save' }).click();

    // Should switch back to view mode — verify the description appears
    await expect(page.getByText(UPDATED_AGENT_DESC)).toBeVisible({ timeout: 10_000 });
  });

  test('delete the agent via the UI', async ({ page }) => {
    await page.goto('/agent-registry');
    await expect(page.locator('[data-testid="agent-registry-page"]')).toBeVisible({ timeout: 10_000 });

    // Click on the agent row
    await page.getByText(CRUD_AGENT_NAME).click();

    // Wait for detail page
    await expect(page.locator('[data-testid="agent-registry-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // Click the Delete button
    await page.locator('button', { hasText: 'Delete' }).click();

    // Confirm modal
    const modal = page.locator('[role="dialog"]');
    await expect(modal).toBeVisible({ timeout: 5_000 });
    await expect(modal.getByRole('heading', { name: /delete agent/i })).toBeVisible();

    // Click Delete in the modal
    await modal.getByRole('button', { name: /delete/i }).first().click();

    // Should redirect back to the registry list
    await expect(page).toHaveURL(/\/agent-registry$/, { timeout: 10_000 });

    // Agent should no longer appear
    await expect(page.getByText(CRUD_AGENT_NAME)).not.toBeVisible({ timeout: 5_000 });
  });
});
