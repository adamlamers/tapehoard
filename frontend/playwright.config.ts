import { defineConfig, devices } from '@playwright/test';

/**
 * See https://playwright.dev/docs/test-configuration.
 */
export default defineConfig({
  testDir: './tests',
  timeout: 120000,
  /* Run tests in files in parallel */
  fullyParallel: false,
  /* Fail the build on CI if you accidentally left test.only in the source code. */
  forbidOnly: !!process.env.CI,
  /* Retry on CI only */
  retries: process.env.CI ? 2 : 0,
  /* Run tests serially to avoid DB conflicts */
  workers: 1,
  /* Reporter to use. See https://playwright.dev/docs/test-reporters */
  reporter: [['html', { open: 'never' }]],
  /* Shared settings for all the projects below. See https://playwright.dev/docs/api/class-testoptions. */
  use: {
    /* Base URL to use in actions like `await page.goto('/')`. */
    baseURL: 'http://localhost:5173',

    /* Collect trace when retrying the failed test. See https://playwright.dev/docs/trace-viewer */
    trace: 'on-first-retry',
    video: 'retain-on-failure',
  },

  /* Configure projects for major browsers */
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  /* Run your local dev server before starting the tests */
  webServer: [
    {
      command: 'cd ../backend && rm -f e2e_test.db* && DATABASE_URL="sqlite:///e2e_test.db" TAPEHOARD_TEST_MODE="true" uv run python -m app.start_test_server --host 0.0.0.0 --port 8001',
      url: 'http://localhost:8001/health',
      reuseExistingServer: false,
      timeout: 120 * 1000,
    },
    {
      command: 'VITE_API_URL=http://localhost:8001 npm run dev',
      url: 'http://localhost:5173',
      reuseExistingServer: false,
      timeout: 120 * 1000,
    },
  ],
});
