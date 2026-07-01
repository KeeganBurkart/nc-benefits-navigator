import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from '@playwright/test'

// E2E against the real server with a deterministic fake LLM (NAV_FAKE_LLM=1).
// Run from web/: npm run e2e
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

export default defineConfig({
  testDir: path.join(ROOT, 'web', 'e2e'),
  timeout: 30_000,
  use: {
    baseURL: 'http://127.0.0.1:8123',
  },
  webServer: {
    command: 'uv run uvicorn server.app:app --port 8123',
    cwd: ROOT,
    url: 'http://127.0.0.1:8123/healthz',
    reuseExistingServer: false,
    env: {
      NAV_FAKE_LLM: '1',
      NAV_DEMO_MODE: '0',
    },
  },
})
