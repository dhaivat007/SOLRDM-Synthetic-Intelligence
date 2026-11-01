"""Build and execute the actual APK-local adapter without a browser or network."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node.js is required to package the Android workspace')
class AgentPackagingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.output = Path(cls.tmp.name)
        cls.originals = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in (ROOT / 'web-agent').rglob('*')
                         if p.is_file() and 'node_modules' not in p.parts}
        subprocess.run(['node', str(ROOT / 'scripts/package-agent-assets.mjs'),
                        '--output-dir', str(cls.output)], check=True,
                       capture_output=True, text=True, timeout=30)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_assets_are_complete_without_modifying_web_sources(self):
        self.assertEqual({p.name for p in self.output.iterdir()},
                         {'index.html', 'style.css', 'app.js', 'android-adapter.js'})
        for path, expected in self.originals.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected, str(path))
        html = (self.output / 'index.html').read_text()
        self.assertLess(html.index('/android-adapter.js'), html.index('/app.js'))
        self.assertIn('Saved in this app', html)
        self.assertIn('Python engine screen', html)
        app = (self.output / 'app.js').read_text()
        self.assertIn('window.SolrdmAndroid.saveExport(filename, mime, content)', app)
        self.assertNotIn('link.download =', app)
        self.assertNotIn('Configure OPENAI_API_KEY', app)
        self.assertIn('200,000 characters', app)
        for name in ['app.js', 'android-adapter.js']:
            subprocess.run(['node', '--check', str(self.output / name)], check=True,
                           capture_output=True, text=True, timeout=30)

    def test_local_adapter_executes_real_tools_and_never_fakes_chat(self):
        script = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
let network = [];
const feedback = {textContent: '', hidden: true, classList: {toggle() {}}};
const context = {
  URL, Response, Request, Headers, DOMException, AbortController, TextDecoder, TextEncoder,
  setTimeout, clearTimeout, console,
  document: {addEventListener() {}, getElementById(id) { return id === 'feedback' ? feedback : null; }},
  fetch: async (url, options) => {
    network.push({url, options});
    return new Response(JSON.stringify({message:{items:[{title:['A paper'],DOI:'10.1234/test',published:{'date-parts':[[2026]]}}]}}));
  },
};
context.window = context;
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
(async () => {
  const status = await (await context.fetch('/api/status')).json();
  assert.equal(status.modelConfigured, false);
  assert.equal(status.runtime, 'android-local');
  assert.equal(status.tools.length, 5);
  const chat = await context.fetch('/api/chat', {method:'POST',body:JSON.stringify({text:'hello'})});
  assert.equal(chat.status,503);
  assert.equal((await chat.json()).code,'MODEL_NOT_CONFIGURED');
  const r = await context.fetch('/api/tools', {method:'POST',body:JSON.stringify({name:'simulate_projectile',args:{speed:10,angle:45,gravity:10}})});
  const result = await r.json();
  assert.equal(result.status,'completed');
  assert.ok(Math.abs(result.data.range-10)<1e-9);
  assert.equal(result.data.points.length,200);
  assert.equal(network.length,0);
  const invalid = await context.fetch('/api/tools', {method:'POST',body:JSON.stringify({name:'run_shell',args:{}})});
  assert.equal(invalid.status,400);
  assert.equal((await context.fetch('/api/tools',{method:'POST',body:'{broken'})).status,400);
  const controller = new AbortController(); controller.abort();
  await assert.rejects(context.fetch('/api/tools',{method:'POST',body:'{}',signal:controller.signal}),e=>e.name==='AbortError');
  await assert.rejects(context.fetch('https://evil.example/works'),/Only the Crossref/);
  await assert.rejects(context.fetch('https://api.crossref.org/other'),/Only the Crossref/);
  await assert.rejects(context.fetch('https://name:password@api.crossref.org/works'),/Only the Crossref/);
  assert.equal(network.length,0);
  const papers = await (await context.fetch('/api/tools',{method:'POST',body:JSON.stringify({name:'research_papers',args:{query:'test'}})})).json();
  assert.equal(papers.status,'completed',JSON.stringify(papers));
  assert.equal(papers.data.papers[0].title,'A paper');
  assert.equal(network.length,1);
  assert.equal(new URL(network[0].url).origin,'https://api.crossref.org');
  assert.equal(network[0].options.credentials,'omit');
  assert.equal(network[0].options.redirect,'error');
  context.__solrdmExportResult(false,'Save cancelled.');
  assert.equal(feedback.textContent,'Save cancelled.');
  assert.equal(feedback.hidden,false);
  console.log('Android adapter: offline tools, failed chat, network limits, cancellation and export callback passed.');
})().catch(error=>{ console.error(error);process.exitCode=1; });
"""
        result = subprocess.run(['node', '-e', script, str(self.output / 'android-adapter.js')],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Android adapter:', result.stdout)


if __name__ == '__main__':
    unittest.main()
