/** Bounded scientific tools. No model inference, arbitrary execution, or user URLs. */
const number = (description, minimum, maximum) => ({ type: 'number', description, minimum, maximum });
const text = (description, maxLength = 120) => ({ type: 'string', description, minLength: 1, maxLength });
const object = (properties) => ({ type: 'object', properties, required: Object.keys(properties), additionalProperties: false });
const array = (items, minItems, maxItems) => ({ type: 'array', items, minItems, maxItems });
const tool = (name, description, parameters) => ({ type: 'function', name, description, parameters, strict: true });

export const TOOL_DEFINITIONS = [
  tool('simulate_projectile', 'Calculate an ideal projectile trajectory launched from ground level. SI units, constant gravity, no air resistance. Results are a mathematical model, not experimental evidence.', object({
    speed: number('Initial speed in metres per second.', 0, 10000),
    angle: number('Launch angle above horizontal in degrees.', 0, 90),
    gravity: number('Constant gravitational acceleration in metres per second squared.', 0.001, 1000),
  })),
  tool('simulate_oscillator', 'Calculate an analytic damped mass-spring trajectory: m*x\u2033 + c*x\u2032 + k*x = 0. Reports position, velocity and mechanical energy. No external forcing.', object({
    mass: number('Mass in kilograms.', 0.001, 100000),
    spring: number('Spring stiffness in newtons per metre.', 0.001, 1000000),
    damping: number('Viscous damping coefficient in newton seconds per metre.', 0, 1000000),
    x0: number('Initial displacement from equilibrium in metres.', -1000000, 1000000),
    v0: number('Initial velocity in metres per second.', -1000000, 1000000),
    duration: number('Simulation duration in seconds.', 0.001, 3600),
  })),
  tool('describe_statistics', 'Calculate descriptive statistics for a supplied list of finite numbers. This does not infer causes, fit distributions, or establish statistical significance.', object({
    numbers: array(number('Observed numeric value.', -1e100, 1e100), 1, 1000),
  })),
  tool('compare_options', 'Rank options by an explicit weighted average of user-supplied criteria and scores. Scores are 0 to 10, with higher always better. Use scores in the same order as criteria. Do not invent objective measurements; disclose any estimated scores to the user.', object({
    criteria: array(object({ name: text('Criterion name.'), weight: number('Non-negative relative importance. At least one weight must be positive.', 0, 1000) }), 1, 10),
    options: array(object({ name: text('Option name.'), scores: array(number('Score for the corresponding criterion; higher is better.', 0, 10), 1, 10) }), 2, 10),
  })),
  tool('research_papers', 'Search Crossref for up to five scholarly publication metadata records. Returns source links and abstracts where present. These are discovery results, not a review of full papers, verification of claims, or an exhaustive literature search.', object({
    query: text('Topic or bibliographic search query.', 300),
  })),
];

function fields(value, names, label = 'Arguments') {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label} must be an object.`);
  const keys = Object.keys(value);
  if (keys.length !== names.length || names.some((name) => !Object.hasOwn(value, name)) || keys.some((name) => !names.includes(name))) {
    throw new Error(`${label} must contain exactly: ${names.join(', ')}.`);
  }
}

function finite(value, min, max, name) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < min || value > max) {
    throw new Error(`${name} must be a finite number from ${min} to ${max}.`);
  }
  return value;
}

function label(value, max, name) {
  if (typeof value !== 'string' || !value.trim() || value.length > max || /[\u0000-\u001f\u007f]/u.test(value)) {
    throw new Error(`${name} must be non-empty text of at most ${max} characters without control characters.`);
  }
  return value.trim();
}

function receipt(toolName, summary, data, assumptions, sources) {
  return { tool: toolName, status: 'completed', summary, data, assumptions, ...(sources ? { sources } : {}) };
}

function format(value) { return Number(value.toPrecision(6)).toString(); }

function projectile(args) {
  fields(args, ['speed', 'angle', 'gravity']);
  const speed = finite(args.speed, 0, 10000, 'speed');
  const angle = finite(args.angle, 0, 90, 'angle');
  const gravity = finite(args.gravity, 0.001, 1000, 'gravity');
  const radians = angle * Math.PI / 180;
  const vx = angle === 90 ? 0 : speed * Math.cos(radians);
  const vy = speed * Math.sin(radians);
  const flightTime = 2 * vy / gravity;
  const range = vx * flightTime;
  const maxHeight = vy * vy / (2 * gravity);
  const count = flightTime > 0 ? 200 : 1;
  const points = Array.from({ length: count }, (_, i) => {
    const t = count === 1 ? 0 : flightTime * i / (count - 1);
    return { t, x: vx * t, y: i === count - 1 ? 0 : Math.max(0, vy * t - gravity * t * t / 2) };
  });
  return receipt('simulate_projectile', `Ideal flight: ${format(flightTime)} s, range ${format(range)} m, peak height ${format(maxHeight)} m.`, {
    flightTime, range, maxHeight, points, parameters: { speed, angle, gravity }, units: { t: 's', x: 'm', y: 'm', speed: 'm/s', gravity: 'm/s²' },
  }, ['Launch and landing are both at ground level.', 'Gravity is constant; air resistance, wind, terrain and Earth curvature are excluded.', 'Analytic equations: x = v₀ cos(θ)t; y = v₀ sin(θ)t − gt²/2.']);
}

function oscillator(args) {
  fields(args, ['mass', 'spring', 'damping', 'x0', 'v0', 'duration']);
  const mass = finite(args.mass, 0.001, 100000, 'mass');
  const spring = finite(args.spring, 0.001, 1000000, 'spring');
  const damping = finite(args.damping, 0, 1000000, 'damping');
  const x0 = finite(args.x0, -1000000, 1000000, 'x0');
  const v0 = finite(args.v0, -1000000, 1000000, 'v0');
  const duration = finite(args.duration, 0.001, 3600, 'duration');
  const omegaSquared = spring / mass;
  const alpha = damping / (2 * mass);
  const discriminant = alpha * alpha - omegaSquared;
  const critical = Math.abs(discriminant) <= Math.max(omegaSquared, alpha * alpha) * 1e-12;
  const regime = critical ? 'critically damped' : discriminant < 0 ? (damping === 0 ? 'undamped' : 'underdamped') : 'overdamped';
  let evaluate;
  let period = null;
  if (critical) {
    const b = v0 + alpha * x0;
    evaluate = (t) => {
      const decay = Math.exp(-alpha * t);
      return { x: (x0 + b * t) * decay, v: (b - alpha * (x0 + b * t)) * decay };
    };
  } else if (discriminant < 0) {
    const omega = Math.sqrt(-discriminant);
    const b = (v0 + alpha * x0) / omega;
    period = 2 * Math.PI / omega;
    evaluate = (t) => {
      const cos = Math.cos(omega * t), sin = Math.sin(omega * t), decay = Math.exp(-alpha * t);
      const base = x0 * cos + b * sin;
      return { x: decay * base, v: decay * (-alpha * base - x0 * omega * sin + b * omega * cos) };
    };
  } else {
    const root = Math.sqrt(discriminant);
    // This form avoids cancellation in the slow root for strong damping.
    const r1 = -omegaSquared / (alpha + root), r2 = -alpha - root;
    const a = (v0 - r2 * x0) / (r1 - r2), b = x0 - a;
    evaluate = (t) => {
      const first = a * Math.exp(r1 * t), second = b * Math.exp(r2 * t);
      return { x: first + second, v: r1 * first + r2 * second };
    };
  }
  const points = Array.from({ length: 501 }, (_, i) => {
    const t = duration * i / 500;
    const { x, v } = i === 0 ? { x: x0, v: v0 } : evaluate(t);
    return { t, x, v, energy: (mass * v * v + spring * x * x) / 2 };
  });
  const resolutionWarning = period && duration / 500 > period / 20
    ? 'The 501 plotted samples provide fewer than 20 points per oscillation. Shorten the duration to see each cycle; sampled positions remain analytic.'
    : null;
  return receipt('simulate_oscillator', `${regime.charAt(0).toUpperCase() + regime.slice(1)} oscillator over ${format(duration)} s; final displacement ${format(points.at(-1).x)} m.`, {
    regime, initialEnergy: points[0].energy, finalEnergy: points.at(-1).energy, points,
    parameters: { mass, spring, damping, x0, v0, duration }, units: { t: 's', x: 'm', v: 'm/s', energy: 'J', mass: 'kg', spring: 'N/m', damping: 'N·s/m' }, resolutionWarning,
  }, ['Analytic solution of m x″ + c x′ + k x = 0 with constant coefficients.', 'Linear spring, viscous damping and no external forcing; this is an idealized model.', ...(resolutionWarning ? [resolutionWarning] : [])]);
}

function statistics(args) {
  fields(args, ['numbers']);
  if (!Array.isArray(args.numbers) || args.numbers.length < 1 || args.numbers.length > 1000) throw new Error('numbers must contain between 1 and 1000 numeric values.');
  const values = args.numbers.map((n) => finite(n, -1e100, 1e100, 'Each value'));
  let mean = 0, m2 = 0;
  values.forEach((value, i) => { const delta = value - mean; mean += delta / (i + 1); m2 += delta * (value - mean); });
  const sorted = [...values].sort((a, b) => a - b), count = values.length;
  const median = count % 2 ? sorted[(count - 1) / 2] : (sorted[count / 2 - 1] + sorted[count / 2]) / 2;
  const data = { count, mean, median, min: sorted[0], max: sorted.at(-1), range: sorted.at(-1) - sorted[0], populationStandardDeviation: Math.sqrt(Math.max(0, m2 / count)), sampleStandardDeviation: count > 1 ? Math.sqrt(Math.max(0, m2 / (count - 1))) : null };
  return receipt('describe_statistics', `${count} values: mean ${format(mean)}, median ${format(median)}, range ${format(data.min)}–${format(data.max)}.`, data,
    ['Every supplied value receives equal weight; missing and non-numeric values are rejected.', 'Population standard deviation divides by n; sample standard deviation divides by n−1 and is undefined for one observation.', 'Descriptive statistics alone do not establish causation or significance.']);
}

function compare(args) {
  fields(args, ['criteria', 'options']);
  if (!Array.isArray(args.criteria) || args.criteria.length < 1 || args.criteria.length > 10) throw new Error('criteria must contain between 1 and 10 criteria.');
  if (!Array.isArray(args.options) || args.options.length < 2 || args.options.length > 10) throw new Error('options must contain between 2 and 10 options.');
  const criteria = args.criteria.map((c) => { fields(c, ['name', 'weight'], 'Criterion'); return { name: label(c.name, 120, 'Criterion name'), weight: finite(c.weight, 0, 1000, 'weight') }; });
  const total = criteria.reduce((sum, c) => sum + c.weight, 0);
  if (!total) throw new Error('At least one criterion weight must be positive.');
  if (new Set(criteria.map((c) => c.name.toLowerCase())).size !== criteria.length) throw new Error('Criterion names must be unique.');
  const options = args.options.map((o) => {
    fields(o, ['name', 'scores'], 'Option');
    const name = label(o.name, 120, 'Option name');
    if (!Array.isArray(o.scores) || o.scores.length !== criteria.length) throw new Error('Each option needs one score per criterion, in criterion order.');
    const scores = o.scores.map((v) => finite(v, 0, 10, 'score'));
    return { name, scores, weightedScore: scores.reduce((sum, score, i) => sum + score * criteria[i].weight, 0) / total };
  });
  if (new Set(options.map((o) => o.name.toLowerCase())).size !== options.length) throw new Error('Option names must be unique.');
  options.sort((a, b) => b.weightedScore - a.weightedScore);
  const top = options.filter((o) => Math.abs(o.weightedScore - options[0].weightedScore) <= 1e-12).map((o) => o.name);
  return receipt('compare_options', `${top.length > 1 ? 'Tied highest' : 'Highest'} weighted score: ${top.join(', ')} (${format(options[0].weightedScore)} / 10).`, {
    criteria: criteria.map((c) => ({ ...c, normalizedWeight: c.weight / total })), ranking: options, topOptions: top,
  }, ['Scores and weights are supplied judgments, not independently verified facts.', 'Higher scores are always better. Weighted average = Σ(weight × score) / Σ(weight).', 'This ranks the supplied options only; it does not execute a decision or prove which choice is best.']);
}

function cleanMetadata(value, max = 1000) {
  if (typeof value !== 'string') return '';
  return value.slice(0, Math.max(max * 4, 8000)).replace(/<[^>]*>/gu, ' ').replace(/&(?:amp|lt|gt|quot|apos);/gu, (s) => ({ '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&apos;': "'" })[s]).replace(/[\u0000-\u001f\u007f]/gu, ' ').replace(/\s+/gu, ' ').trim().slice(0, max);
}

async function boundedJSON(response, signal) {
  const limit = 256 * 1024;
  const length = Number(response.headers.get('content-length'));
  if (Number.isFinite(length) && length > limit) throw new Error('Research source returned too much data.');
  if (!response.body) throw new Error('Research source returned an empty response.');
  const reader = response.body.getReader();
  let total = 0;
  const chunks = [];
  try {
    while (true) {
      if (signal.aborted) throw new Error('Research request cancelled or timed out.');
      const { value, done } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > limit) throw new Error('Research source returned too much data.');
      chunks.push(value);
    }
  } catch (error) {
    await reader.cancel().catch(() => {});
    throw error;
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { return JSON.parse(new TextDecoder().decode(bytes)); } catch { throw new Error('Research source returned invalid JSON.'); }
}

async function papers(args, { fetchImpl, signal }) {
  fields(args, ['query']);
  const query = label(args.query, 300, 'query');
  if (signal?.aborted) throw new Error('Research request cancelled.');
  const controller = new AbortController();
  const cancel = () => controller.abort();
  signal?.addEventListener('abort', cancel, { once: true });
  const timeout = setTimeout(cancel, 10000);
  const url = new URL('https://api.crossref.org/works');
  url.searchParams.set('query.bibliographic', query);
  url.searchParams.set('rows', '5');
  url.searchParams.set('select', 'DOI,title,author,published,abstract,type');
  try {
    const response = await fetchImpl(url.toString(), { headers: { Accept: 'application/json' }, signal: controller.signal, redirect: 'error' });
    if (!response.ok) throw new Error(`Research source unavailable (HTTP ${response.status}).`);
    const result = await boundedJSON(response, controller.signal);
    if (!Array.isArray(result?.message?.items)) throw new Error('Research source returned an unexpected format.');
    const records = result.message.items.slice(0, 5).map((item) => {
      const doi = typeof item?.DOI === 'string' && /^10\.\d{4,9}\/[^\s<>"']{1,180}$/u.test(item.DOI) ? item.DOI : null;
      const year = item?.published?.['date-parts']?.[0]?.[0];
      return {
        title: cleanMetadata(Array.isArray(item?.title) ? item.title[0] : null) || 'Untitled publication',
        authors: Array.isArray(item?.author) ? item.author.slice(0, 10).map((a) => cleanMetadata([a?.given, a?.family].filter((v) => typeof v === 'string').join(' '), 200)).filter(Boolean) : [],
        year: Number.isInteger(year) && year >= 1 && year <= 9999 ? year : null,
        doi, url: doi ? `https://doi.org/${encodeURIComponent(doi)}` : null,
        abstract: cleanMetadata(item?.abstract, 4000) || null, source: 'Crossref metadata',
      };
    });
    const sources = [{ title: 'Crossref metadata search', url: url.toString() }, ...records.filter((p) => p.url).map((p) => ({ title: p.title, url: p.url }))];
    return receipt('research_papers', `Found ${records.length} publication metadata record${records.length === 1 ? '' : 's'} in Crossref. Full papers have not been read.`, { query, papers: records },
      ['This is a relevance-ranked metadata search, not an exhaustive or systematically screened literature review.', 'Abstracts are publisher-supplied metadata when available and may be truncated to 4000 characters; full paper text is not retrieved.', 'Bibliographic records can contain errors and do not establish that a scientific claim is correct.'], sources);
  } catch (error) {
    if (controller.signal.aborted) throw new Error('Research request cancelled or timed out.');
    if (error instanceof Error && /^Research source /u.test(error.message)) throw error;
    throw new Error('Research source could not be reached. Try again later.');
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener('abort', cancel);
  }
}

export async function executeTool(name, args, { fetchImpl = fetch, signal } = {}) {
  if (signal?.aborted) throw new Error('Tool request cancelled.');
  switch (name) {
    case 'simulate_projectile': return projectile(args);
    case 'simulate_oscillator': return oscillator(args);
    case 'describe_statistics': return statistics(args);
    case 'compare_options': return compare(args);
    case 'research_papers': return papers(args, { fetchImpl, signal });
    default: throw new Error('Unknown tool.');
  }
}
