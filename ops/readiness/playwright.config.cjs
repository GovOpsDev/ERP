const { defineConfig } = require('@playwright/test');
const path = require('path');
const evidence = process.env.READINESS_EVIDENCE_DIR;
if (!evidence) throw new Error('READINESS_EVIDENCE_DIR must point outside the source repository');
module.exports = defineConfig({
  testDir: './browser', testIgnore: process.env.READINESS_ROLLBACK==='1' ? ['**/flows.spec.cjs','**/readiness.spec.cjs'] : ['**/rollback.spec.cjs'], workers: 1, retries: 0, timeout: 90000,
  expect: { timeout: 20000 },
  outputDir: path.join(evidence, 'browser-artifacts'),
  reporter: [['line'], ['json', { outputFile: path.join(evidence, 'browser-results.json') }]],
  use: { actionTimeout: 15000, navigationTimeout: 30000, serviceWorkers: 'block', baseURL: 'http://127.0.0.1:18069', viewport: { width: 1440, height: 1000 },
    trace: 'off', screenshot: 'only-on-failure' },
});
