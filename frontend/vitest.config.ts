import { defineConfig } from 'vitest/config';

/**
 * Unit tests for pure frontend logic.
 *
 * Browser-level UI behavior is covered by the Playwright suite in `e2e/`
 * (see planning/planning_ui/ui_testing_plan.md) — this config is for the
 * non-React modules under src/lib and src/utils, which are plain TypeScript
 * and need no DOM.
 */
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
});
