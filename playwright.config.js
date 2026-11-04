const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./tests/ui",
  snapshotPathTemplate: "{testDir}/baselines/{arg}{ext}",
  timeout: 15_000,
  expect: { timeout: 5_000 },
  use: {
    baseURL: "http://127.0.0.1:8876",
    viewport: { width: 1280, height: 800 },
    trace: "retain-on-failure",
  },
  webServer: {
    command: `${process.env.WECHAT_AI_PYTHON || "python"} tests/ui/serve_fixture.py`,
    url: "http://127.0.0.1:8876/api/health",
    timeout: 20_000,
    reuseExistingServer: false,
  },
});
