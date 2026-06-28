# VitalGraph UI End-to-End Testing Plan

## 1. Overview

This document defines the automated end-to-end (E2E) testing strategy for the
VitalGraph web UI. The goal is fully automated browser-based testing that
exercises the complete stack — React frontend → REST API → PostgreSQL — and
runs in CI on every relevant PR.

---

## 2. Tooling — Playwright

**Why Playwright**:
- Cross-browser: Chromium, Firefox, WebKit in a single test run
- TypeScript-native: matches the frontend stack
- Built-in `expect` assertions with auto-retrying locators
- Network interception via `page.route()` for error simulation
- Visual regression via `toHaveScreenshot()`
- `codegen` tool for rapid test authoring
- Headless CI execution with no extra infrastructure
- Trace viewer and HTML report for debugging failures

**Install** (add to `frontend/package.json` devDependencies):
```
@playwright/test: ^1.49
```

---

## 3. Directory Layout

```
frontend/
├── e2e/                            # All Playwright tests
│   ├── fixtures/
│   │   ├── auth.ts                 # Login helper, shared authenticated page
│   │   └── seed.ts                 # API-driven test data setup/teardown
│   ├── pages/                      # Page Object Models (POM)
│   │   ├── login.page.ts
│   │   ├── spaces.page.ts
│   │   ├── space-detail.page.ts
│   │   ├── graphs.page.ts
│   │   ├── graph-detail.page.ts
│   │   ├── objects.page.ts
│   │   ├── object-detail.page.ts
│   │   ├── kg-entities.page.ts
│   │   ├── kg-frames.page.ts
│   │   ├── kg-types.page.ts
│   │   ├── triples.page.ts
│   │   ├── files.page.ts
│   │   ├── users.page.ts
│   │   ├── sparql.page.ts
│   │   ├── data-import.page.ts
│   │   ├── data-export.page.ts
│   │   └── admin.page.ts
│   ├── auth.spec.ts                # Login, logout, token refresh
│   ├── spaces.spec.ts              # Spaces CRUD
│   ├── users.spec.ts               # Users CRUD
│   ├── graphs.spec.ts              # Graphs CRUD
│   ├── objects.spec.ts             # Objects/KGEntities/KGFrames CRUD
│   ├── kg-types.spec.ts            # KG Types CRUD
│   ├── triples.spec.ts             # Triples list, filter
│   ├── files.spec.ts               # File upload, detail, download
│   ├── sparql.spec.ts              # SPARQL query execution
│   ├── data.spec.ts                # Import/Export flows
│   ├── navigation.spec.ts          # Sidebar, breadcrumbs, deep links
│   └── smoke.spec.ts               # Fast smoke: login + visit every page
├── playwright.config.ts
└── package.json
```

---

## 4. Playwright Configuration

```typescript
// frontend/playwright.config.ts
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [
    ['html', { open: 'never' }],
    ['junit', { outputFile: 'e2e-results.xml' }],
  ],
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
```

---

## 5. Test Architecture

### 5.1 Authentication Fixture

A shared fixture logs in once and reuses the authenticated browser state across
all tests in a worker, avoiding repeated login overhead:

```typescript
// e2e/fixtures/auth.ts
import { test as base, expect, Page } from '@playwright/test';

export const test = base.extend<{ authenticatedPage: Page }>({
  authenticatedPage: async ({ browser }, use) => {
    const context = await browser.newContext();
    const page = await context.newPage();
    await page.goto('/login');
    await page.fill('input[name="username"]', process.env.E2E_USER || 'admin');
    await page.fill('input[name="password"]', process.env.E2E_PASS || 'admin');
    await page.click('button[type="submit"]');
    await expect(page).toHaveURL('/');
    await use(page);
    await context.close();
  },
});
```

### 5.2 Data Seeding Fixture

Tests should not depend on pre-existing data. A seed fixture creates the
required test data via direct API calls (bypassing the UI) before each test
suite and tears it down after:

```typescript
// e2e/fixtures/seed.ts
import { test as base } from './auth';

interface SeedResult {
  space: any;
  token: string;
}

export const test = base.extend<{ seedData: SeedResult }>({
  seedData: async ({ request }, use) => {
    // Login via API
    const loginResp = await request.post('/api/login', {
      form: { username: 'admin', password: 'admin' }
    });
    const { access_token } = await loginResp.json();
    const headers = { Authorization: `Bearer ${access_token}` };

    // Create test space
    const spaceResp = await request.post('/api/spaces', {
      headers,
      data: { space: 'e2e_test_space', space_name: 'E2E Test Space' }
    });
    const space = await spaceResp.json();

    // Create test graph, entities, etc. as needed
    // ...

    await use({ space, token: access_token });

    // Teardown: delete test space
    await request.delete(`/api/spaces/${space.space.space}`, { headers });
  },
});
```

### 5.3 Page Object Models (POM)

Each page gets a class encapsulating its locators and common actions. Tests stay
readable and resilient to selector changes:

```typescript
// e2e/pages/spaces.page.ts
import { Page, expect } from '@playwright/test';

export class SpacesPage {
  constructor(private page: Page) {}

  async navigate() {
    await this.page.click('a[href="/spaces"]');
    await expect(this.page.locator('h1')).toContainText('Spaces');
  }

  async getSpaceRows() {
    return this.page.locator('table tbody tr');
  }

  async searchSpaces(term: string) {
    await this.page.fill('input[placeholder*="Search"]', term);
  }

  async clickSpace(spaceName: string) {
    await this.page.click(`text=${spaceName}`);
  }

  async clickNewSpace() {
    await this.page.click('text=New Space');
  }
}
```

---

## 6. Test Scenarios

### 6.1 Smoke Suite (`smoke.spec.ts`) — runs on every PR

Fast check that the app boots, login works, and every page is reachable:

| # | Test | Assertions |
|---|------|------------|
| 1 | Login with valid credentials | Redirects to `/`, user name visible in navbar |
| 2 | Login with invalid credentials | Error alert shown, stays on `/login` |
| 3 | Visit every sidebar link | Each page loads without JS errors, no blank screens |
| 4 | Logout | Redirects to `/login`, protected routes redirect back |

### 6.2 Auth Suite (`auth.spec.ts`)

| # | Test | Assertions |
|---|------|------------|
| 1 | Token refresh on 401 | Mock API to return 401 once, verify silent retry succeeds |
| 2 | Expired session redirect | Clear tokens, visit protected route, verify redirect to `/login` |
| 3 | Session persistence | Login, reload page, verify still authenticated |

### 6.3 CRUD Suites (per entity type)

Each CRUD spec follows this template:

```
1. Seed: create test space + graph via API
2. Create: navigate to list → click "New" → fill form → submit → verify redirect to detail
3. Read:   navigate to list → verify new item appears → click → verify detail fields
4. Update: click Edit → change fields → save → verify updated values
5. Delete: click Delete → confirm modal → verify removed from list
6. Teardown: delete test space via API
```

**Entity-specific tests**:

| Suite | Key scenarios beyond basic CRUD |
|---|---|
| `spaces.spec.ts` | Filter by name, create with description, delete non-empty space warning |
| `graphs.spec.ts` | Space selector filters graphs, graph type badge display |
| `objects.spec.ts` | Tab switching (Objects ↔ KG Entities ↔ KG Frames), space+graph selection carries across tabs |
| `kg-types.spec.ts` | Create with custom properties, JSON-LD property display |
| `triples.spec.ts` | Filter by subject/predicate/object, pagination, triple count badge |
| `files.spec.ts` | File upload (drag-and-drop + button), download, detail view |
| `sparql.spec.ts` | Execute SELECT → results table, ASK → boolean, CONSTRUCT → triples, syntax error → error display |
| `data.spec.ts` | Create import job, execute import, verify progress, create export job |
| `users.spec.ts` | Create user, update role, change password, delete user |

### 6.4 Navigation Suite (`navigation.spec.ts`)

| # | Test | Assertions |
|---|------|------------|
| 1 | Sidebar active state | Clicking each link highlights correct sidebar item |
| 2 | Breadcrumb trail | Space → Graph → Objects shows correct breadcrumb chain |
| 3 | Deep link | Directly visit `/space/X/graph/Y/objects/graphobjects`, verify correct space+graph selected |
| 4 | Browser back/forward | Navigate Space→Graph→Objects, back button returns to Graphs |
| 5 | Mobile sidebar | At mobile viewport, sidebar collapses, hamburger toggles it |
| 6 | Dark mode | Toggle dark mode, verify no broken contrast/colors |

---

## 7. CI Integration

### 7.1 Docker Compose for E2E

A dedicated `docker-compose.e2e.yml` starts the full stack
(PostgreSQL + Jena sidecar + VitalGraph server + MinIO) and runs
Playwright against it:

```yaml
# docker-compose.e2e.yml
services:
  postgres:
    image: postgres:17
    environment:
      POSTGRES_DB: vitalgraph_e2e
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: test
    ports: ["5432:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      retries: 5

  sparql-compiler:
    build:
      context: ./vitalgraph-jena-sidecar
      dockerfile: Dockerfile
    ports: ["7070:7070"]

  minio:
    image: minio/minio:latest
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    command: server /data --console-address ":9001"
    ports: ["9000:9000"]

  vitalgraph:
    build: .
    depends_on:
      postgres: { condition: service_healthy }
      sparql-compiler: { condition: service_started }
      minio: { condition: service_started }
    environment:
      APP_MODE: production
      DATABASE_URL: postgresql://postgres:test@postgres:5432/vitalgraph_e2e
      SIDECAR_URL: http://sparql-compiler:7070
      MINIO_ENDPOINT: minio:9000
      JWT_SECRET_KEY: e2e-test-secret
      E2E_ADMIN_USER: admin
      E2E_ADMIN_PASS: admin
    ports: ["8001:8001"]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/health"]
      interval: 5s
      retries: 10

  playwright:
    image: mcr.microsoft.com/playwright:v1.49.0-noble
    depends_on:
      vitalgraph: { condition: service_healthy }
    working_dir: /app/frontend
    environment:
      E2E_BASE_URL: http://vitalgraph:8001
      E2E_USER: admin
      E2E_PASS: admin
      CI: "true"
    volumes:
      - .:/app
    command: npx playwright test --reporter=junit
```

### 7.2 GitHub Actions Workflow

```yaml
# .github/workflows/e2e.yml
name: E2E Tests
on:
  push:
    branches: [main]
  pull_request:
    paths: ['frontend/**', 'vitalgraph/endpoint/**', 'vitalgraph/api/**']

jobs:
  e2e:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4

      - name: Build and start services
        run: docker compose -f docker-compose.e2e.yml up -d --build --wait

      - name: Run Playwright tests
        run: docker compose -f docker-compose.e2e.yml run playwright

      - name: Upload test artifacts
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: playwright-report
          path: frontend/playwright-report/
          retention-days: 14

      - name: Upload test results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: e2e-results
          path: frontend/e2e-results.xml

      - name: Teardown
        if: always()
        run: docker compose -f docker-compose.e2e.yml down -v
```

---

## 8. npm Scripts

Add to `frontend/package.json`:
```json
{
  "scripts": {
    "test:e2e": "playwright test",
    "test:e2e:headed": "playwright test --headed",
    "test:e2e:ui": "playwright test --ui",
    "test:e2e:smoke": "playwright test smoke.spec.ts",
    "test:e2e:codegen": "playwright codegen http://localhost:5173",
    "test:e2e:report": "playwright show-report"
  }
}
```

---

## 9. Test Data Strategy

| Approach | When to use |
|---|---|
| **API seeding** (preferred) | Most tests. Create data via REST API before test, teardown after. Fast, deterministic. |
| **Database seeding** | Performance/load tests. Load large datasets via SQL directly. |
| **UI seeding** | Only for testing the create flow itself. All other tests seed via API. |
| **Network mocking** | Error state tests (simulate 500, timeout, network failure). Use `page.route()` to intercept. |

---

## 10. Browser Scope

Chromium-only for now. Additional browsers (Firefox, WebKit) or mobile
viewports can be added later by extending the `projects` array in
`playwright.config.ts`.

---

## 11. Visual Regression (Optional, Post-Stabilization)

After the UI design is stable, add visual regression via Playwright screenshots:
```typescript
await expect(page).toHaveScreenshot('spaces-list.png', { maxDiffPixels: 100 });
```
Store baseline screenshots in `e2e/screenshots/` and update them intentionally
when UI changes. This catches unintended CSS/layout breakages.

---

## 12. Estimated Scope

| Category | Test count | Runtime |
|---|---|---|
| Smoke | 4 | < 30s |
| Auth | 3 | < 30s |
| CRUD (9 entity types × ~5 tests) | ~45 | < 5 min |
| Navigation | 6 | < 1 min |
| SPARQL | 4 | < 1 min |
| Data Import/Export | 4 | < 1 min |
| **Total** | **~66** | **< 8 min** |

Chromium-only keeps runtime fast. Adding more browsers later scales linearly.

---

## 13. Relationship to Backend Testing

The E2E browser tests complement — but do not replace — the backend test tiers
defined in `planning_testing/testing_plan.md`:

```
Tier 1: Unit (Python, no DB)              — fast, ~150 tests
Tier 2: SPARQL Conformance (DAWG/ARQ)     — needs PG
Tier 3: Integration (storage, KG, schema) — needs PG
Tier 4: API (REST contract via httpx)     — needs server
Tier 5: Performance (benchmarks)          — nightly
───────────────────────────────────────────────────────
Tier 6: E2E (browser, Playwright)         — needs full stack  ← THIS PLAN
```

Tier 4 verifies backend REST contracts in isolation (no browser, no JS).
Tier 6 verifies the **full frontend→backend round-trip** through a real
browser — auth flow, form submission, data rendering, navigation, error display.

---

## 14. Implementation Phases

### Phase A: Foundation (with Phase 1–2 of UI plan)
1. Install Playwright, create `playwright.config.ts`
2. Create auth fixture and smoke test
3. Create Page Object Models for existing complete pages (Spaces, Users, Graphs)
4. Write CRUD specs for Spaces, Users, Graphs

### Phase B: Expand Coverage (with Phase 3–4 of UI plan)
5. Add POMs and specs for Objects, KGEntities, KGFrames, KGTypes, Triples
6. Add Files spec (upload, detail, download)
7. Add SPARQL spec
8. Add navigation spec

### Phase C: Data & Admin (with Phase 5–6 of UI plan)
9. Add Data Import/Export specs (after mock elimination)
10. Add Admin page spec
11. Add Entity Registry / Agent Registry specs

### Phase D: CI & Polish (with Phase 7 of UI plan)
12. Create `docker-compose.e2e.yml`
13. Create `.github/workflows/e2e.yml`
14. Add visual regression baselines
15. Tune flaky test detection (3x retry in CI)

---

## 15. Success Criteria

| Metric | Target |
|---|---|
| Smoke suite passes | 100% on every PR |
| CRUD coverage | Every entity type has create/read/update/delete spec |
| Cross-browser | Chromium + Firefox + WebKit all green |
| Mobile viewport | Navigation and layout specs pass on iPhone 14 |
| CI runtime | < 10 min for full suite |
| Zero flaky tests | 100% deterministic (retry-stable) |
| No manual testing required | All per-screen verification automated |
