/** Package the verified web workspace into offline Android assets. No secrets or model client. */
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { resolve, dirname, isAbsolute } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
if (args.length && (args.length !== 2 || args[0] !== '--output-dir' || !isAbsolute(args[1]))) {
  throw new Error('Usage: node scripts/package-agent-assets.mjs [--output-dir /absolute/directory]');
}
const output = args.length ? args[1] : resolve(root, 'app/src/main/assets/agent');
const read = name => readFile(resolve(root, 'web-agent', name), 'utf8');
let [html, css, app, tools] = await Promise.all([
  read('web/index.html'), read('web/style.css'), read('web/app.js'), read('src/tools.mjs'),
]);

function replaceOnce(source, before, after) {
  if (!source.includes(before) || source.indexOf(before) !== source.lastIndexOf(before)) {
    throw new Error('Android packaging source contract changed: ' + before.slice(0, 70));
  }
  return source.replace(before, after);
}

html = replaceOnce(html, '<script src="/app.js" defer></script>', '<script src="/android-adapter.js" defer></script>\n  <script src="/app.js" defer></script>');
html = replaceOnce(html, 'href="/" aria-label="SOLRDM home"', 'href="/index.html" aria-label="SOLRDM home"');
html = html.replaceAll('Saved in this browser', 'Saved in this app')
  .replaceAll('Personal · Private Site', 'Personal · Android app')
  .replace('Research and scientific tools are ready to use in the workbench.', 'Scientific tools work offline. AI chat is not connected yet.')
  .replace('Conversation history stays in this browser and does not sync between devices. Sending a message sends its text, recent conversation context and selected files to the configured model provider. Attachment bytes are not retained after sending. Attach a file again when asking for a fresh review or details not captured in the previous response. Use Export to keep a copy of your conversation.', 'Conversation history is stored privately in this app and does not sync between devices. This APK has no configured conversation model or API key, so files and chat messages are not sent to a model. Selected file bytes are temporary; attach a file again for a new review. Use Export to save text and tool results through the Android file picker. Research searches contact Crossref when you run that tool.')
  .replace('This web app is a separate assistant interface. It does not run the complete SOLRDM v0.7 Python engine or claim general intelligence.', 'The sixteen SOLRDM v0.7 Python modules are bundled separately and available through the Python engine screen. These chat controls are not a full integration of those modules and do not claim general intelligence.')
  .replaceAll('Download this conversation', 'Save this conversation')
  .replaceAll('Download Markdown', 'Save Markdown')
  .replaceAll('Download JSON', 'Save JSON');

app = app.replaceAll('SOLRDM Web', 'SOLRDM Agent Android')
  .replaceAll('Browser storage is full or unavailable.', 'App storage is full or unavailable.')
  .replaceAll('in this browser', 'in this app')
  .replaceAll('from this browser', 'from this app')
  .replace('Sign in to this private Site, then try again.', 'This app operation is unavailable. Try again.');
app = replaceOnce(app,
  'Model setup is pending. Configure OPENAI_API_KEY securely in the Site’s server environment to enable conversation and file understanding. The key is never entered or stored in this app.',
  'AI chat and file understanding are not connected in this APK. A secure model backend is still required; no API key is bundled or requested here. Scientific tools and the separate Python engine work offline.');
app = replaceOnce(app, 'const text = await file.text(); if (text.includes', 'const text = await file.text(); if (text.length > 200000) throw new Error(`${name}: text files must contain at most 200,000 characters.`); if (text.includes');
const downloadLine = app.split('\n').find(line => line.includes('const url = URL.createObjectURL(new Blob([content]'));
if (!downloadLine) throw new Error('Conversation export source contract changed.');
app = replaceOnce(app, downloadLine, String.raw`    const filename = (c.title.replace(/[^a-z0-9_-]/gi, '-').slice(0, 50) || 'solrdm-conversation') + (format === 'json' ? '.json' : '.md');
    if (new TextEncoder().encode(content).byteLength > 2 * 1024 * 1024) { feedback('This export exceeds 2 MB. Export a shorter conversation.'); return; }
    if (!window.SolrdmAndroid || typeof window.SolrdmAndroid.saveExport !== 'function') { feedback('Android file saving is unavailable. The export was not saved.'); return; }
    try { window.SolrdmAndroid.saveExport(filename, mime, content); $('export-dialog').close(); feedback('Choose where to save this export.'); }
    catch { feedback('Android could not open the save picker. The export was not saved.'); }`);

const cleanTools = tools.replace(/^export\s+(?=(?:async\s+)?(?:function|const|let|class)\b)/gm, '');
if (/^import\s|^export\s/m.test(cleanTools)) throw new Error('Unexpected module declaration in scientific tools.');
const adapter = `'use strict';\n(() => {\nconst { executeTool, TOOL_DEFINITIONS } = (() => {\n${cleanTools}\nreturn { executeTool, TOOL_DEFINITIONS };\n})();\n` + String.raw`
  const LOCAL_ORIGIN = 'https://appassets.androidplatform.net';
  const nativeFetch = window.fetch.bind(window);
  const knownTools = new Set(TOOL_DEFINITIONS.map(item => item.name));
  const reply = (value, status = 200) => new Response(JSON.stringify(value), {
    status, headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' },
  });
  const stopped = signal => {
    if (signal && signal.aborted) throw new DOMException('Request stopped.', 'AbortError');
  };
  async function researchFetch(input, options = {}) {
    stopped(options.signal);
    const url = new URL(typeof input === 'string' ? input : input.url, LOCAL_ORIGIN);
    if (url.origin !== 'https://api.crossref.org' || url.pathname !== '/works' || url.username || url.password || (options.method && options.method !== 'GET')) {
      throw new Error('Only the Crossref research search can use the network in this APK.');
    }
    return nativeFetch(url.href, {
      method: 'GET', mode: 'cors', credentials: 'omit', redirect: 'error', referrerPolicy: 'no-referrer',
      headers: { Accept: 'application/json' }, signal: options.signal,
    });
  }
  window.fetch = async (input, options = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url, LOCAL_ORIGIN);
    const method = String(options.method || (typeof input === 'object' && input.method) || 'GET').toUpperCase();
    const signal = options.signal || (typeof input === 'object' ? input.signal : undefined);
    stopped(signal);
    if (url.origin !== LOCAL_ORIGIN) return researchFetch(input, { ...options, method, signal });
    if (url.username || url.password || url.search || url.hash) return reply({ error: 'Unsupported app request.' }, 400);
    if (url.pathname === '/api/status' && method === 'GET') return reply({
      modelConfigured: false, model: null, runtime: 'android-local', tools: [...knownTools],
      limitations: [
        'No conversation model, API key or hosted model backend is configured in this APK. Live chat and file understanding are unavailable.',
        'Projectile motion, damped oscillation, statistics and weighted comparisons run locally without network access.',
        'Crossref metadata search requires internet access; full papers are not read and live research access is not guaranteed.',
        'Video preparation samples up to six still frames and omits audio. Preparation is not proof of model understanding.',
        'History is private to this Android app and does not sync between devices. Attachment bytes are not retained with saved history.',
        'The sixteen v0.7 Python modules are available on the separate Python engine screen, not integrated into model-controlled chat.',
      ],
    });
    if (url.pathname === '/api/chat' && method === 'POST') return reply({
      error: 'AI chat and file understanding are not connected in this APK. Use the scientific workbench or the Python engine for the available offline tools.',
      code: 'MODEL_NOT_CONFIGURED',
    }, 503);
    if (url.pathname !== '/api/tools') return reply({ error: 'Unknown app operation.' }, 404);
    if (method !== 'POST') return reply({ error: 'Use POST for a scientific tool.' }, 405);
    if (typeof options.body !== 'string' || options.body.length > 200000) return reply({ error: 'Tool inputs must be bounded JSON text.' }, 400);
    let payload;
    try { payload = JSON.parse(options.body); }
    catch { return reply({ error: 'Tool inputs must be valid JSON.' }, 400); }
    if (!payload || typeof payload !== 'object' || Array.isArray(payload) || !knownTools.has(payload.name)) {
      return reply({ error: 'Choose one of the available scientific tools.' }, 400);
    }
    try {
      const result = await executeTool(payload.name, payload.args, { fetchImpl: researchFetch, signal });
      stopped(signal);
      return reply(result);
    } catch (error) {
      stopped(signal);
      return reply({ error: error instanceof Error ? error.message.slice(0, 350) : 'The tool could not complete this request.', code: 'TOOL_FAILED' }, 400);
    }
  };
  window.__solrdmExportResult = (success, message) => {
    const target = document.getElementById('feedback');
    if (!target) return;
    target.textContent = typeof message === 'string' ? message.slice(0, 350) : (success ? 'Export saved.' : 'Export was not saved.');
    target.hidden = false;
    target.classList.toggle('success', success === true);
  };
  document.addEventListener('DOMContentLoaded', () => {
    const workbench = document.getElementById('nav-workbench');
    if (!workbench) return;
    const button = document.createElement('button');
    button.id = 'native-engine-button'; button.type = 'button'; button.className = 'nav-item';
    button.textContent = '◈ Python engine · v0.7';
    button.addEventListener('click', () => {
      if (!window.SolrdmAndroid || typeof window.SolrdmAndroid.openEngine !== 'function') {
        window.__solrdmExportResult(false, 'The native Python engine screen is unavailable.'); return;
      }
      window.SolrdmAndroid.openEngine();
    });
    workbench.insertAdjacentElement('afterend', button);
  });
})();
`;

await mkdir(output, { recursive: true });
await Promise.all([
  writeFile(resolve(output, 'index.html'), html), writeFile(resolve(output, 'style.css'), css),
  writeFile(resolve(output, 'app.js'), app), writeFile(resolve(output, 'android-adapter.js'), adapter),
]);
console.log(`Packaged Android agent assets in ${output}; model connection explicitly pending.`);
