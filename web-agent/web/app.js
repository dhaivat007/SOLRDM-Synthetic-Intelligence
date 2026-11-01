'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const STORAGE_KEY = 'solrdm.conversations.v1';
  const MAX_FILES = 3, MAX_PAYLOAD = 20 * 1024 * 1024;
  const state = { conversations: [], currentId: null, mode: 'chat', attachments: [], busy: false, processing: false, request: null, requestId: 0, pendingDraft: null, fileBatch: 0, status: null, toolReceipt: null, toolBusy: false };
  function node(tag, className, text) { const n = document.createElement(tag); if (className) n.className = className; if (text !== undefined) n.textContent = String(text); return n; }
  function id() { return crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2); }
  function current() { return state.conversations.find(c => c.id === state.currentId); }
  function feedback(message, success = false) { $('feedback').textContent = message || ''; $('feedback').hidden = !message; $('feedback').classList.toggle('success', success); }
  function save() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify({ currentId: state.currentId, conversations: state.conversations.slice(0, 20) })); }
    catch { feedback('Browser storage is full or unavailable. This session still works; export your conversation to keep it.'); }
  }
  function load() {
    try {
      const value = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
      if (Array.isArray(value.conversations)) {
        state.conversations = value.conversations.filter(c => c && typeof c.id === 'string' && typeof c.title === 'string' && Array.isArray(c.messages)).slice(0, 20).map(c => ({ id: c.id, title: c.title.slice(0, 80), mode: ['chat','research','review','plan'].includes(c.mode) ? c.mode : 'chat', created: c.created || Date.now(), messages: c.messages.filter(m => m && ['user','assistant'].includes(m.role) && typeof m.content === 'string').slice(-80).map(m => ({ ...m, content: m.content.slice(0, 80000) })) }));
        state.currentId = state.conversations.some(c => c.id === value.currentId) ? value.currentId : state.conversations[0]?.id;
      }
    } catch { feedback('Saved history could not be read. You can start a new conversation.'); }
    if (!current()) makeConversation(false);
    state.mode = current().mode;
  }
  function makeConversation(shouldSave = true) {
    stopRequest(false); state.fileBatch++; state.attachments = []; state.processing = false;
    const conversation = { id: id(), title: 'New conversation', mode: 'chat', created: Date.now(), messages: [] };
    state.conversations.unshift(conversation); state.conversations = state.conversations.slice(0, 20); state.currentId = conversation.id; state.mode = 'chat';
    if (shouldSave) save();
    $('message-input').value = ''; feedback(''); render(); closeSidebar();
  }
  function selectConversation(conversationId) {
    if (state.currentId === conversationId) { closeSidebar(); return; }
    stopRequest(false); state.fileBatch++; state.attachments = []; state.processing = false;
    state.currentId = conversationId; state.mode = current().mode; $('message-input').value = ''; feedback(''); save(); render(); closeSidebar();
  }
  function renderHistory() {
    const list = $('conversation-list'); list.replaceChildren();
    const chats = state.conversations.filter(c => c.messages.length || c.id === state.currentId);
    $('history-count').textContent = String(chats.length);
    chats.forEach(c => {
      const button = node('button', 'history-item' + (c.id === state.currentId ? ' selected' : ''));
      button.append(node('span', '', '◌'), node('span', '', c.title)); button.title = c.title;
      if (c.id === state.currentId) button.setAttribute('aria-current', 'page');
      button.addEventListener('click', () => selectConversation(c.id)); list.append(button);
    });
  }
  function setMode(mode) { state.mode = mode; current().mode = mode; save(); renderModes(); }
  function renderModes() { document.querySelectorAll('.mode-button').forEach(b => { const selected = b.dataset.mode === state.mode; b.classList.toggle('selected', selected); b.setAttribute('aria-pressed', String(selected)); }); }
  function safeUrl(value) { try { const u = new URL(value); return u.protocol === 'https:' || u.protocol === 'http:' ? u.href : null; } catch { return null; } }
  function appendInline(parent, text) {
    const pattern = /(\*\*([^*\n]+)\*\*|`([^`\n]+)`)/g; let last = 0;
    for (const match of text.matchAll(pattern)) {
      parent.append(document.createTextNode(text.slice(last, match.index)));
      parent.append(node(match[2] ? 'strong' : 'code', '', match[2] || match[3])); last = match.index + match[0].length;
    }
    parent.append(document.createTextNode(text.slice(last)));
  }
  function renderText(target, text) {
    const lines = String(text).split('\n'); let paragraph = [], code = null, list = null;
    function flush() { if (paragraph.length) { const p = node('p'); appendInline(p, paragraph.join('\n')); p.style.whiteSpace = 'pre-wrap'; target.append(p); paragraph = []; } list = null; }
    for (const line of lines) {
      if (/^```/.test(line)) { if (code !== null) { const pre = node('pre'); pre.append(node('code', '', code.join('\n'))); target.append(pre); code = null; } else { flush(); code = []; } continue; }
      if (code !== null) { code.push(line); continue; }
      if (!line.trim()) { flush(); continue; }
      const heading = /^#{1,4}\s+(.+)$/.exec(line);
      if (heading) { flush(); const h = node('h3'); appendInline(h, heading[1]); target.append(h); continue; }
      const item = /^\s*(?:[-*]|\d+\.)\s+(.+)$/.exec(line);
      if (item) { if (paragraph.length) flush(); if (!list) { list = node('ul'); target.append(list); } const li = node('li'); appendInline(li, item[1]); list.append(li); continue; }
      if (list) flush(); paragraph.push(line);
    }
    flush(); if (code !== null) { const pre = node('pre'); pre.append(node('code', '', code.join('\n'))); target.append(pre); }
  }
  function renderSources(sources, parent) {
    if (!Array.isArray(sources)) return;
    const links = node('div', 'citations'); const seen = new Set();
    sources.slice(0, 20).forEach(source => { if (!source || typeof source !== 'object') return; const url = safeUrl(source.url); if (!url || seen.has(url)) return; seen.add(url); const a = node('a', 'citation', source.title || new URL(url).hostname); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; a.title = url; links.append(a); });
    if (links.childNodes.length) parent.append(links);
  }
  function renderChart(receipt, parent) {
    const points = receipt?.data?.points;
    if (!Array.isArray(points) || points.length < 2) return;
    const projectile = receipt.tool === 'simulate_projectile';
    if (!projectile && receipt.tool !== 'simulate_oscillator') return;
    const pairs = points.slice(0, 501).map(p => [projectile ? p.x : p.t, projectile ? p.y : p.x]).filter(p => p.every(Number.isFinite)); if (pairs.length < 2) return;
    const xs = pairs.map(p => p[0]), ys = pairs.map(p => p[1]); const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(0, ...ys), maxY = Math.max(0, ...ys);
    const xScale = x => 40 + (x - minX) / (maxX - minX || 1) * 450; const yScale = y => 183 - (y - minY) / (maxY - minY || 1) * 158;
    const ns = 'http://www.w3.org/2000/svg'; const svg = document.createElementNS(ns, 'svg'); svg.setAttribute('viewBox', '0 0 520 220'); svg.setAttribute('class', 'result-chart'); svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', projectile ? 'Simulated height against horizontal distance' : 'Simulated displacement against time');
    const line = document.createElementNS(ns, 'path'); line.setAttribute('d', `M40 20V183H493 M40 ${yScale(0)}H493`); line.setAttribute('stroke', '#d8e5ce'); line.setAttribute('fill', 'none'); svg.append(line);
    const path = document.createElementNS(ns, 'path'); path.setAttribute('d', pairs.map((p, i) => `${i ? 'L' : 'M'}${xScale(p[0]).toFixed(2)},${yScale(p[1]).toFixed(2)}`).join(' ')); path.setAttribute('stroke', '#5e8950'); path.setAttribute('stroke-width', '2.5'); path.setAttribute('fill', 'none'); svg.append(path);
    [[40, 204, `${minX.toPrecision(3)}`], [455, 204, `${maxX.toPrecision(3)}`], [5, 28, `${maxY.toPrecision(2)}`], [5, 182, `${minY.toPrecision(2)}`]].forEach(([x, y, value]) => { const t = document.createElementNS(ns, 'text'); t.setAttribute('x', x); t.setAttribute('y', y); t.setAttribute('font-size', '10'); t.setAttribute('fill', '#8ba177'); t.textContent = value; svg.append(t); });
    parent.append(svg, node('div', 'chart-caption', projectile ? 'Horizontal distance (m) → · Height (m) ↑' : 'Time (s) → · Displacement (m) ↑'));
  }
  function renderReceipt(receipt) {
    const card = node('div', 'receipt');
    if (!receipt || typeof receipt !== 'object') return card;
    const completed = receipt.status === 'completed';
    card.append(node('div', 'receipt-header', `${completed ? '✓' : '!'} ${String(receipt.tool || 'Tool').replaceAll('_', ' ')} · ${completed ? 'Result recorded' : 'Not completed'}`));
    card.append(node('div', 'receipt-summary', receipt.summary || receipt.error || 'No result summary returned.'));
    renderChart(receipt, card);
    if (Array.isArray(receipt.assumptions) && receipt.assumptions.length) { const list = node('ul'); receipt.assumptions.slice(0, 20).forEach(a => list.append(node('li', '', a))); card.append(list); }
    renderSources(receipt.sources, card);
    if (receipt.data) { const details = node('details'); details.append(node('summary', '', 'Inspect values & method'), node('pre', '', JSON.stringify(receipt.data, null, 2))); card.append(details); }
    return card;
  }
  function renderMessages() {
    const conversation = current(); $('welcome').hidden = conversation.messages.length > 0;
    const messages = $('messages'); messages.replaceChildren();
    conversation.messages.forEach(m => {
      const article = node('article', `message ${m.role}`); const header = node('div', 'message-header'); header.append(node('span', 'message-avatar', m.role === 'user' ? 'Y' : '✦'), node('span', '', m.role === 'user' ? 'You' : 'SOLRDM'));
      if (m.role === 'assistant' && m.incomplete === true) header.append(node('span', 'incomplete-badge', 'Incomplete'));
      article.append(header);
      const body = node('div', 'message-body'); renderText(body, m.content);
      if (Array.isArray(m.attachments) && m.attachments.length) { const files = node('div', 'message-attachments'); m.attachments.forEach(a => files.append(node('span', 'message-file', `${a.kind === 'video' ? '▸' : '▤'} ${a.name} · ${a.description || a.kind} · attach again for a new review`))); body.append(files); }
      renderSources(m.citations, body); if (Array.isArray(m.receipts)) m.receipts.slice(0, 8).forEach(r => body.append(renderReceipt(r))); article.append(body);
      if (m.role === 'assistant') { const actions = node('div', 'message-actions'); const copy = node('button', '', 'Copy'); copy.addEventListener('click', async () => { try { await navigator.clipboard.writeText(m.content); copy.textContent = 'Copied'; setTimeout(() => { copy.textContent = 'Copy'; }, 1600); } catch { feedback('Copy is unavailable here. Export the conversation instead.'); } }); actions.append(copy); if ('speechSynthesis' in window) { const speak = node('button', '', 'Read aloud'); speak.addEventListener('click', () => { speechSynthesis.cancel(); const utterance = new SpeechSynthesisUtterance(m.content); utterance.onend = () => { speak.textContent = 'Read aloud'; }; utterance.onerror = utterance.onend; if (speak.dataset.speaking === 'yes') { speak.dataset.speaking = 'no'; speak.textContent = 'Read aloud'; return; } speak.dataset.speaking = 'yes'; speak.textContent = 'Stop reading'; utterance.onend = () => { speak.dataset.speaking = 'no'; speak.textContent = 'Read aloud'; }; utterance.onerror = utterance.onend; speechSynthesis.speak(utterance); }); actions.append(speak); } article.append(actions); }
      messages.append(article);
    });
  }
  function renderAttachments() {
    const parent = $('attachments'); parent.replaceChildren();
    state.attachments.forEach((file, index) => { const item = node('div', 'attachment'); item.append(node('span', '', file.kind === 'video' ? '▸' : '▤')); const label = node('div'); label.append(node('strong', '', file.name), node('small', '', file.description)); item.append(label); const remove = node('button', '', '×'); remove.type = 'button'; remove.setAttribute('aria-label', `Remove ${file.name}`); remove.disabled = state.busy; remove.addEventListener('click', () => { state.attachments.splice(index, 1); renderAttachments(); updateControls(); }); item.append(remove); parent.append(item); });
  }
  function updateControls() {
    $('send-button').hidden = state.busy; $('stop-button').hidden = !state.busy;
    $('send-button').disabled = state.processing || (!state.attachments.length && !$('message-input').value.trim());
    $('attach-button').disabled = state.busy || state.processing || state.attachments.length >= MAX_FILES;
    $('file-input').disabled = state.busy || state.processing; $('working-indicator').hidden = !state.busy;
    $('attachment-hint').textContent = state.processing ? 'Preparing files…' : 'Images, video, PDF & text';
  }
  function render() {
    $('rename-chat').replaceChildren(document.createTextNode(current().title + ' '), node('span', '', '⌄'));
    renderHistory(); renderModes(); renderMessages(); renderAttachments(); updateControls();
  }
  function scrollDown() { requestAnimationFrame(() => { $('conversation-scroll').scrollTop = $('conversation-scroll').scrollHeight; }); }
  function restorePendingDraft(restoreFiles) {
    const draft = state.pendingDraft; if (!draft) return;
    const conversation = state.conversations.find(c => c.id === draft.conversationId);
    if (conversation) conversation.messages = conversation.messages.filter(m => m !== draft.message);
    if (restoreFiles && draft.conversationId === state.currentId) { $('message-input').value = draft.text; state.attachments = draft.attachments; }
    state.pendingDraft = null; save();
  }
  function stopRequest(show = true) {
    if (state.request) state.request.abort(); state.request = null; state.requestId++;
    const wasBusy = state.busy; state.busy = false;
    if (wasBusy) { restorePendingDraft(show); if (show) { feedback('Request stopped. Your draft and files are ready to try again.'); renderMessages(); renderAttachments(); } }
    updateControls();
  }
  async function api(url, options = {}) {
    const response = await fetch(url, options); let data;
    try { data = await response.json(); } catch { throw new Error(response.status === 401 || response.status === 403 ? 'Sign in to this private Site, then try again.' : 'The service returned an unreadable response. Please try again.'); }
    if (!response.ok) { const error = new Error(typeof data.error === 'string' ? data.error : `Request failed (${response.status}).`); error.code = data.code; throw error; } return data;
  }
  async function refreshStatus() {
    $('refresh-status').disabled = true;
    try {
      state.status = await api('/api/status'); const configured = state.status.modelConfigured === true;
      const badge = $('connection-badge'); badge.className = 'connection-badge ' + (configured ? 'configured' : 'pending'); badge.replaceChildren(node('i'), document.createTextNode(configured ? 'Model configured' : 'Model setup pending'));
      $('setup-notice').hidden = configured; $('settings-status').classList.toggle('pending', !configured);
      $('settings-status').textContent = configured ? `Model configured: ${state.status.model || 'multimodal model'}. A successful response will verify provider access.` : 'Model setup is pending. Configure OPENAI_API_KEY securely in the Site’s server environment to enable conversation and file understanding. The key is never entered or stored in this browser.';
      const limits = $('server-limitations'); limits.replaceChildren();
      if (Array.isArray(state.status.limitations)) { const list = node('ul', 'muted'); state.status.limitations.forEach(l => list.append(node('li', '', l))); limits.append(list); }
    } catch (error) {
      state.status = null; $('connection-badge').replaceChildren(node('i'), document.createTextNode('Connection unavailable')); $('settings-status').textContent = `Could not check setup: ${error.message}`; $('settings-status').classList.add('pending'); $('setup-notice').hidden = true;
    } finally { $('refresh-status').disabled = false; }
  }
  async function submitMessage(event) {
    event.preventDefault(); if (state.busy || state.processing) return;
    const text = $('message-input').value.trim(); if (!text && !state.attachments.length) return;
    if (state.status && !state.status.modelConfigured) { feedback('Conversation needs a model connection. Open Connection & capabilities for setup, or use the scientific workbench now.'); return; }
    const conversation = current(); const conversationId = conversation.id; const previous = conversation.messages.slice(-20).map(m => ({ role: m.role, content: m.content + (Array.isArray(m.attachments) && m.attachments.length ? '\n[Earlier attachments: ' + m.attachments.map(a => a.name).join(', ') + '. File content is not included in this follow-up; ask for a new attachment if needed.]' : '') }));
    const files = state.attachments.map(({ description, ...file }) => file); const metadata = state.attachments.map(({ name, kind, sha256, description }) => ({ name, kind, sha256, description }));
    const content = text || 'Please review the attached files.';
    const userMessage = { role: 'user', content, attachments: metadata, created: Date.now() };
    state.pendingDraft = { conversationId, message: userMessage, text, attachments: [...state.attachments] };
    conversation.messages.push(userMessage);
    if (conversation.title === 'New conversation') conversation.title = content.slice(0, 55);
    state.attachments = []; $('message-input').value = ''; $('message-input').style.height = ''; state.busy = true; feedback('');
    const controller = new AbortController(); const requestId = ++state.requestId; state.request = controller; save(); render(); scrollDown();
    try {
      const result = await api('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode: state.mode, messages: previous, text: content, attachments: files }), signal: controller.signal });
      if (requestId !== state.requestId || conversationId !== state.currentId) return;
      if (typeof result.text !== 'string' || !result.text.trim()) throw new Error('The model did not return a text response. Please try again.');
      state.pendingDraft = null;
      conversation.messages.push({ role: 'assistant', content: result.text, citations: result.citations || [], receipts: result.receipts || [], model: result.model, incomplete: result.incomplete === true, created: Date.now() }); save(); renderMessages(); renderHistory(); scrollDown();
    } catch (error) { if (requestId === state.requestId && error.name !== 'AbortError') { restorePendingDraft(true); renderMessages(); renderAttachments(); feedback(error.message + ' Your draft and files have been kept for retry.'); } }
    finally { if (requestId === state.requestId) { state.busy = false; state.request = null; updateControls(); } }
  }
  function dataUrl(blob) { return new Promise((resolve, reject) => { const reader = new FileReader(); reader.onerror = () => reject(new Error('The file could not be read.')); reader.onload = () => resolve(reader.result); reader.readAsDataURL(blob); }); }
  async function sha256(file) { const bytes = await file.arrayBuffer(); const hash = await crypto.subtle.digest('SHA-256', bytes); return Array.from(new Uint8Array(hash), b => b.toString(16).padStart(2, '0')).join(''); }
  function waitEvent(target, name, timeout = 20000) { return new Promise((resolve, reject) => { const timer = setTimeout(() => done(new Error('Media decoding took too long. Try a smaller file or another format.')), timeout); function clean() { clearTimeout(timer); target.removeEventListener(name, ok); target.removeEventListener('error', fail); } function done(error) { clean(); error ? reject(error) : resolve(); } function ok() { done(); } function fail() { done(new Error('This browser could not decode the media file.')); } target.addEventListener(name, ok, { once: true }); target.addEventListener('error', fail, { once: true }); }); }
  function canvasImage(source, width, height, maxBytes = 8 * 1024 * 1024) {
    if (!width || !height) throw new Error('This file has no readable image dimensions.');
    const canvas = document.createElement('canvas'); const context = canvas.getContext('2d');
    if (!context) throw new Error('Image processing is unavailable in this browser.');
    let ratio = Math.min(1, 1600 / Math.max(width, height));
    // Match the server's decoded-byte bound, including high-detail video frames.
    for (let scale = 0; scale < 6; scale++) {
      canvas.width = Math.max(1, Math.round(width * ratio)); canvas.height = Math.max(1, Math.round(height * ratio));
      context.fillStyle = '#fff'; context.fillRect(0, 0, canvas.width, canvas.height); context.drawImage(source, 0, 0, canvas.width, canvas.height);
      for (const quality of [0.85, 0.7, 0.55, 0.4]) {
        const result = canvas.toDataURL('image/jpeg', quality);
        if (!result.startsWith('data:image/jpeg;base64,')) throw new Error('JPEG processing is unavailable in this browser.');
        const encoded = result.slice(result.indexOf(',') + 1);
        const bytes = encoded.length / 4 * 3 - (encoded.endsWith('==') ? 2 : encoded.endsWith('=') ? 1 : 0);
        if (bytes <= maxBytes) return result;
      }
      ratio *= 0.7;
    }
    throw new Error('The image could not be compressed within the upload limit. Try a smaller file.');
  }
  async function prepareImage(file) { const url = URL.createObjectURL(file); const image = new Image(); try { const loaded = waitEvent(image, 'load'); image.src = url; await loaded; return canvasImage(image, image.naturalWidth, image.naturalHeight); } finally { URL.revokeObjectURL(url); } }
  async function prepareVideo(file) {
    const video = document.createElement('video'); const url = URL.createObjectURL(file); video.muted = true; video.playsInline = true; video.preload = 'auto';
    try {
      const loaded = waitEvent(video, 'loadeddata'); video.src = url; video.load(); await loaded;
      if (!Number.isFinite(video.duration) || video.duration <= 0 || video.duration > 1200) throw new Error('Use a video shorter than 20 minutes with a readable duration.');
      const duration = video.duration, frames = [];
      for (let index = 0; index < 6; index++) {
        const timestamp = duration * index / 6;
        if (Math.abs(video.currentTime - timestamp) > 0.001) { const sought = waitEvent(video, 'seeked'); video.currentTime = timestamp; await sought; }
        frames.push({ timestamp, dataUrl: canvasImage(video, video.videoWidth, video.videoHeight, 512 * 1024) });
      }
      return { duration, frames };
    } finally { video.removeAttribute('src'); video.load(); URL.revokeObjectURL(url); }
  }
  async function prepareFile(file) {
    const extension = file.name.split('.').pop().toLowerCase(); const name = file.name.slice(0, 200);
    if (!file.size) throw new Error(`${name} is empty.`);
    if (['txt', 'md', 'csv', 'json'].includes(extension)) { if (file.size > 200 * 1024) throw new Error(`${name}: text files must be 200 KB or smaller.`); const text = await file.text(); if (text.includes('\0')) throw new Error(`${name}: this does not appear to be a plain text document.`); return { name, kind: 'text', text, sha256: await sha256(file), description: `${extension.toUpperCase()} · ${Math.ceil(file.size / 1024)} KB of text` }; }
    if (['png', 'jpg', 'jpeg', 'webp'].includes(extension)) { if (file.size > 8 * 1024 * 1024) throw new Error(`${name}: images must be 8 MB or smaller.`); return { name, kind: 'image', dataUrl: await prepareImage(file), sha256: await sha256(file), description: 'Image · resized to at most 1600 px' }; }
    if (extension === 'pdf') { if (file.size > 8 * 1024 * 1024) throw new Error(`${name}: PDFs must be 8 MB or smaller.`); const header = new TextDecoder().decode(await file.slice(0, 5).arrayBuffer()); if (header !== '%PDF-') throw new Error(`${name}: this file does not have a PDF header.`); const url = await dataUrl(new Blob([file], { type: 'application/pdf' })); return { name, kind: 'pdf', dataUrl: url, sha256: await sha256(file), description: `PDF · ${Math.ceil(file.size / 1024)} KB · model review required` }; }
    if (['mp4', 'webm'].includes(extension)) { if (file.size > 50 * 1024 * 1024) throw new Error(`${name}: videos must be 50 MB or smaller.`); const result = await prepareVideo(file); return { name, kind: 'video', ...result, sha256: await sha256(file), description: `6 sampled frames · ${Math.round(result.duration)} s · no audio` }; }
    throw new Error(`${name}: use PNG, JPEG, WebP, MP4, WebM, PDF, TXT, Markdown, CSV or JSON. Export Word documents as PDF first.`);
  }
  async function handleFiles(event) {
    const files = Array.from(event.target.files || []); event.target.value = ''; if (!files.length || state.busy || state.processing) return;
    const batch = ++state.fileBatch; state.processing = true; feedback(''); updateControls(); const errors = [];
    try {
      for (const file of files) {
        if (batch !== state.fileBatch) return;
        if (state.attachments.length >= MAX_FILES) { errors.push('Attach up to 3 files per message.'); break; }
        try { const prepared = await prepareFile(file); if (batch !== state.fileBatch) return; if (JSON.stringify([...state.attachments, prepared]).length > MAX_PAYLOAD) throw new Error('The prepared files exceed 20 MB. Remove a file or use a smaller one.'); state.attachments.push(prepared); renderAttachments(); } catch (error) { errors.push(error.message); }
      }
    } finally { if (batch === state.fileBatch) { state.processing = false; updateControls(); if (errors.length) feedback(errors.join(' ')); } }
  }
  function openDialog(name) { const dialog = $(name); if (!dialog.open) dialog.showModal(); }
  function closeSidebar() { $('sidebar').classList.remove('open'); $('sidebar-backdrop').hidden = true; $('menu-button').setAttribute('aria-expanded', 'false'); }
  function exportConversation(format) {
    const c = current(); let content, mime;
    if (format === 'json') { content = JSON.stringify({ app: 'SOLRDM Web', exportedAt: new Date().toISOString(), attachmentFilesIncluded: false, conversation: c }, null, 2); mime = 'application/json'; }
    else { content = '# ' + c.title + '\n\n' + c.messages.map(m => `## ${m.role === 'user' ? 'You' : 'SOLRDM'}\n\n${m.incomplete === true ? '[Incomplete response]\n\n' : ''}${m.content}\n` + (m.attachments?.length ? '\nAttachments (files not included):\n' + m.attachments.map(a => `- ${a.name} (${a.description || a.kind}) · SHA-256 ${a.sha256 || 'unavailable'}`).join('\n') + '\n' : '') + (m.citations?.length ? '\nSources:\n' + m.citations.map(s => `- ${s.title || s.url}: ${s.url}`).join('\n') + '\n' : '') + (m.receipts?.length ? '\nTool results:\n```json\n' + JSON.stringify(m.receipts, null, 2) + '\n```\n' : '')).join('\n'); mime = 'text/markdown'; }
    const url = URL.createObjectURL(new Blob([content], { type: mime })); const link = node('a'); link.href = url; link.download = (c.title.replace(/[^a-z0-9_-]/gi, '-').slice(0, 50) || 'solrdm-conversation') + (format === 'json' ? '.json' : '.md'); document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); $('export-dialog').close();
  }
  const toolConfigurations = {
    simulate_projectile: { fields: [['speed', 'Launch speed (m/s)', 20, 0, 10000], ['angle', 'Launch angle (degrees)', 45, 0, 90], ['gravity', 'Gravity (m/s²)', 9.81, 0.001, 1000]], help: 'A point mass launched from ground level with constant gravity and no air resistance.' },
    simulate_oscillator: { fields: [['mass', 'Mass (kg)', 1, 0.001, 100000], ['spring', 'Spring constant (N/m)', 4, 0.001, 1000000], ['damping', 'Damping (N·s/m)', 0.2, 0, 1000000], ['x0', 'Initial displacement (m)', 1, -1000000, 1000000], ['v0', 'Initial velocity (m/s)', 0, -1000000, 1000000], ['duration', 'Duration (s)', 10, 0.001, 3600]], help: 'A linear mass–spring system with viscous damping. Inspect the model assumptions with the result.' },
    describe_statistics: { text: 'numbers', label: 'Numbers, separated by commas or spaces', value: '12, 15, 18, 18, 21, 24, 28', help: 'Up to 1,000 finite numbers. These are descriptive statistics, not a causal explanation.' },
    compare_options: { text: 'comparison', label: 'Criteria, weights and option scores (JSON)', value: JSON.stringify({ criteria: [{ name: 'Cost', weight: 0.4 }, { name: 'Quality', weight: 0.6 }], options: [{ name: 'Option A', scores: [8, 6] }, { name: 'Option B', scores: [5, 9] }] }, null, 2), help: 'Score each criterion from 0–10, with higher always better. Scores follow the same order as criteria. This compares your assumptions; it does not choose values for you.' },
    research_papers: { text: 'query', label: 'Research topic', value: '', placeholder: 'For example: solid-state battery cycle life', help: 'Search Crossref paper metadata. Results may include abstracts and DOI links; this does not retrieve or review full papers.' }
  };
  function renderToolFields() {
    const name = $('tool-select').value, config = toolConfigurations[name], parent = $('tool-fields'); parent.replaceChildren();
    state.toolReceipt = null; $('save-tool-result').disabled = true; $('tool-result').replaceChildren(); $('tool-status').textContent = '';
    if (config.fields) config.fields.forEach(([key, label, value, min, max]) => { const container = node('div'); const input = node('input'); input.type = 'number'; input.name = key; input.id = 'tool-' + key; input.value = value; input.step = 'any'; input.min = min; input.max = max; input.required = true; const l = node('label', 'field-label', label); l.htmlFor = input.id; container.append(l, input); parent.append(container); });
    else { const container = node('div', 'full-width'); const input = node(config.text === 'query' ? 'input' : 'textarea'); input.name = config.text; input.id = 'tool-' + config.text; input.value = config.value; input.required = true; input.maxLength = config.text === 'query' ? 300 : 20000; if (config.placeholder) input.placeholder = config.placeholder; const label = node('label', 'field-label', config.label); label.htmlFor = input.id; container.append(label, input); parent.append(container); }
    parent.append(node('p', 'tool-help', config.help)); $('run-tool').textContent = name === 'research_papers' ? 'Find papers ↗' : 'Run calculation ↗';
  }
  async function runTool(event) {
    event.preventDefault(); if (state.toolBusy) return; const name = $('tool-select').value; const data = new FormData($('tool-form')); let args;
    try { if (name === 'describe_statistics') { const raw = data.get('numbers').trim(); args = { numbers: raw.split(/[\s,;]+/).filter(Boolean).map(Number) }; if (!args.numbers.every(Number.isFinite)) throw new Error('Use finite numbers separated by spaces or commas.'); }
      else if (name === 'compare_options') args = JSON.parse(data.get('comparison'));
      else if (name === 'research_papers') args = { query: data.get('query').trim() };
      else args = Object.fromEntries([...data].map(([key, value]) => [key, Number(value)]));
    } catch (error) { $('tool-status').textContent = error instanceof SyntaxError ? 'The comparison JSON is invalid. Check quotes, commas and brackets.' : error.message; return; }
    state.toolBusy = true; state.toolReceipt = null; $('save-tool-result').disabled = true; $('run-tool').disabled = true; $('tool-select').disabled = true; $('tool-result').replaceChildren(); $('tool-status').textContent = name === 'research_papers' ? 'Looking up paper metadata…' : 'Running the calculation…';
    try { const result = await api('/api/tools', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, args }) }); const receipt = result.receipt || result; state.toolReceipt = receipt; $('tool-result').append(renderReceipt(receipt)); $('tool-status').textContent = receipt.status === 'completed' ? 'Result recorded.' : 'The tool did not complete.'; $('save-tool-result').disabled = receipt.status !== 'completed'; }
    catch (error) { $('tool-status').textContent = error.message; }
    finally { state.toolBusy = false; $('run-tool').disabled = false; $('tool-select').disabled = false; }
  }
  $('new-chat').addEventListener('click', () => makeConversation());
  $('nav-chat').addEventListener('click', () => closeSidebar());
  $('menu-button').addEventListener('click', () => { $('sidebar').classList.add('open'); $('sidebar-backdrop').hidden = false; $('menu-button').setAttribute('aria-expanded', 'true'); });
  $('sidebar-backdrop').addEventListener('click', closeSidebar);
  ['settings-button', 'setup-details', 'capabilities-link'].forEach(name => $(name).addEventListener('click', () => { closeSidebar(); openDialog('settings-dialog'); }));
  ['nav-workbench', 'starter-simulate'].forEach(name => $(name).addEventListener('click', () => { closeSidebar(); openDialog('workbench-dialog'); }));
  document.querySelectorAll('[data-close-dialog]').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
  document.querySelectorAll('.mode-button').forEach(button => button.addEventListener('click', () => setMode(button.dataset.mode)));
  document.querySelectorAll('.starter[data-prompt]').forEach(button => button.addEventListener('click', () => { setMode(button.dataset.mode); $('message-input').value = button.dataset.prompt; $('message-input').focus(); updateControls(); }));
  $('refresh-status').addEventListener('click', refreshStatus);
  $('composer-form').addEventListener('submit', submitMessage); $('stop-button').addEventListener('click', () => stopRequest());
  $('message-input').addEventListener('input', () => { $('message-input').style.height = 'auto'; $('message-input').style.height = Math.min($('message-input').scrollHeight, 150) + 'px'; updateControls(); });
  $('message-input').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && !matchMedia('(pointer: coarse)').matches) { event.preventDefault(); $('composer-form').requestSubmit(); } });
  $('attach-button').addEventListener('click', () => $('file-input').click()); $('file-input').addEventListener('change', handleFiles);
  $('rename-chat').addEventListener('click', () => { $('title-input').value = current().title; openDialog('rename-dialog'); $('title-input').select(); });
  $('rename-form').addEventListener('submit', event => { event.preventDefault(); const title = $('title-input').value.trim(); if (!title) return; current().title = title.slice(0, 80); save(); render(); $('rename-dialog').close(); });
  $('clear-chat').addEventListener('click', () => { if (!current().messages.length || confirm('Clear the messages in this conversation from this browser? Export first if you want to keep them.')) { stopRequest(false); current().messages = []; state.attachments = []; state.fileBatch++; state.processing = false; save(); feedback(''); render(); } });
  $('export-button').addEventListener('click', () => openDialog('export-dialog')); $('export-json').addEventListener('click', () => exportConversation('json')); $('export-markdown').addEventListener('click', () => exportConversation('markdown'));
  $('tool-select').addEventListener('change', renderToolFields); $('tool-form').addEventListener('submit', runTool);
  $('save-tool-result').addEventListener('click', () => { if (!state.toolReceipt) return; const receipt = state.toolReceipt; current().messages.push({ role: 'assistant', content: 'Workbench result: ' + receipt.summary, receipts: [receipt], created: Date.now() }); if (current().title === 'New conversation') current().title = String(receipt.tool || 'Workbench').replaceAll('_', ' '); save(); render(); scrollDown(); $('workbench-dialog').close(); feedback('Tool result added to this conversation.', true); });
  document.addEventListener('keydown', event => { if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); makeConversation(); $('message-input').focus(); } if (event.key === 'Escape') closeSidebar(); });
  load(); render(); renderToolFields(); refreshStatus();
})();
