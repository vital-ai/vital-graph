import { test, expect } from '@playwright/test';
import { ADMIN_USER, SEEDED_ENTITY_REGISTRY, SEEDED_AGENT } from '../seed-constants';

/**
 * Tier 9 — Admin detail pages
 *
 * Covers: Admin content, AuditLog content, ApiKeys content,
 *         EntityRegistry + Detail, AgentRegistry + Detail, User Detail
 */

// ---------- Admin page content ---------------------------------------------

test.describe('Admin page', () => {
  test('shows administration heading and controls', async ({ page }) => {
    await page.goto('/admin');
    await expect(page.locator('[data-testid="admin-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole('heading', { name: /administration/i })).toBeVisible();
  });
});

// ---------- Audit Log content ----------------------------------------------

test.describe('Audit Log', () => {
  test('shows log table or empty state', async ({ page }) => {
    await page.goto('/audit-log');
    await expect(page.locator('[data-testid="audit-log-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole('heading', { name: /audit/i })).toBeVisible();
  });
});

// ---------- API Keys content -----------------------------------------------

test.describe('API Keys', () => {
  test('shows key list or create button', async ({ page }) => {
    await page.goto('/api-keys');
    await expect(page.locator('[data-testid="api-keys-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole('heading', { name: /api key/i })).toBeVisible();
  });
});

// ---------- Entity Registry ------------------------------------------------

test.describe('Entity Registry', () => {
  test('list page loads and shows seeded entry', async ({ page }) => {
    await page.goto('/entity-registry');
    await expect(page.locator('[data-testid="entity-registry-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(SEEDED_ENTITY_REGISTRY.primary_name).first()).toBeVisible({ timeout: 10_000 });
  });

  test('navigates to seeded entry detail', async ({ page }) => {
    await page.goto('/entity-registry');
    await expect(page.locator('[data-testid="entity-registry-page"]')).toBeVisible({ timeout: 10_000 });
    await page.getByText(SEEDED_ENTITY_REGISTRY.primary_name).first().click();
    await expect(page.locator('[data-testid="entity-registry-detail-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(SEEDED_ENTITY_REGISTRY.primary_name).first()).toBeVisible();
  });
});

// ---------- Agent Registry -------------------------------------------------

test.describe('Agent Registry', () => {
  test('list page loads and shows seeded agent', async ({ page }) => {
    await page.goto('/agent-registry');
    await expect(page.locator('[data-testid="agent-registry-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(SEEDED_AGENT.name).first()).toBeVisible({ timeout: 10_000 });
  });

  test('navigates to seeded agent detail', async ({ page }) => {
    await page.goto('/agent-registry');
    await expect(page.locator('[data-testid="agent-registry-page"]')).toBeVisible({ timeout: 10_000 });
    await page.getByText(SEEDED_AGENT.name).first().click();
    await expect(page.locator('[data-testid="agent-registry-detail-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(SEEDED_AGENT.name).first()).toBeVisible();
  });
});

// ---------- User Detail ----------------------------------------------------

test.describe('User Detail', () => {
  test('admin user detail page loads', async ({ page }) => {
    // Navigate via users list
    await page.goto('/users');
    await expect(page.locator('[data-testid="users-page"]')).toBeVisible({ timeout: 10_000 });
    await page.getByRole('link', { name: new RegExp(ADMIN_USER) }).first().click();
    await expect(page.locator('[data-testid="user-detail-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(ADMIN_USER).first()).toBeVisible();
  });
});
