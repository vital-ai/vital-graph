/**
 * Playwright global setup — runs once before all test suites.
 *
 * Waits for the VitalGraph server to be healthy.
 * Seeding is handled by run-tests.sh before Playwright starts.
 * If running Playwright directly (without the shell script), seed
 * manually first:
 *   python -m tests.shared.seed_ui_test_data --server-url http://localhost:8002
 */

const BASE_URL = process.env.VG_TEST_URL || 'http://localhost:8002';
const MAX_WAIT_MS = 60_000;
const POLL_INTERVAL_MS = 2_000;

async function globalSetup(): Promise<void> {
  const start = Date.now();
  while (Date.now() - start < MAX_WAIT_MS) {
    try {
      const res = await fetch(`${BASE_URL}/health`);
      if (res.ok) {
        console.log(`✅ VitalGraph server is healthy at ${BASE_URL}`);
        return;
      }
    } catch {
      // Server not ready yet
    }
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
  }
  throw new Error(`Server at ${BASE_URL} did not become healthy within ${MAX_WAIT_MS / 1000}s`);
}

export default globalSetup;
