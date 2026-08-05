import { defineConfig, devices } from '@playwright/test';

/**
 * VitalGraph E2E Test Configuration
 *
 * Targets the test compose stack (docker-compose.test.yml) on port 8002.
 * Override with VG_TEST_URL env var if needed.
 */
export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: [['html'], ['json', { outputFile: 'test-results.json' }]],

  use: {
    baseURL: process.env.VG_TEST_URL || 'http://localhost:8002',
    // 'retain-on-failure', not 'on-first-retry': locally `retries` is 0, so
    // there is never a first retry and no trace was ever captured for the
    // parallel-load flake under investigation (issues/022). CI still gets a
    // trace on the failing attempt.
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },

  globalSetup: './global-setup.ts',

  projects: [
    // Auth setup — login once, save storageState
    {
      name: 'setup',
      testMatch: /auth\.setup\.ts/,
      teardown: 'cleanup',
    },
    {
      name: 'cleanup',
      testMatch: /global\.teardown\.ts/,
    },

    // Chromium only (per resolved decision #6)
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        storageState: '.auth/user.json',
      },
      dependencies: ['setup'],
    },
  ],
});
