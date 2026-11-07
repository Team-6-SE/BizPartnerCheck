import { defineConfig, devices } from '@playwright/test'

/**
 * End-to-end tests in a real browser against the running stack:
 * database + Keycloak + Mailpit (docker compose), backend (uvicorn) and frontend (npm run dev).
 * See README → "End-to-end tests".
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  fullyParallel: false,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173',
    trace: 'retain-on-failure',
    // Optional: use an already installed Chromium instead of `npx playwright install`.
    launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {},
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
