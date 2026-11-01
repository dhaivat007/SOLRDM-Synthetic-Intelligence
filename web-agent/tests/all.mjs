// Import into one test runner: works on restricted executors and in CI.
await import('./tools.test.mjs');
await import('./model.test.mjs');
await import('./worker.test.mjs');
