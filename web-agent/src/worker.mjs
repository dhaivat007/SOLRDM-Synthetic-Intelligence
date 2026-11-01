import { runAgent } from './model.mjs';
import { executeTool, TOOL_DEFINITIONS } from './tools.mjs';
import { UI_HTML, UI_CSS, UI_JS } from './ui.mjs';

const MAX_BODY = 24 * 1024 * 1024;
const SECURITY_HEADERS = {
  'x-content-type-options': 'nosniff',
  'referrer-policy': 'same-origin',
  'cache-control': 'no-store',
  'content-security-policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'",
};

function json(value, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { ...SECURITY_HEADERS, 'content-type': 'application/json; charset=utf-8' } });
}

async function readJSON(request) {
  if (!request.headers.get('content-type')?.toLowerCase().startsWith('application/json')) {
    throw Object.assign(new Error('Send application/json.'), { status: 415 });
  }
  if (Number(request.headers.get('content-length')) > MAX_BODY) {
    throw Object.assign(new Error('This request is too large. Remove an attachment.'), { status: 413 });
  }
  if (!request.body) throw Object.assign(new Error('The request is empty.'), { status: 400 });
  const reader = request.body.getReader();
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_BODY) {
        await reader.cancel();
        throw Object.assign(new Error('This request is too large. Remove an attachment.'), { status: 413 });
      }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try {
    const parsed = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error();
    return parsed;
  } catch { throw Object.assign(new Error('The request must be a JSON object.'), { status: 400 }); }
}

export function createHandler({ fetchImpl = globalThis.fetch } = {}) {
  return async function handle(request, env = {}) {
    const url = new URL(request.url);
    const isApi = url.pathname.startsWith('/api/');
    if (isApi) {
      // Sites authenticates visitors before forwarding this trusted header.
      if (!request.headers.get('oai-authenticated-user-id')) {
        return json({ error: 'Sign in to use your SOLRDM workspace.', code: 'SIGN_IN_REQUIRED' }, 401);
      }
      const origin = request.headers.get('origin');
      if (origin && origin !== url.origin) return json({ error: 'Use the app from its own address.', code: 'ORIGIN_MISMATCH' }, 403);
    }
    if (request.method === 'GET') {
      const assets = { '/': [UI_HTML, 'text/html'], '/style.css': [UI_CSS, 'text/css'], '/app.js': [UI_JS, 'text/javascript'] };
      if (assets[url.pathname]) {
        const [body, type] = assets[url.pathname];
        return new Response(body, { headers: { ...SECURITY_HEADERS, 'content-type': type + '; charset=utf-8' } });
      }
      if (url.pathname === '/api/status') return json({
        modelConfigured: Boolean(env.OPENAI_API_KEY),
        model: env.OPENAI_MODEL || 'gpt-4.1',
        tools: TOOL_DEFINITIONS.map(t => t.name),
        limitations: [
          'Model responses require a configured OpenAI API key and available API credit.',
          'Conversation history is saved in this browser only; it does not sync across devices.',
          'Video analysis uses up to six still frames and omits audio.',
          'Research search returns Crossref metadata and available abstracts, not verified full-text findings.',
          'Scientific tools are bounded mathematical models, not validated predictions of real systems.',
          'The original SOLRDM v0.7 Python engine is not executing inside this web app.',
          'The agent can select available tools; it cannot send messages, spend money, or control external accounts.',
        ],
      });
      return json({ error: 'Not found.' }, 404);
    }
    if (request.method !== 'POST') return json({ error: 'Method not allowed.' }, 405);
    if (!['/api/chat', '/api/tools'].includes(url.pathname)) return json({ error: 'Not found.' }, 404);
    try {
      const payload = await readJSON(request);
      const signal = AbortSignal.any([request.signal, AbortSignal.timeout(url.pathname === '/api/tools' ? 20000 : 120000)]);
      if (url.pathname === '/api/tools') {
        if (!TOOL_DEFINITIONS.some(t => t.name === payload.name)) return json({ error: 'Choose one of the available tools.' }, 400);
        try { return json(await executeTool(payload.name, payload.args, { fetchImpl, signal })); }
        catch (error) {
          if (error instanceof TypeError || error instanceof ReferenceError) throw error;
          throw Object.assign(error, { status: 400, code: 'TOOL_FAILED' });
        }
      }
      if (!env.OPENAI_API_KEY) return json({
        error: 'The conversation model is not connected yet. Research search and scientific tools are available in the workbench.',
        code: 'MODEL_NOT_CONFIGURED',
      }, 503);
      const result = await runAgent(payload, {
        apiKey: env.OPENAI_API_KEY,
        model: env.OPENAI_MODEL || 'gpt-4.1',
        fetchImpl, signal, executeTool: (name, args, opts = {}) => executeTool(name, args, { ...opts, fetchImpl, signal }),
        toolDefinitions: TOOL_DEFINITIONS,
      });
      return json(result);
    } catch (error) {
      if (request.signal.aborted || error?.name === 'AbortError' || error?.name === 'TimeoutError') {
        return json({ error: 'The request stopped or timed out. No completion was confirmed.', code: 'REQUEST_STOPPED' }, 408);
      }
      // Errors from the model layer are sanitized there; never echo unexpected internals.
      const known = Number.isInteger(error?.status) && error.status >= 400 && error.status <= 599;
      const status = known ? error.status : 500;
      const message = known && error instanceof Error ? error.message : 'The request could not be completed. Please try again.';
      const safeMessage = message.includes(env.OPENAI_API_KEY || '\u0000') ? 'The request could not be completed.' : message.slice(0, 350);
      return json({ error: safeMessage, code: error?.code || 'REQUEST_FAILED' }, status);
    }
  };
}

export default { fetch: createHandler() };
