import { defineConfig } from '@playwright/test';

const python = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python';
const launchOptions = process.platform === 'darwin'
  ? { executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' }
  : {};

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: 'list',
  timeout: 45_000,
  use: {
    baseURL: 'http://127.0.0.1:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    launchOptions,
  },
  webServer: [
    {
      command: `${python} -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8740`,
      url: 'http://127.0.0.1:8740/api/health',
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: { HKUS_HOST: '127.0.0.1', HKUS_PORT: '8740', HKUS_DATA_MODE: 'DEMO' },
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 5173 --strictPort',
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
});
