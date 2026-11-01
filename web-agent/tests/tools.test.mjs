import test from 'node:test';
import assert from 'node:assert/strict';
import { executeTool, TOOL_DEFINITIONS } from '../src/tools.mjs';

const close = (actual, expected, tolerance = 1e-9) => assert.ok(Math.abs(actual - expected) <= tolerance * Math.max(1, Math.abs(expected)), `${actual} != ${expected}`);
const oscillator = { mass: 1, spring: 4, damping: 0, x0: 1, v0: 0, duration: Math.PI };

test('all model function schemas are strict and fully required', () => {
  function validate(schema) {
    if (schema.type === 'object') {
      assert.equal(schema.additionalProperties, false);
      assert.deepEqual(schema.required.sort(), Object.keys(schema.properties).sort());
      Object.values(schema.properties).forEach(validate);
    }
    if (schema.type === 'array') validate(schema.items);
  }
  assert.equal(TOOL_DEFINITIONS.length, 5);
  TOOL_DEFINITIONS.forEach((tool) => { assert.equal(tool.strict, true); validate(tool.parameters); });
});

test('projectile matches analytic 45-degree range and landing', async () => {
  const r = await executeTool('simulate_projectile', { speed: 10, angle: 45, gravity: 10 });
  assert.equal(r.status, 'completed');
  close(r.data.range, 10);
  close(r.data.maxHeight, 2.5);
  close(r.data.flightTime, Math.SQRT2);
  assert.equal(r.data.points.length, 200);
  assert.equal(r.data.points.at(-1).y, 0);
  assert.equal(r.data.points[0].t, 0);
});

test('projectile handles zero velocity and vertical launch without phantom range', async () => {
  const zero = await executeTool('simulate_projectile', { speed: 0, angle: 10, gravity: 9.81 });
  assert.deepEqual(zero.data.points, [{ t: 0, x: 0, y: 0 }]);
  const vertical = await executeTool('simulate_projectile', { speed: 10, angle: 90, gravity: 10 });
  assert.equal(vertical.data.range, 0);
});

test('undamped oscillator preserves energy and completes one known period', async () => {
  const r = await executeTool('simulate_oscillator', oscillator);
  assert.equal(r.data.regime, 'undamped');
  assert.equal(r.data.points.length, 501);
  close(r.data.points.at(-1).x, 1);
  close(r.data.points.at(-1).v, 0);
  r.data.points.forEach((p) => close(p.energy, 2));
});

test('critical damping matches x=(1+2t)e^-2t and loses energy', async () => {
  const r = await executeTool('simulate_oscillator', { ...oscillator, damping: 4, duration: 1 });
  assert.equal(r.data.regime, 'critically damped');
  close(r.data.points.at(-1).x, 3 * Math.exp(-2));
  close(r.data.points.at(-1).v, -4 * Math.exp(-2));
  assert.ok(r.data.finalEnergy < r.data.initialEnergy);
});

test('overdamped oscillator stays finite at bounded extreme parameters', async () => {
  const r = await executeTool('simulate_oscillator', { mass: .001, spring: .001, damping: 1e6, x0: 1e6, v0: -1e6, duration: 3600 });
  assert.equal(r.data.regime, 'overdamped');
  r.data.points.forEach((p) => Object.values(p).forEach((value) => assert.ok(Number.isFinite(value))));
  assert.ok(r.data.finalEnergy < r.data.initialEnergy);
});

test('underdamped and overdamped samples match independent closed-form solutions', async () => {
  const under = await executeTool('simulate_oscillator', { ...oscillator, damping: 2, duration: 1 });
  close(under.data.points.at(-1).x, Math.exp(-1) * (Math.cos(Math.sqrt(3)) + Math.sin(Math.sqrt(3)) / Math.sqrt(3)));
  const over = await executeTool('simulate_oscillator', { ...oscillator, damping: 5, duration: 1 });
  close(over.data.points.at(-1).x, (4 * Math.exp(-1) - Math.exp(-4)) / 3);
  close(over.data.points.at(-1).v, (-4 * Math.exp(-1) + 4 * Math.exp(-4)) / 3);
});

test('underdamped oscillator satisfies both initial conditions and reports sampling limits', async () => {
  const r = await executeTool('simulate_oscillator', { ...oscillator, damping: .2, x0: 3, v0: -2, duration: 3600 });
  assert.equal(r.data.regime, 'underdamped');
  assert.equal(r.data.points[0].x, 3);
  assert.equal(r.data.points[0].v, -2);
  assert.match(r.data.resolutionWarning, /fewer than 20/);
});

test('statistics matches known sample and distinguishes population/sample SD', async () => {
  const r = await executeTool('describe_statistics', { numbers: [2, 4, 4, 4, 5, 5, 7, 9] });
  assert.equal(r.data.mean, 5);
  assert.equal(r.data.median, 4.5);
  assert.equal(r.data.populationStandardDeviation, 2);
  close(r.data.sampleStandardDeviation, Math.sqrt(32 / 7));
  const single = await executeTool('describe_statistics', { numbers: [7] });
  assert.equal(single.data.sampleStandardDeviation, null);
  assert.equal(single.data.populationStandardDeviation, 0);
});

test('weighted decision ranks supplied values with normalized weights and explicit ties', async () => {
  const args = { criteria: [{ name: 'Cost', weight: 3 }, { name: 'Speed', weight: 1 }], options: [{ name: 'A', scores: [8, 4] }, { name: 'B', scores: [5, 10] }] };
  const r = await executeTool('compare_options', args);
  assert.equal(r.data.ranking[0].name, 'A');
  assert.equal(r.data.ranking[0].weightedScore, 7);
  assert.equal(r.data.criteria[0].normalizedWeight, .75);
  const tie = await executeTool('compare_options', { criteria: [{ name: 'Fit', weight: 1 }], options: [{ name: 'A', scores: [8] }, { name: 'B', scores: [8] }] });
  assert.deepEqual(tie.data.topOptions, ['A', 'B']);
});

test('invalid inputs and arbitrary tool names are rejected, never coerced or evaluated', async () => {
  const cases = [
    ['simulate_projectile', { speed: '10', angle: 45, gravity: 10 }],
    ['simulate_projectile', { speed: 10, angle: 45, gravity: 0 }],
    ['simulate_projectile', { speed: 10, angle: 45, gravity: 10, code: 'process.exit()' }],
    ['simulate_oscillator', { ...oscillator, mass: 0 }],
    ['describe_statistics', { numbers: [Infinity] }],
    ['describe_statistics', { numbers: [] }],
    ['describe_statistics', { numbers: Array(1001).fill(1) }],
    ['compare_options', { criteria: [{ name: 'x', weight: 0 }], options: [{ name: 'a', scores: [1] }, { name: 'b', scores: [2] }] }],
    ['compare_options', { criteria: [{ name: 'x', weight: 1 }], options: [{ name: 'a', scores: [1, 2] }, { name: 'b', scores: [2] }] }],
    ['research_papers', { query: 'hello', url: 'http://localhost/' }],
    ['__proto__', {}], ['eval', { code: '1+1' }],
  ];
  for (const [name, args] of cases) await assert.rejects(executeTool(name, args));
});

test('research requests only fixed Crossref endpoint and returns bounded linked metadata', async () => {
  let requested;
  const r = await executeTool('research_papers', { query: 'climate sensitivity' }, { fetchImpl: async (url, options) => {
    requested = new URL(url);
    assert.equal(options.redirect, 'error');
    assert.equal(options.signal.aborted, false);
    return Response.json({ message: { items: [{ DOI: '10.1000/example', title: ['<i>Study</i> &amp; result'], author: [{ given: 'Ada', family: 'Lovelace' }], published: { 'date-parts': [[2024]] }, abstract: '<jats:p>Observed &lt;result&gt;.</jats:p>' }] } });
  } });
  assert.equal(requested.origin, 'https://api.crossref.org');
  assert.equal(requested.pathname, '/works');
  assert.equal(requested.searchParams.get('rows'), '5');
  assert.equal(requested.searchParams.get('query.bibliographic'), 'climate sensitivity');
  assert.equal(r.data.papers[0].title, 'Study & result');
  assert.deepEqual(r.data.papers[0].authors, ['Ada Lovelace']);
  assert.equal(r.data.papers[0].year, 2024);
  assert.equal(r.data.papers[0].url, 'https://doi.org/10.1000%2Fexample');
  assert.match(r.summary, /Full papers have not been read/);
});

test('research tolerates absent fields without inventing metadata or trusted links', async () => {
  const r = await executeTool('research_papers', { query: 'x' }, { fetchImpl: async () => Response.json({ message: { items: [null, { DOI: 'javascript:alert(1)' }, { title: ['<script>x</script>'] }] } }) });
  assert.equal(r.data.papers.length, 3);
  assert.equal(r.data.papers[0].year, null);
  assert.equal(r.data.papers[0].abstract, null);
  assert.equal(r.data.papers[1].url, null);
  assert.equal(r.sources.length, 1);
});

test('research rejects HTTP errors, malformed JSON, oversized payloads and failed fetches', async () => {
  const providers = [
    async () => new Response('rate limit', { status: 429 }),
    async () => new Response('{'),
    async () => Response.json({ unexpected: true }),
    async () => new Response('x'.repeat(256 * 1024 + 1)),
    async () => new Response('{}', { headers: { 'content-length': String(300000) } }),
    async () => { throw new Error('secret infrastructure detail'); },
  ];
  for (const fetchImpl of providers) await assert.rejects(executeTool('research_papers', { query: 'x' }, { fetchImpl }), /Research source/);
});

test('cancelled tools never invoke network', async () => {
  const controller = new AbortController(); controller.abort();
  await assert.rejects(executeTool('research_papers', { query: 'x' }, { signal: controller.signal, fetchImpl: () => { throw new Error('must not fetch'); } }), /cancelled/);
});
