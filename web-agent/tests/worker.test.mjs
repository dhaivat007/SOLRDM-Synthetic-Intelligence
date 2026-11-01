import test from 'node:test';
import assert from 'node:assert/strict';
import { createHandler } from '../src/worker.mjs';

const request = (path, payload, headers = {}) => new Request('https://solrdm.example' + path, {
  method: payload === undefined ? 'GET' : 'POST',
  headers: { 'oai-authenticated-user-id': 'test-owner', ...(payload === undefined ? {} : { 'content-type': 'application/json' }), ...headers },
  ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
});

test('private APIs require platform identity', async () => {
  const res = await createHandler()(new Request('https://solrdm.example/api/status'));
  assert.equal(res.status, 401);
});

test('cross-origin API requests are refused before execution', async () => {
  const res = await createHandler()(request('/api/tools', { name: 'describe_statistics', args: { numbers: [1, 2] } }, { origin: 'https://other.example' }));
  assert.equal(res.status, 403);
});

test('model configuration state is honest and never returns the secret', async () => {
  const handler = createHandler();
  const absent = await (await handler(request('/api/status'))).json();
  assert.equal(absent.modelConfigured, false);
  assert.match(absent.limitations.join(' '), /Python engine is not executing/);
  const present = await handler(request('/api/status'), { OPENAI_API_KEY: 'private-test-value' });
  const body = await present.text();
  assert.equal(JSON.parse(body).modelConfigured, true);
  assert.equal(body.includes('private-test-value'), false);
});

test('unconfigured chat does not fabricate an assistant reply or call network', async () => {
  const handler = createHandler({ fetchImpl: () => { throw new Error('must not fetch'); } });
  const res = await handler(request('/api/chat', { text: 'hello', messages: [], attachments: [], mode: 'chat' }));
  assert.equal(res.status, 503);
  assert.equal((await res.json()).code, 'MODEL_NOT_CONFIGURED');
});

test('scientific tools work through the authenticated API without a model key', async () => {
  const res = await createHandler()(request('/api/tools', { name: 'simulate_projectile', args: { speed: 10, angle: 45, gravity: 10 } }));
  assert.equal(res.status, 200);
  const result = await res.json();
  assert.equal(result.status, 'completed');
  assert.ok(Math.abs(result.data.range - 10) < 1e-9);
  assert.equal(result.data.points.length, 200);
});

test('tool errors are visible and never become completed receipts', async () => {
  const res = await createHandler()(request('/api/tools', { name: 'simulate_projectile', args: { speed: 10, angle: 45, gravity: 0 } }));
  assert.equal(res.status, 400);
  const body = await res.json();
  assert.match(body.error, /gravity/);
  assert.equal(body.status, undefined);
});

test('unknown tools, invalid JSON and oversized declared bodies fail', async () => {
  const handler = createHandler();
  assert.equal((await handler(request('/api/tools', { name: 'run_shell', args: {} }))).status, 400);
  assert.equal((await handler(new Request('https://solrdm.example/api/tools', { method: 'POST', headers: { 'oai-authenticated-user-id': 'test', 'content-type': 'application/json' }, body: '{broken' }))).status, 400);
  assert.equal((await handler(request('/api/tools', {}, { 'content-length': String(25 * 1024 * 1024) }))).status, 413);
  assert.equal((await handler(request('/api/tools', {}, { 'content-type': 'text/plain' }))).status, 415);
});

test('assets use explicit MIME types and content security policy', async () => {
  for (const [path, type] of [['/', 'text/html'], ['/app.js', 'text/javascript'], ['/style.css', 'text/css']]) {
    const res = await createHandler()(request(path));
    assert.equal(res.status, 200);
    assert.ok(res.headers.get('content-type').startsWith(type));
    assert.match(res.headers.get('content-security-policy'), /script-src 'self'/);
    assert.ok((await res.text()).length > 100);
  }
});

test('unsupported methods and routes have explicit errors', async () => {
  const handler = createHandler();
  assert.equal((await handler(request('/missing'))).status, 404);
  assert.equal((await handler(new Request('https://solrdm.example/', { method: 'DELETE' }))).status, 405);
});
