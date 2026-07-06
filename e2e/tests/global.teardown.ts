import { test as teardown } from '@playwright/test';

teardown('cleanup auth state', async ({}) => {
  // Placeholder — add any post-suite cleanup here (e.g. delete test data).
  // The docker-compose stack is torn down externally.
});
