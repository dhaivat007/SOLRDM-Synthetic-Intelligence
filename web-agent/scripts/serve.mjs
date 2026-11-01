import http from 'node:http';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { Readable } from 'node:stream';

const worker = (await import(pathToFileURL(resolve('dist/server/index.js')).href)).default;
const port = Number(process.env.PORT || 8787);
const server = http.createServer(async (req, res) => {
  const abort = new AbortController();
  res.on('close', () => { if (!res.writableEnded) abort.abort(); });
  try {
    const origin = `http://127.0.0.1:${port}`;
    const headers = new Headers();
    for (const [key, value] of Object.entries(req.headers)) if (value) headers.set(key, Array.isArray(value) ? value.join(',') : value);
    // Local preview identity is supplied ONLY by this loopback-only development server.
    headers.set('oai-authenticated-user-id', 'local-development');
    const init = { method: req.method, headers, signal: abort.signal };
    if (!['GET', 'HEAD'].includes(req.method)) { init.body = Readable.toWeb(req); init.duplex = 'half'; }
    const request = new Request(new URL(req.url, origin), init);
    const response = await worker.fetch(request, { OPENAI_API_KEY: process.env.OPENAI_API_KEY, OPENAI_MODEL: process.env.OPENAI_MODEL });
    res.writeHead(response.status, Object.fromEntries(response.headers));
    res.end(Buffer.from(await response.arrayBuffer()));
  } catch { res.writeHead(500); res.end('Local preview failed.'); }
});
server.listen(port, '127.0.0.1', () => console.log(`SOLRDM local preview: http://127.0.0.1:${port}`));
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => server.close(() => process.exit(0)));
