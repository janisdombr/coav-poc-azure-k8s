import { defineConfig, devices } from '@playwright/test'

const BASE_URL = process.env.BASE_URL || 'http://localhost:5173'
const isRemote = BASE_URL.startsWith('http') && !BASE_URL.includes('localhost')

export default defineConfig({
  testDir: './e2e',
  timeout: 45_000,              // extra time for remote/prod
  fullyParallel: false,         // tests share backend state (flights, advisories)
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',

  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'on-first-retry',
  },

  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],

  // Skip local dev server when testing against a remote URL
  webServer: isRemote ? undefined : {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
})
