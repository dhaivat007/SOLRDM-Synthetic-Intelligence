/** CI-only browser QA. Requires playwright@1.56.1 and its Chromium installation.
 * Run after `npm run build`. No model credential or live model calls are used.
 */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';
import { chromium } from 'playwright';

const root = resolve(fileURLToPath(new URL('..', import.meta.url)));
const evidence = resolve(root, 'evidence');
const base = 'http://127.0.0.1:8787';
const pageErrors = [];
const checks = [];
let server;
let browser;
let serverOutput = '';
let serverStartError;
let chatRequests = 0;
let mockedChatRequests = 0;
let activePage;

function record(name) { checks.push(name); console.log(`PASS ${name}`); }
function track(page, name) {
  page.setDefaultTimeout(30_000);
  page.setDefaultNavigationTimeout(30_000);
  page.on('pageerror', error => pageErrors.push(`${name}: ${error.message}`));
  page.on('request', request => { if (new URL(request.url()).pathname === '/api/chat') chatRequests++; });
  return page;
}
async function waitForServer() {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (serverStartError) throw serverStartError;
    if (server.exitCode !== null) throw new Error(`Preview server exited with ${server.exitCode}: ${serverOutput}`);
    try {
      const response = await fetch(base, { signal: AbortSignal.timeout(1000) });
      if (response.ok && (await response.text()).includes('SOLRDM')) return;
    } catch { /* Startup can take a moment; retry within the explicit deadline. */ }
    await delay(200);
  }
  throw new Error(`Preview server did not become ready within 30 seconds: ${serverOutput}`);
}
async function pendingSetup(page) {
  await page.waitForFunction(() => document.querySelector('#connection-badge')?.textContent.includes('Model setup pending'));
  assert.equal(await page.locator('#setup-notice').isVisible(), true, 'The missing model setup must be visible.');
}
async function noOverflow(page) {
  const dimensions = await page.evaluate(() => ({ width: window.innerWidth, document: document.documentElement.scrollWidth, body: document.body.scrollWidth }));
  assert.ok(dimensions.document <= dimensions.width + 1, `Document overflows horizontally: ${JSON.stringify(dimensions)}`);
  assert.ok(dimensions.body <= dimensions.width + 1, `Body overflows horizontally: ${JSON.stringify(dimensions)}`);
}
function pdfFixture() {
  // A complete one-page PDF with a valid xref table, not merely a fake extension.
  const stream = 'BT /F1 12 Tf 72 720 Td (SOLRDM browser test document) Tj ET';
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    `<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}\nendstream`,
  ];
  let text = '%PDF-1.4\n';
  const offsets = [0];
  objects.forEach((body, i) => { offsets.push(Buffer.byteLength(text)); text += `${i + 1} 0 obj\n${body}\nendobj\n`; });
  const xref = Buffer.byteLength(text);
  text += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  text += offsets.slice(1).map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('');
  text += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(text);
}

try {
  await mkdir(evidence, { recursive: true });
  // A CI secret must never accidentally enable a billable model call during QA.
  server = spawn(process.execPath, ['scripts/serve.mjs'], {
    cwd: root, env: { ...process.env, PORT: '8787', OPENAI_API_KEY: '', OPENAI_MODEL: '' }, stdio: ['ignore', 'pipe', 'pipe'],
  });
  server.on('error', error => { serverStartError = error; });
  const capture = chunk => { serverOutput = (serverOutput + chunk.toString()).slice(-12_000); };
  server.stdout.on('data', capture); server.stderr.on('data', capture);
  await waitForServer();
  browser = await chromium.launch({ headless: true });
  const desktopContext = await browser.newContext({ viewport: { width: 1440, height: 1040 }, acceptDownloads: true });
  const page = track(await desktopContext.newPage(), 'desktop'); activePage = page;
  const statusResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/status');
  await page.goto(base, { waitUntil: 'networkidle' });
  const status = await (await statusResponse).json();
  assert.equal(status.modelConfigured, false);
  assert.ok(status.limitations.some(value => value.includes('Python engine')));
  await pendingSetup(page);
  await noOverflow(page);
  const screenshotPng = await page.screenshot({ path: resolve(evidence, 'web-desktop.png'), fullPage: true });
  record('Desktop loads with honest model-setup and engine limitations');

  await page.locator('#message-input').fill('Hello, can you review my research?');
  await page.locator('#send-button').click();
  await page.waitForFunction(() => document.querySelector('#feedback')?.textContent.includes('needs a model connection'));
  assert.equal(await page.locator('#messages .message').count(), 0, 'No invented assistant response or completed chat should appear.');
  assert.equal(await page.locator('#message-input').inputValue(), 'Hello, can you review my research?');
  assert.equal(chatRequests, 0);
  record('Missing model blocks chat visibly, retains draft and produces no canned reply');

  await page.locator('#nav-workbench').click();
  await page.locator('#workbench-dialog').waitFor({ state: 'visible' });
  await page.locator('#tool-select').selectOption('simulate_projectile');
  await page.locator('#tool-speed').fill('10');
  await page.locator('#tool-angle').fill('45');
  await page.locator('#tool-gravity').fill('10');
  const toolResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/tools' && response.request().method() === 'POST');
  await page.locator('#run-tool').click();
  const response = await toolResponse;
  assert.equal(response.status(), 200);
  const receipt = await response.json();
  assert.equal(receipt.tool, 'simulate_projectile');
  assert.equal(receipt.status, 'completed');
  assert.ok(Math.abs(receipt.data.range - 10) < 1e-9);
  assert.ok(Math.abs(receipt.data.maxHeight - 2.5) < 1e-9);
  assert.equal(receipt.data.points.length, 200);
  await page.locator('#tool-result .result-chart').waitFor({ state: 'visible' });
  assert.equal(await page.locator('#tool-result .result-chart path').count(), 2);
  assert.ok((await page.locator('#tool-result .result-chart path').last().getAttribute('d')).includes('L'));
  assert.ok((await page.locator('#tool-result .receipt-summary').innerText()).includes('range 10 m'));
  assert.ok((await page.locator('#tool-result').innerText()).includes('air resistance'));
  await page.screenshot({ path: resolve(evidence, 'web-workbench.png'), fullPage: true });
  await page.locator('#save-tool-result').click();
  await page.locator('#workbench-dialog').waitFor({ state: 'hidden' });
  assert.equal(await page.locator('#messages .message.assistant').count(), 1);
  assert.equal(await page.locator('#messages .result-chart').count(), 1);
  await page.locator('#rename-chat').click();
  await page.locator('#title-input').fill('Projectile verification');
  await page.locator('#rename-form').getByRole('button', { name: 'Save title', exact: true }).click();
  record('Workbench executes real projectile API, charts 200 points and saves its receipt');

  await page.reload({ waitUntil: 'networkidle' });
  await pendingSetup(page);
  assert.ok((await page.locator('#rename-chat').innerText()).includes('Projectile verification'));
  assert.equal(await page.locator('#messages .message.assistant').count(), 1);
  assert.equal(await page.locator('#messages .result-chart').count(), 1);
  const stored = await page.evaluate(() => JSON.parse(localStorage.getItem('solrdm.conversations.v1')));
  const saved = stored.conversations.find(item => item.id === stored.currentId);
  assert.equal(saved.messages[0].receipts[0].data.range, receipt.data.range);
  record('Conversation title and actual scientific result survive reload');

  await page.locator('#export-button').click();
  const downloadEvent = page.waitForEvent('download');
  await page.locator('#export-json').click();
  const download = await downloadEvent;
  assert.equal(await download.failure(), null);
  assert.ok(download.suggestedFilename().endsWith('.json'));
  const exportedPath = resolve(evidence, 'conversation-export.json');
  await download.saveAs(exportedPath);
  const exported = JSON.parse(await readFile(exportedPath, 'utf8'));
  assert.equal(exported.attachmentFilesIncluded, false);
  assert.equal(exported.conversation.title, 'Projectile verification');
  assert.equal(exported.conversation.messages[0].receipts[0].status, 'completed');
  assert.equal(exported.conversation.messages[0].receipts[0].data.range, receipt.data.range);
  record('Downloaded JSON export contains the verified tool receipt');

  await page.locator('#new-chat').click();
  assert.equal(await page.locator('#messages .message').count(), 0);
  assert.equal(await page.locator('#welcome').isVisible(), true);
  for (const mode of ['research', 'review', 'plan', 'chat']) {
    await page.locator(`.mode-button[data-mode="${mode}"]`).click();
    assert.equal(await page.locator(`.mode-button[data-mode="${mode}"]`).getAttribute('aria-pressed'), 'true');
    assert.equal(await page.locator('.mode-button[aria-pressed="true"]').count(), 1);
  }
  await page.locator('.mode-button[data-mode="review"]').click();
  await page.reload({ waitUntil: 'networkidle' });
  await pendingSetup(page);
  assert.equal(await page.locator('.mode-button[data-mode="review"]').getAttribute('aria-pressed'), 'true');
  assert.equal(await page.locator('#conversation-list .history-item').count(), 2);
  record('New conversation and all modes work; selected mode persists');

  await page.locator('#file-input').setInputFiles([
    { name: 'observations.txt', mimeType: 'text/plain', buffer: Buffer.from('Experiment notes\nObserved distances: 1, 2, 3 metres.\n') },
    { name: 'workspace.png', mimeType: 'image/png', buffer: screenshotPng },
    { name: 'research-note.pdf', mimeType: 'application/pdf', buffer: pdfFixture() },
  ]);
  await page.waitForFunction(() => document.querySelectorAll('#attachments .attachment').length === 3 && !document.querySelector('#file-input').disabled);
  const attachments = await page.locator('#attachments').innerText();
  for (const name of ['observations.txt', 'workspace.png', 'research-note.pdf']) assert.ok(attachments.includes(name));
  assert.ok(attachments.includes('resized to at most 1600 px'));
  assert.ok(attachments.includes('model review required'));
  assert.equal(await page.locator('#feedback').isVisible(), false, 'Valid attachments should prepare without an error.');
  await page.locator('#message-input').fill('Review these three attachments.');
  await page.locator('#send-button').click();
  await page.waitForFunction(() => document.querySelector('#feedback')?.textContent.includes('needs a model connection'));
  assert.equal(await page.locator('#attachments .attachment').count(), 3, 'Unsent attachments must remain available.');
  assert.equal(await page.locator('#messages .message').count(), 0, 'Upload preparation is not model understanding.');
  assert.equal(chatRequests, 0);
  const localData = await page.evaluate(() => localStorage.getItem('solrdm.conversations.v1'));
  assert.ok(!localData.includes('data:image/'));
  assert.ok(!localData.includes('Observed distances'));
  await page.getByRole('button', { name: 'Remove workspace.png', exact: true }).click();
  assert.equal(await page.locator('#attachments .attachment').count(), 2);
  record('TXT, real PNG and valid PDF prepare locally; pending model retains files without claiming analysis');

  // Explicit UI fixtures only: intercept both status and chat in this browser.
  // The preview server still has no model credential, and no model provider is called.
  const mockedPayloads = [];
  const mockText = 'Mocked UI response: the existing projectile calculation is shown below. This fixture is incomplete and does not verify model reasoning or file understanding.';
  await page.route(`${base}/api/status`, route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ ...status, modelConfigured: true, model: 'explicit-browser-test-fixture' }),
  }));
  await page.route(`${base}/api/chat`, async route => {
    mockedChatRequests++;
    mockedPayloads.push(route.request().postDataJSON());
    await route.fulfill(mockedChatRequests === 1 ? {
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ text: mockText, incomplete: true, receipts: [receipt], citations: [], model: 'explicit-browser-test-fixture' }),
    } : {
      status: 503, contentType: 'application/json',
      body: JSON.stringify({ error: 'Mocked model outage for UI testing.', code: 'MOCK_MODEL_UNAVAILABLE' }),
    });
  });
  await page.locator('#settings-button').click();
  await page.locator('#refresh-status').click();
  await page.waitForFunction(() => document.querySelector('#connection-badge')?.textContent.includes('Model configured'));
  await page.locator('#settings-dialog').getByRole('button', { name: 'Done', exact: true }).click();
  assert.equal(await page.locator('#attachments .attachment').count(), 2, 'Checking setup must retain prepared files.');
  const mockPrompt = 'Review these two attachments. This is a UI fixture test.';
  await page.locator('#message-input').fill(mockPrompt);
  await page.locator('#send-button').click();
  await page.waitForFunction(() => document.querySelector('#messages .message.assistant')?.textContent.includes('Mocked UI response:'));
  assert.equal(mockedChatRequests, 1);
  assert.equal(mockedPayloads[0].mode, 'review');
  assert.equal(mockedPayloads[0].text, mockPrompt);
  assert.deepEqual(mockedPayloads[0].messages, []);
  assert.deepEqual(mockedPayloads[0].attachments.map(file => file.name), ['observations.txt', 'research-note.pdf']);
  assert.equal(mockedPayloads[0].attachments[0].kind, 'text');
  assert.ok(mockedPayloads[0].attachments[0].text.includes('Observed distances: 1, 2, 3 metres.'));
  assert.equal(mockedPayloads[0].attachments[1].kind, 'pdf');
  assert.ok(mockedPayloads[0].attachments[1].dataUrl.startsWith('data:application/pdf;base64,'));
  mockedPayloads[0].attachments.forEach(file => assert.match(file.sha256, /^[a-f0-9]{64}$/));
  assert.equal(await page.locator('#messages .message').count(), 2);
  assert.equal(await page.locator('#messages .incomplete-badge').innerText(), 'Incomplete');
  assert.equal(await page.locator('#messages .message-file').count(), 2);
  assert.equal(await page.locator('#messages .result-chart').count(), 1);
  assert.equal(await page.locator('#attachments .attachment').count(), 0);
  const mockStored = await page.evaluate(() => JSON.parse(localStorage.getItem('solrdm.conversations.v1')));
  const mockConversation = mockStored.conversations.find(item => item.id === mockStored.currentId);
  assert.equal(mockConversation.messages[1].content, mockText);
  assert.equal(mockConversation.messages[1].incomplete, true);
  assert.equal(mockConversation.messages[1].receipts[0].data.range, receipt.data.range);
  mockConversation.messages[0].attachments.forEach(file => {
    assert.deepEqual(Object.keys(file).sort(), ['description', 'kind', 'name', 'sha256']);
    assert.equal(Object.hasOwn(file, 'text'), false);
    assert.equal(Object.hasOwn(file, 'dataUrl'), false);
  });
  assert.ok(!JSON.stringify(mockStored).includes('Observed distances:'));
  assert.ok(!JSON.stringify(mockStored).includes('data:application/pdf;base64,'));
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForFunction(() => document.querySelector('#connection-badge')?.textContent.includes('Model configured'));
  assert.ok((await page.locator('#messages .message.assistant').innerText()).includes(mockText));
  assert.equal(await page.locator('#messages .incomplete-badge').innerText(), 'Incomplete');
  assert.equal(await page.locator('#messages .message-file').count(), 2);
  assert.equal(await page.locator('#messages .result-chart').count(), 1);
  await page.screenshot({ path: resolve(evidence, 'web-mocked-conversation.png'), fullPage: true });
  record('Explicit mocked chat renders and persists incomplete response, real prior receipt and attachment metadata without file bytes');

  const retryPrompt = 'Please review my draft again.';
  const retryBytes = 'Retry-only attachment content; do not retain this in saved history.';
  await page.locator('#file-input').setInputFiles({ name: 'retry-notes.txt', mimeType: 'text/plain', buffer: Buffer.from(retryBytes) });
  await page.waitForFunction(() => document.querySelectorAll('#attachments .attachment').length === 1 && !document.querySelector('#file-input').disabled);
  await page.locator('#message-input').fill(retryPrompt);
  await page.locator('#send-button').click();
  await page.waitForFunction(() => document.querySelector('#feedback')?.textContent.includes('Mocked model outage for UI testing.'));
  assert.equal(mockedChatRequests, 2);
  assert.equal(mockedPayloads[1].text, retryPrompt);
  assert.equal(mockedPayloads[1].attachments[0].text, retryBytes);
  assert.equal(mockedPayloads[1].messages.length, 2);
  assert.ok(mockedPayloads[1].messages[0].content.includes('File content is not included in this follow-up'));
  assert.ok(!mockedPayloads[1].messages[0].content.includes('Observed distances:'));
  assert.equal(await page.locator('#message-input').inputValue(), retryPrompt);
  assert.equal(await page.locator('#attachments .attachment').count(), 1);
  assert.ok((await page.locator('#attachments').innerText()).includes('retry-notes.txt'));
  assert.ok((await page.locator('#feedback').innerText()).includes('kept for retry'));
  assert.equal(await page.locator('#messages .message').count(), 2, 'A failed request must not add a completed message or duplicate the user draft.');
  assert.equal(await page.locator('#messages .incomplete-badge').count(), 1);
  const afterFailure = await page.evaluate(() => localStorage.getItem('solrdm.conversations.v1'));
  assert.ok(!afterFailure.includes(retryBytes));
  assert.ok(!afterFailure.includes(retryPrompt));
  record('Explicit mocked chat failure retains retry text and files without inventing completion or persisting attachment bytes');

  // A separate phone browser has its own local history, as the UI explicitly states.
  const mobileContext = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1, isMobile: true, hasTouch: true });
  const mobile = track(await mobileContext.newPage(), 'mobile'); activePage = mobile;
  await mobile.goto(base, { waitUntil: 'networkidle' });
  await pendingSetup(mobile);
  assert.equal(await mobile.locator('#messages .message').count(), 0);
  await noOverflow(mobile);
  await mobile.screenshot({ path: resolve(evidence, 'web-mobile.png'), fullPage: true });
  await mobile.locator('#menu-button').click();
  assert.equal(await mobile.locator('#menu-button').getAttribute('aria-expanded'), 'true');
  await mobile.locator('#nav-workbench').click();
  await mobile.locator('#workbench-dialog').waitFor({ state: 'visible' });
  await mobile.locator('#tool-select').selectOption('describe_statistics');
  await mobile.locator('#tool-numbers').fill('1, 2, 3');
  const mobileResponse = mobile.waitForResponse(res => new URL(res.url()).pathname === '/api/tools' && res.request().method() === 'POST');
  await mobile.locator('#run-tool').click();
  const mobileReceipt = await (await mobileResponse).json();
  assert.equal(mobileReceipt.status, 'completed');
  assert.equal(mobileReceipt.data.mean, 2);
  await mobile.waitForFunction(() => document.querySelector('#tool-status')?.textContent === 'Result recorded.');
  await noOverflow(mobile);
  await mobile.screenshot({ path: resolve(evidence, 'web-mobile-workbench.png'), fullPage: true });
  await mobile.locator('#save-tool-result').click();
  await mobile.locator('#workbench-dialog').waitFor({ state: 'hidden' });
  assert.equal(await mobile.locator('#messages .receipt').count(), 1);
  await noOverflow(mobile);
  record('Phone navigation, workbench, result saving and layout work without horizontal overflow');

  assert.deepEqual(pageErrors, [], 'Browser JavaScript page errors are not permitted.');
  assert.equal(mockedChatRequests, 2);
  assert.equal(chatRequests, mockedChatRequests, 'Every browser chat request must be intercepted by an explicit UI fixture.');
  await writeFile(resolve(evidence, 'browser-smoke.json'), JSON.stringify({
    status: 'passed', browser: 'Chromium via Playwright', checks, pageErrors,
    modelVerified: false, modelRequests: 0, mockedChatRequests, unmockedChatRequests: chatRequests - mockedChatRequests, mockedChatUiVerified: true, liveResearchVerified: false,
    filePreparationVerified: ['TXT', 'PNG', 'PDF'], videoPreparationVerified: false,
    limitations: ['Local preview supplies a development identity; production Sites authentication is not verified.', 'Chat success and failure use explicitly mocked browser responses; no model provider call, model file understanding or live Crossref search was tested.', 'Video extraction is not covered by this browser run.'],
  }, null, 2) + '\n');
  console.log(`Browser smoke passed (${checks.length} checks). Model execution and video understanding were not tested.`);
} catch (error) {
  if (activePage && !activePage.isClosed()) await activePage.screenshot({ path: resolve(evidence, 'browser-failure.png'), fullPage: true }).catch(() => {});
  await writeFile(resolve(evidence, 'browser-smoke.json'), JSON.stringify({ status: 'failed', checks, error: error.message, pageErrors, modelVerified: false, modelRequests: 0, mockedChatRequests, unmockedChatRequests: chatRequests - mockedChatRequests }, null, 2) + '\n').catch(() => {});
  throw error;
} finally {
  if (browser) await browser.close().catch(() => {});
  if (server && server.exitCode === null) {
    server.kill('SIGTERM');
    const stopped = await Promise.race([new Promise(resolveStop => server.once('exit', () => resolveStop(true))), delay(3000).then(() => false)]);
    if (!stopped && server.exitCode === null) server.kill('SIGKILL');
  }
}
