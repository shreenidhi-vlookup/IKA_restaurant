import { api } from '../api.js';

const activeJob = job => ['queued', 'processing'].includes(job.status);
const query = (branch, date) => `branch=${encodeURIComponent(branch)}&selected_date=${encodeURIComponent(date)}`;
const initial = (branch = '', businessDate = '') => ({ branch, businessDate, loading: false, busy: false, error: '', notice: '', verification: null, files: [], unassigned: [], tickets: [], dockets: [], batches: [], csvName: '', pendingCsv: null, ticketReport: null, ticketReportName: '', warnings: { ticket: '', docket: '' }, pendingResolution: null, history: [], historyOpen: false, historyLoading: false, historyLoaded: false, historyError: '' });

export function imageSelection(kind, files) {
  const accepted = [], rejected = [];
  for (const file of files) {
    const name = file.name.toLowerCase();
    if ((kind === 'ticket' && name.includes('docket')) || (kind === 'docket' && name.includes('ticket'))) rejected.push(file.name);
    else accepted.push(file);
  }
  return { accepted, warning: rejected.length ? `${rejected.join(', ')}: this filename looks like ${kind === 'ticket' ? 'a docket; use Docket photos' : 'a ticket; use Ticket screenshots'} instead.` : '' };
}

// All network traffic uses the unchanged original API helper and existing routes.
// The controller stays mounted across section changes; context changes invalidate old responses.
export function createImportsController({ request = api, schedule = setTimeout, cancel = clearTimeout, wait = ms => new Promise(resolve => setTimeout(resolve, ms)), replacementTimeout = 180000 } = {}) {
  let state = initial(), generation = 0, revision = 0, abort, timer, running = false;
  const listeners = new Set();
  const publish = update => { state = { ...state, ...update }; listeners.forEach(listener => listener()); };
  const current = token => running && token === generation;
  const read = url => request(url, { signal: abort.signal });
  const needsPolling = () => state.batches.some(batch => batch.jobs.some(activeJob)) || state.files.some(activeJob);
  const batchUpdate = (batch, kind) => publish({ batches: [...state.batches.filter(item => item.batch_id !== batch.batch_id), { ...batch, kind }] });

  async function refresh(quiet = false) {
    if (!running || !state.branch) return false;
    const token = generation, requestRevision = ++revision;
    if (!quiet) publish({ loading: true });
    try {
      const scope = query(state.branch, state.businessDate);
      const [verification, files, unassigned, tickets, dockets] = await Promise.all([read(`/verification?${scope}`), read(`/uploads?${scope}`), read(`/tickets/unassigned?${scope}`), read(`/tickets?${scope}`), read(`/dockets?${scope}`)]);
      if (!current(token) || requestRevision !== revision) return false;
      publish({ verification, files, unassigned, tickets, dockets, loading: false });
      return true;
    } catch (error) {
      if (current(token) && requestRevision === revision) publish({ error: error.message, loading: false });
      return false;
    }
  }

  function pollSoon() {
    cancel(timer);
    if (running && needsPolling()) timer = schedule(poll, 2000);
  }
  async function poll() {
    const token = generation;
    try {
      for (const batch of state.batches.filter(item => item.jobs.some(activeJob))) {
        const latest = await read(`/upload/jobs/${encodeURIComponent(batch.batch_id)}`);
        if (!current(token)) return;
        batchUpdate(latest, batch.kind);
      }
      if (current(token)) await refresh(true);
    } catch (error) {
      if (current(token)) publish({ error: `${error.message} Processing status will be checked again.` });
    } finally { if (current(token)) pollSoon(); }
  }

  async function mutate(work, { evidence = false } = {}) {
    if (!running || state.busy) return;
    if (!state.branch) { publish({ error: 'Select a restaurant branch first.' }); return; }
    if (evidence && !state.verification?.has_import) { publish({ error: 'Import a till CSV for this date first.' }); return; }
    const token = generation;
    publish({ busy: true, error: '', notice: '' });
    const body = () => { const form = new FormData(); form.append('branch', state.branch); form.append('selected_date', state.businessDate); return form; };
    try { await work({ token, body }); }
    catch (error) { if (current(token)) publish({ error: error.message }); }
    finally { if (current(token)) { publish({ busy: false }); pollSoon(); } }
  }

  async function uploadCsv(file, confirm = false) {
    if (!file) return;
    return mutate(async ({ token, body }) => {
      const form = body(); form.append('file', file); form.append('confirm_date_mismatch', String(confirm));
      const result = await request('/csv', { method: 'POST', body: form });
      if (!current(token)) return;
      if (result.confirmation_required) { publish({ pendingCsv: { file, result } }); return; }
      publish({ pendingCsv: null, csvName: file.name, historyLoaded: false, notice: `${file.name}: ${result.saved_rows} till rows imported.` });
      await refresh(true);
    });
  }

  async function uploadReport(file) {
    if (!file) return;
    return mutate(async ({ token, body }) => {
      const form = body(); form.append('file', file);
      const ticketReport = await request('/ticket-report', { method: 'POST', body: form });
      if (current(token)) publish({ ticketReport, ticketReportName: file.name, notice: `${file.name}: ${ticketReport.total_tickets} tickets processed; ${ticketReport.unpaid_count} unpaid.` });
    });
  }

  async function uploadImages(kind, files) {
    if (!['ticket', 'docket'].includes(kind) || !files?.length) return;
    return mutate(async ({ token, body }) => {
      const { accepted, warning } = imageSelection(kind, Array.from(files));
      publish({ warnings: { ...state.warnings, [kind]: warning } });
      if (!accepted.length) return;
      if (accepted.length > 30) throw new Error('Upload accepts at most 30 images per batch.');
      const form = body(); accepted.forEach(file => form.append('files', file));
      const batch = await request(`/upload/${kind === 'ticket' ? 'tickets' : 'dockets'}`, { method: 'POST', body: form });
      if (!current(token)) return;
      batchUpdate(batch, kind);
      publish({ notice: `${batch.total} ${kind} image(s) submitted. Extraction results appear below.` });
      await refresh(true);
    }, { evidence: true });
  }

  async function deleteFile(item) {
    if (!['ticket', 'docket'].includes(item.kind)) return;
    return mutate(async ({ token }) => {
      if (activeJob(item)) throw new Error('Wait for extraction to finish before deleting this image.');
      await request(`/uploads/${item.kind}/${encodeURIComponent(item.stored_filename)}`, { method: 'DELETE' });
      if (!current(token)) return;
      publish({ notice: `${item.original_filename || item.stored_filename} deleted.` });
      await refresh(true);
    });
  }

  async function replaceFile(item, file) {
    if (!file || !['ticket', 'docket'].includes(item.kind)) return;
    return mutate(async ({ token, body }) => {
      const form = body(); form.append('files', file);
      let batch = await request(`/upload/${item.kind === 'ticket' ? 'tickets' : 'dockets'}`, { method: 'POST', body: form });
      if (!current(token)) return;
      batchUpdate(batch, item.kind);
      if (batch.jobs[0]?.message === 'Duplicate, skipped') { publish({ notice: 'Duplicate image skipped. The original image is unchanged.' }); return; }
      const started = Date.now();
      while (batch.jobs.some(activeJob)) {
        if (Date.now() - started >= replacementTimeout) throw new Error('Replacement is still processing. The original is retained; review the uploaded images before retrying.');
        await wait(1800);
        if (!current(token)) return;
        batch = await read(`/upload/jobs/${encodeURIComponent(batch.batch_id)}`);
        if (!current(token)) return;
        batchUpdate(batch, item.kind);
      }
      if (!current(token)) return;
      const job = batch.jobs[0];
      if (job?.status !== 'done' || !job.provider) {
        await refresh(true);
        throw new Error(`${job?.error || 'Replacement image was not extracted.'} The original image is still saved.`);
      }
      await request(`/uploads/${item.kind}/${encodeURIComponent(item.stored_filename)}`, { method: 'DELETE' });
      if (current(token)) { publish({ notice: `${file.name} replaced ${item.original_filename || item.stored_filename}.` }); await refresh(true); }
    });
  }

  async function resolveScreenshot(item, ticketId, confirm = false) {
    return mutate(async ({ token, body }) => {
      const form = body(); form.append('filename', item.filename); form.append('ticket_id', ticketId); form.append('confirm_mismatch', String(confirm));
      try {
        const result = await request('/tickets/resolve', { method: 'POST', body: form });
        if (current(token)) { publish({ pendingResolution: null, notice: `Screenshot assigned to ${result.ticket_id}.` }); await refresh(true); }
      } catch (error) {
        let detail;
        try { detail = JSON.parse(error.message); } catch { /* Preserve ordinary API errors. */ }
        if (detail?.confirmation_required && current(token)) publish({ pendingResolution: { item, ticketId, warnings: detail.warnings || [] } });
        else throw error;
      }
    });
  }

  async function loadHistory(open = false) {
    if (!running || !state.branch || state.historyLoading) return;
    const token = generation;
    publish({ historyLoading: true, historyError: '' });
    try {
      const result = await read(`/verification/dates?branch=${encodeURIComponent(state.branch)}`);
      if (current(token)) publish({ history: result.dates || [], historyOpen: open || state.historyOpen, historyLoaded: true });
    } catch (error) { if (current(token)) publish({ historyError: error.message }); }
    finally { if (current(token)) publish({ historyLoading: false }); }
  }

  async function toggleHistory() {
    if (state.historyOpen) { publish({ historyOpen: false }); return; }
    return loadHistory(true);
  }

  function stop() { running = false; generation++; revision++; abort?.abort(); cancel(timer); }
  async function setContext(branch, businessDate) {
    stop(); running = true; abort = new AbortController();
    publish(initial(branch, businessDate));
    if (branch) { await refresh(); pollSoon(); }
  }
  return {
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    getSnapshot: () => state,
    setContext, stop, refresh: async () => { publish({ error: '' }); const result = await refresh(); pollSoon(); return result; },
    uploadCsv, uploadReport, uploadImages, deleteFile, replaceFile, resolveScreenshot, toggleHistory, loadHistory,
    cancelCsv: () => publish({ pendingCsv: null }), cancelResolution: () => publish({ pendingResolution: null }),
  };
}
