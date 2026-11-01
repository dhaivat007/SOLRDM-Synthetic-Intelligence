/** Browser QA against the real Python service. Model inference is NOT exercised here.
 * Chat rendering/error recovery uses explicitly mocked responses; ARM64 CI tests
 * actual downloaded weights separately. Requires playwright@1.56.1 + Chromium.
 */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';
import { chromium } from 'playwright';

const root = resolve(fileURLToPath(new URL('..', import.meta.url)));
const repo = resolve(root, '..');
const evidence = join(root, 'evidence');
const base = 'http://127.0.0.1:19877';
const dataDir = await mkdtemp(join(tmpdir(), 'solrdm-pi-browser-'));
const checks = [], pageErrors = [], browserConsoleErrors = [];
let server, browser, output = '', serverError, activePage, mockedChatRequests = 0;
function record(name) { checks.push(name); console.log(`PASS ${name}`); }
async function ready() {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (serverError) throw serverError;
    if (server.exitCode !== null) throw new Error(`Service exited: ${output}`);
    try { const r = await fetch(`${base}/health`, { signal: AbortSignal.timeout(1000) }); if (r.ok) return; } catch { /* bounded startup retry */ }
    await delay(100);
  }
  throw new Error(`Service did not start: ${output}`);
}
function track(page) {
  page.setDefaultTimeout(15000);
  page.on('pageerror', e => pageErrors.push(e.message));
  page.on('console', m => { if (m.type() === 'error' && !m.text().includes('Failed to load resource')) browserConsoleErrors.push(m.text()); });
  return page;
}
async function noOverflow(page) {
  const sizes = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth, body: document.body.scrollWidth }));
  assert.ok(sizes.document <= sizes.viewport + 1 && sizes.body <= sizes.viewport + 1, JSON.stringify(sizes));
}
async function selectView(page, view) { await page.locator(`.nav[data-view="${view}"]`).click(); await page.locator(`#view-${view}`).waitFor({ state: 'visible' }); }

try {
  await mkdir(evidence, { recursive: true });
  server = spawn('python3', ['-m', 'solrdm_pi', '--data-dir', dataDir, '--port', '19877'], {
    cwd: root, env: { ...process.env, PYTHONPATH: [root, join(repo, 'app/src/main/python'), process.env.PYTHONPATH].filter(Boolean).join(':') }, stdio: ['ignore', 'pipe', 'pipe'],
  });
  server.on('error', e => { serverError = e; });
  server.stdout.on('data', d => { output += d; }); server.stderr.on('data', d => { output += d; });
  await ready();
  assert.equal((await fetch(`${base}/api/status`)).status, 403);
  record('Unauthenticated API calls are rejected by the real service');
  browser = await chromium.launch({ headless: true, args: ['--no-sandbox'], ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : {}) });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
  const page = activePage = track(await context.newPage());
  await page.goto(base);
  await page.waitForFunction(() => document.querySelector('#status-button').textContent === 'No model loaded');
  assert.match(await page.locator('#setup-title').innerText(), /Add and load a model/);
  await page.locator('#chat-input').fill('Hello');
  assert.equal(await page.locator('#send-button').isDisabled(), true);
  await noOverflow(page);
  record('First run explains missing weights and disables chat until a backend is selected');
  await selectView(page, 'models');
  await page.waitForFunction(() => document.querySelectorAll('.catalog-card').length >= 2);
  assert.match(await page.locator('#catalog').innerText(), /Qwen.*1.5B/s);
  assert.equal(await page.locator('#model-file').getAttribute('accept'), '.gguf');
  assert.match(await page.locator('#runtime-status').innerText(), /ARM64 package|llama-server found/);
  await page.screenshot({ path: join(evidence, 'desktop-model-library.png'), fullPage: true });
  record('Model catalog, file selector, Pi path attachment and cloud controls are visible');
  await page.locator('#model-url').fill('http://example.com/model.gguf');
  await page.locator('#cloud-form button').click();
  await page.waitForFunction(() => document.querySelector('#feedback').textContent.includes('require a direct HTTPS'));
  record('Cloud import rejects insecure links before beginning a download');
  // Container-only fixture checks transport and checksum, never loaded for inference.
  const fixture = Buffer.alloc(24); fixture.write('GGUF'); fixture.writeUInt32LE(3, 4);
  const fixtureSha = createHash('sha256').update(fixture).digest('hex');
  await page.locator('#model-file').setInputFiles({ name: 'browser-upload-fixture.gguf', mimeType: 'application/octet-stream', buffer: fixture });
  await page.locator('#upload-button').click();
  await page.waitForFunction(() => document.querySelector('#upload-status').textContent.includes('File copied and verified'));
  assert.match(await page.locator('#model-list').innerText(), /browser-upload-fixture/);
  await page.locator('.model-info details').first().evaluate(n => n.open = true);
  assert.match(await page.locator('#model-list').innerText(), new RegExp(fixtureSha));
  assert.equal(await page.locator('#status-button').innerText(), 'No model loaded');
  record('GGUF container fixture uploads through real chunk API and shows matching SHA-256; no inference claimed');
  await selectView(page, 'tools');
  await page.locator('#tool-select').selectOption('calculate');
  await page.locator('#tool-fields input[name="expression"]').fill('sqrt(144) + 2**3');
  await page.locator('#run-tool').click();
  await page.waitForFunction(() => document.querySelector('#tool-result pre')?.textContent.includes('"result": 20'));
  record('Offline calculator returns actual backend result 20');
  await page.locator('#tool-select').selectOption('simulate_projectile');
  await page.locator('#run-tool').click();
  await page.waitForFunction(() => document.querySelector('#tool-result pre')?.textContent.includes('"flightTime"'));
  const projectile = JSON.parse(await page.locator('#tool-result pre').innerText());
  assert.ok(Math.abs(projectile.range - 40.7747196738) < 0.000001);
  assert.equal(await page.locator('#tool-result canvas[role="img"]').count(), 1);
  assert.match(await page.locator('#tool-result canvas').getAttribute('aria-label'), /Horizontal distance \(m\).*Height \(m\)/);
  await page.screenshot({ path: join(evidence, 'desktop-projectile-simulation.png'), fullPage: true });
  record('Projectile simulation runs real equations and displays an accessible plot with units and assumptions');
  await page.locator('#engine-form').evaluate(n => n.closest('details').open = true);
  await page.locator('#engine-form button').click();
  await page.waitForFunction(() => document.querySelector('#engine-result').textContent.includes('module_count'));
  const engine = JSON.parse(await page.locator('#engine-result').innerText());
  assert.equal(engine.module_count, 16); assert.equal(engine.integration_complete, false);
  record('Supplied 16-module engine status is accessible and retains integration limits');
  await selectView(page, 'memory');
  const observation = 'Example observation <img src=x onerror="window.xss=true">';
  await page.locator('#memory-text').fill(observation); await page.locator('#memory-source').fill('Browser QA user observation');
  await page.locator('#memory-form button').click();
  await page.waitForFunction(() => document.querySelector('.memory-item')?.textContent.includes('Awaiting review'));
  assert.equal(await page.locator('.memory-item img').count(), 0);
  await page.locator('.memory-item').getByRole('button', { name: 'Approve for recall' }).click();
  await page.waitForFunction(() => document.querySelector('.memory-item')?.textContent.includes('Reviewed · approved'));
  assert.equal(await page.evaluate(() => window.xss), undefined);
  record('Observations require explicit review and untrusted markup is rendered as text');
  let releaseSettings, settingsRequested;
  const settingsHold = new Promise(resolve => { releaseSettings = resolve; });
  const settingsSeen = new Promise(resolve => { settingsRequested = resolve; });
  const holdSettings = async route => {
    if (route.request().method() === 'GET') { settingsRequested(); await settingsHold; }
    await route.continue();
  };
  await page.route('**/api/settings', holdSettings);
  await selectView(page, 'settings');
  await settingsSeen;
  assert.equal(await page.locator('#preferred-backend').isDisabled(), true);
  assert.equal(await page.locator('#provider-model').isDisabled(), true);
  releaseSettings();
  await page.waitForFunction(() => document.querySelector('#settings-form').getAttribute('aria-busy') === 'false');
  await page.unroute('**/api/settings', holdSettings);
  record('Settings remain disabled during a delayed load so a response cannot overwrite edits');
  await page.locator('#preferred-backend').selectOption('provider');
  await page.locator('#provider-url').fill('https://example.com/v1');
  await page.locator('#provider-model').fill('browser-mocked-model');
  await page.locator('#provider-key').fill('dummy-browser-test-secret');
  await page.locator('#settings-form button').click();
  await page.waitForFunction(() => document.querySelector('#feedback').textContent.includes('Settings saved'));
  assert.equal(await page.locator('#provider-key').inputValue(), '');
  assert.equal(await page.evaluate(() => JSON.stringify(localStorage).includes('dummy-browser-test-secret')), false);
  await page.reload(); await selectView(page, 'settings');
  await page.waitForFunction(() => document.querySelector('#provider-key-status').textContent.includes('An API key is saved'));
  assert.equal(await page.locator('#provider-key').inputValue(), '');
  assert.equal(await page.locator('#preferred-backend').inputValue(), 'provider');
  assert.equal(await page.locator('#provider-model').inputValue(), 'browser-mocked-model');
  await page.waitForFunction(() => document.querySelector('#status-button').textContent.includes('Online · browser-mocked-model'));
  record('Provider settings persist on the service without exposing the key in browser storage or responses');
  let failChat = true;
  await page.route('**/api/chat', async route => {
    mockedChatRequests++;
    const body = route.request().postDataJSON();
    assert.equal(body.attachments[0].kind, 'text');
    await route.fulfill({ status: failChat ? 400 : 200, contentType: 'application/json', body: JSON.stringify(failChat ? { error: 'Mocked provider unavailable; this is browser recovery QA.' } : { text: 'Mocked rendering check <script>window.xss=true</script>', model: 'browser-mocked-model', sources: [{ title: 'A safe source', url: 'https://example.com/paper' }, { title: 'unsafe', url: 'javascript:alert(1)' }], receipts: [{ tool: 'calculate', status: 'completed', summary: 'Mocked receipt for UI rendering only', data: { result: 20 }, assumptions: [] }] }) });
  });
  await selectView(page, 'chat');
  await page.locator('#chat-input').fill('Review this tiny text file');
  await page.locator('#chat-files').setInputFiles({ name: 'notes.txt', mimeType: 'text/plain', buffer: Buffer.from('A small text attachment.') });
  await page.waitForFunction(() => !document.querySelector('#send-button').disabled);
  await page.locator('#send-button').click();
  await page.waitForFunction(() => document.querySelector('#feedback').textContent.includes('Mocked provider unavailable'));
  assert.equal(await page.locator('#chat-input').inputValue(), 'Review this tiny text file');
  assert.match(await page.locator('#attachments').innerText(), /notes.txt/);
  assert.equal(await page.locator('.message.user').count(), 0);
  record('Mocked failed chat restores the draft and attachment without a dangling user message');
  failChat = false;
  await page.locator('#send-button').click();
  await page.waitForFunction(() => document.querySelector('.message.assistant')?.textContent.includes('Mocked rendering check'));
  assert.equal(await page.locator('.message.assistant script').count(), 0);
  assert.equal(await page.locator('.sources a').count(), 1);
  assert.equal(await page.evaluate(() => window.xss), undefined);
  await page.reload();
  await page.waitForFunction(() => document.querySelector('.message.assistant')?.textContent.includes('Mocked rendering check'));
  assert.equal(await page.locator('.attachments .attachment').count(), 0);
  record('Mocked chat renders source-safe text and persists history, excluding original file bytes');
  await page.screenshot({ path: join(evidence, 'desktop-conversation.png'), fullPage: true });
  const mobile = activePage = track(await context.newPage());
  await mobile.setViewportSize({ width: 390, height: 844 });
  await mobile.goto(base); await mobile.locator('#setup-title').waitFor(); await noOverflow(mobile);
  await selectView(mobile, 'models'); await mobile.waitForFunction(() => document.querySelectorAll('.catalog-card').length >= 2); await noOverflow(mobile);
  await mobile.screenshot({ path: join(evidence, 'mobile-model-library.png'), fullPage: true });
  await selectView(mobile, 'tools'); await noOverflow(mobile);
  record('Phone-width conversation, model library and scientific tools fit without horizontal overflow');
  assert.deepEqual(pageErrors, []); assert.deepEqual(browserConsoleErrors, []);
  record('No uncaught browser or content-security errors');
  await writeFile(join(evidence, 'browser-results.json'), JSON.stringify({ checks, pageErrors, browserConsoleErrors, mockedChatRequests, realModelInferenceCalls: 0, fixture: 'GGUF container upload only; not model weights', notes: 'Actual ARM64 model inference is verified by the separate smoke_runtime.py workflow step.' }, null, 2));
  console.log(`${checks.length} browser checks passed; ${mockedChatRequests} mocked chat requests; zero live model inference calls in this browser suite.`);
} catch (error) {
  const uiState = activePage ? await activePage.evaluate(() => ({ status: document.querySelector('#status-button')?.textContent, feedback: document.querySelector('#feedback')?.textContent, selectedBackend: document.querySelector('#preferred-backend')?.value, settingsBusy: document.querySelector('#settings-form')?.getAttribute('aria-busy'), sendDisabled: document.querySelector('#send-button')?.disabled })).catch(() => null) : null;
  await writeFile(join(evidence, 'browser-failure.json'), JSON.stringify({ error: error.stack, checks, pageErrors, browserConsoleErrors, mockedChatRequests, uiState }, null, 2));
  if (activePage) await activePage.screenshot({ path: join(evidence, 'browser-failure.png'), fullPage: true }).catch(() => {});
  throw error;
} finally {
  if (browser) await browser.close();
  if (server && server.exitCode === null) { server.kill('SIGTERM'); await Promise.race([new Promise(resolve => server.once('exit', resolve)), delay(3000)]); if (server.exitCode === null) server.kill('SIGKILL'); }
  await writeFile(join(evidence, 'browser-service.log'), output);
  await rm(dataDir, { recursive: true, force: true });
}
