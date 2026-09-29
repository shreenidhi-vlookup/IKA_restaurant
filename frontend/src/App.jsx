import { useCallback, useEffect, useState } from 'react';
import './App.css';

const BRANCHES = ['Haweli Restaurant Southall', 'Haweli Restaurant Norbury', 'Haweli Ilford Ltd'];
const today = new Date().toISOString().slice(0, 10);

async function api(url, options = {}) {
  const response = await fetch(`/api${url}`, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || 'Request failed'));
  return data;
}

function parseJson(value, fallback = []) {
  try { return JSON.parse(value || JSON.stringify(fallback)); } catch { return fallback; }
}

async function copyText(text) {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text);
  const field = document.createElement('textarea');
  field.value = text;
  field.style.position = 'fixed';
  field.style.opacity = '0';
  document.body.appendChild(field);
  field.select();
  const copied = document.execCommand('copy');
  field.remove();
  if (!copied) throw new Error('Could not copy to clipboard');
}

export default function App() {
  const [branch, setBranch] = useState('');
  const [date, setDate] = useState(today);
  const [summary, setSummary] = useState(null);
  const [rows, setRows] = useState([]);
  const [tickets, setTickets] = useState([]);
  const [dockets, setDockets] = useState([]);
  const [uploadedFiles, setUploadedFiles] = useState([]);
  const [active, setActive] = useState('');
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [csvName, setCsvName] = useState('');
  const [pendingCsv, setPendingCsv] = useState(null);
  const [dateWarning, setDateWarning] = useState(null);
  const [uploads, setUploads] = useState({ ticket: '', docket: '' });
  const [uploadBatches, setUploadBatches] = useState({ ticket: null, docket: null });
  const [unassigned, setUnassigned] = useState([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyDates, setHistoryDates] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [copiedKey, setCopiedKey] = useState('');
  const [managingKind, setManagingKind] = useState('');
  const [previewUpload, setPreviewUpload] = useState(null);

  const refresh = useCallback(async () => {
    if (!branch || !date) return;
    const data = await api(`/verification?branch=${encodeURIComponent(branch)}&selected_date=${date}`);
    setRows(data.rows || []);
    setSummary(data.has_import ? data.summary : null);
    const [pending, savedTickets, savedDockets, files] = await Promise.all([
      api(`/tickets/unassigned?branch=${encodeURIComponent(branch)}&selected_date=${date}`),
      api(`/tickets?branch=${encodeURIComponent(branch)}&selected_date=${date}`),
      api(`/dockets?branch=${encodeURIComponent(branch)}&selected_date=${date}`),
      api(`/uploads?branch=${encodeURIComponent(branch)}&selected_date=${date}`),
    ]);
    setUnassigned(pending);
    setTickets(savedTickets || []);
    setDockets(savedDockets || []);
    setUploadedFiles(files || []);
  }, [branch, date]);

  useEffect(() => { refresh().catch((e) => setError(e.message)); }, [refresh]);

  const submitCsv = async (file, confirm = false) => {
    setBusy(true); setError('');
    const body = new FormData();
    body.append('branch', branch); body.append('selected_date', date); body.append('file', file);
    body.append('confirm_date_mismatch', String(confirm));
    try {
      const result = await api('/csv', { method: 'POST', body });
      if (result.confirmation_required) { setDateWarning(result); setPendingCsv(file); return; }
      setDateWarning(null); setPendingCsv(null); setCsvName(file.name);
      await refresh();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  const uploadImages = async (kind, files) => {
    setBusy(true); setError('');
    const body = new FormData(); files.forEach((file) => body.append('files', file));
    body.append('branch', branch); body.append('selected_date', date);
    try {
      const result = await api(`/upload/${kind === 'ticket' ? 'tickets' : 'dockets'}`, { method: 'POST', body });
      setUploadBatches((old) => ({ ...old, [kind]: result }));
      setUploads((old) => ({ ...old, [kind]: `${result.total} file(s) submitted` }));
      await refresh();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  const ticketBatchId = uploadBatches.ticket?.batch_id || '';
  const docketBatchId = uploadBatches.docket?.batch_id || '';
  useEffect(() => {
    const batchIds = [['ticket', ticketBatchId], ['docket', docketBatchId]].filter(([, id]) => id);
    if (!batchIds.length) return undefined;
    let stopped = false;
    const poll = async () => {
      let stillActive = false;
      let changed = false;
      for (const [kind, batchId] of batchIds) {
        try {
          const latest = await api(`/upload/jobs/${batchId}`);
          if (stopped) return;
          const previous = uploadBatches[kind]?.jobs || [];
          changed ||= latest.jobs.some((job) => {
            const before = previous.find((item) => item.job_id === job.job_id);
            return before && before.status !== job.status;
          });
          setUploadBatches((old) => old[kind]?.batch_id === batchId ? { ...old, [kind]: latest } : old);
          stillActive ||= latest.jobs.some((job) => job.status === 'queued' || job.status === 'processing');
        } catch (e) { setError(e.message); }
      }
      if (changed) refresh().catch((e) => setError(e.message));
      if (!stillActive) stopped = true;
    };
    poll();
    const timer = window.setInterval(() => { if (!stopped) poll(); }, 2000);
    return () => { stopped = true; window.clearInterval(timer); };
  }, [ticketBatchId, docketBatchId, refresh]);

  const resolveScreenshot = async (item, confirm = false, enteredId = '') => {
    const id = enteredId || window.prompt('Enter the ticket ID (YYMMDD-N) for this screenshot:');
    if (!id) return;
    const body = new FormData(); body.append('filename', item.filename); body.append('branch', branch); body.append('selected_date', date); body.append('ticket_id', id); body.append('confirm_mismatch', String(confirm));
    try { await api('/tickets/resolve', { method: 'POST', body }); await refresh(); }
    catch (e) {
      if (e.message.includes('confirmation_required') && window.confirm('The ticket branch or day differs from your selection. Save it anyway?')) await resolveScreenshot(item, true, id);
      else setError(e.message);
    }
  };

  const boxes = summary ? [
    { key: 'total', title: 'Total', value: `${summary.item_rows} rows`, note: `${summary.quantity} items` },
    { key: 'void', title: 'Void', value: `${summary.void.flagged_rows} rows`, note: `£${summary.void.amount.toFixed(2)} · ${summary.void.verified} of ${summary.void.total} verified` },
    { key: 'cancel', title: 'Cancel', value: `${summary.cancel.flagged_rows} rows`, note: `£${summary.cancel.amount.toFixed(2)} · ${summary.cancel.verified} of ${summary.cancel.total} verified` },
    { key: 'promotions', title: 'Promotions', value: summary.promotions_in_file ? `${summary.promotions.flagged_rows} rows` : 'Not in file', note: summary.promotions_in_file ? `£${summary.promotions.amount.toFixed(2)} · ${summary.promotions.verified} of ${summary.promotions.total} verified` : 'Promotion column not present' },
    { key: 'status', title: 'Status', value: summary.status.label, note: `${summary.status.verified} of ${summary.status.total} flagged rows verified` },
  ] : [];
  const statusLabel = (row, key) => row.matches?.[key]?.status?.replace('_', ' ') || row.row_status?.replace('_', ' ') || 'pending';
  const showDetail = (row, key) => setDetail({ row, key: key === 'promotions' ? 'promotion' : key });
  const rowsFor = (key) => rows.filter((row) => key === 'total' ? true : key === 'status' ? (row.void_count > 0 || row.cancel_count > 0 || row.promotion_count > 0) && row.row_status !== 'verified' : row[`${key === 'promotions' ? 'promotion' : key}_count`] > 0);
  const selectedRows = rowsFor(active);
  const managedFiles = uploadedFiles.filter((item) => item.kind === managingKind);

  const copySummary = async (box) => {
    const relevantRows = rowsFor(box.key);
    const lines = [
      `TIL System — ${box.title} details`,
      `Branch: ${branch || '—'}`,
      `Date: ${date}`,
      box.value,
      box.note,
      '',
      ...relevantRows.map((row) => `${row.product} | Qty ${row.quantity} | ${row.user_name} | ${row.department} | ${row.till} | £${Number(row.sales_value || 0).toFixed(2)} | ${statusLabel(row, box.key)}`),
    ];
    try { await copyText(lines.join('\n')); setCopiedKey(`box-${box.key}`); }
    catch (e) { setError(e.message); }
    window.setTimeout(() => setCopiedKey(''), 1600);
  };

  const copyDetail = async () => {
    if (!detail) return;
    const row = detail.row;
    const lines = [
      `TIL System — ${detail.key.toUpperCase()} detail`,
      `Branch: ${branch}`, `Date: ${row.row_date || date}`, `Item: ${row.product}`,
      `Quantity: ${row.quantity}`, `User: ${row.user_name}`, `Department: ${row.department}`,
      `Till: ${row.till}`, `Value: £${Number(row.sales_value || 0).toFixed(2)}`,
      `Status: ${row.row_status?.replace('_', ' ') || 'pending'}`,
    ];
    for (const candidate of row.candidates || []) {
      const ticket = candidate.ticket;
      const item = candidate.ticket_item;
      const docket = candidate.docket;
      if (ticket) lines.push('', `Ticket ${ticket.ticket_id}`, `Terminal: ${ticket.terminal || '—'}`, `Table: ${ticket.table_name || '—'}`, `Ticket item: ${item?.name || '—'} | Qty ${item?.quantity || item?.qty || '—'} | Total ${item?.total || '—'} | Void ${item?.is_void ? 'Yes' : 'No'}`);
      if (docket) lines.push('', `Docket order ${docket.docket_order_no || '—'}`, `Date/time: ${docket.docket_date || '—'} ${docket.docket_time || ''}`, `Department/staff: ${docket.department || '—'} / ${docket.staff_name || '—'}`, `Description: ${docket.handwritten_reason || 'No description'}`);
    }
    try { await copyText(lines.join('\n')); setCopiedKey('detail'); }
    catch (e) { setError(e.message); }
    window.setTimeout(() => setCopiedKey(''), 1600);
  };

  const deleteUploadedFile = async (item) => {
    if (!window.confirm(`Delete ${item.original_filename || item.stored_filename} and its saved extraction data?`)) return;
    try {
      await api(`/uploads/${item.kind}/${encodeURIComponent(item.stored_filename)}`, { method: 'DELETE' });
      setDetail(null);
      setPreviewUpload(null);
      await refresh();
    } catch (e) { setError(e.message); }
  };

  const replaceUploadedFile = async (item, file) => {
    if (!file || !window.confirm(`Replace ${item.original_filename || item.stored_filename} with ${file.name}? The old image is removed after the new one extracts successfully.`)) return;
    setBusy(true); setError('');
    try {
      const body = new FormData();
      body.append('files', file); body.append('branch', branch); body.append('selected_date', date);
      let latest = await api(`/upload/${item.kind === 'ticket' ? 'tickets' : 'dockets'}`, { method: 'POST', body });
      setUploadBatches((old) => ({ ...old, [item.kind]: latest }));
      setUploads((old) => ({ ...old, [item.kind]: `Replacing ${item.original_filename || item.stored_filename}` }));
      await refresh();
      if (latest.jobs?.[0]?.message === 'Duplicate, skipped') return;
      while (latest.jobs?.some((job) => job.status === 'queued' || job.status === 'processing')) {
        await new Promise((resolve) => window.setTimeout(resolve, 1800));
        latest = await api(`/upload/jobs/${latest.batch_id}`);
        setUploadBatches((old) => ({ ...old, [item.kind]: latest }));
      }
      const replacementJob = latest.jobs?.[0];
      if (replacementJob?.status === 'done' && replacementJob.provider) {
        await api(`/uploads/${item.kind}/${encodeURIComponent(item.stored_filename)}`, { method: 'DELETE' });
        setPreviewUpload(null);
      } else {
        setError(replacementJob?.error || 'Replacement image was not extracted; the original image is still saved.');
      }
      await refresh();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  const toggleHistory = async () => {
    if (historyOpen) { setHistoryOpen(false); return; }
    if (!branch) return;
    setHistoryLoading(true);
    setError('');
    try {
      const result = await api(`/verification/dates?branch=${encodeURIComponent(branch)}`);
      setHistoryDates(result.dates || []);
      setHistoryOpen(true);
    } catch (e) { setError(e.message); }
    finally { setHistoryLoading(false); }
  };

  return <div className="app-shell">
    <header className="topbar"><div className="brand-mark">T</div><div><span className="eyebrow">TIL SYSTEM · VERIFICATION</span><h1>Discrepancy review</h1></div></header>
    <main>
      <section className="selection-card"><div><span className="eyebrow">WORKSPACE</span><h2>Select branch and date</h2></div><div className="selectors">
        <label>Restaurant branch<select value={branch} onChange={(e) => { setBranch(e.target.value); setSummary(null); setHistoryOpen(false); }}><option value="">Choose branch</option>{BRANCHES.map((b) => <option key={b}>{b}</option>)}</select></label>
        <label>Business date<input type="date" value={date} onChange={(e) => { setDate(e.target.value); setSummary(null); }} /></label>
      </div></section>
      <section className="history-section">
        <button className="history-button" disabled={!branch || historyLoading} onClick={toggleHistory}>{historyLoading ? 'Loading records…' : historyOpen ? 'Hide previous records' : 'View previous records'}</button>
        {historyOpen && <div className="history-panel"><div className="history-heading"><div><span className="eyebrow">SAVED CSV HISTORY</span><h3>{branch}</h3></div><span className="history-current">Selected date: {date}</span></div>
          {historyDates.filter((item) => item.date < date).length === 0 ? <p className="empty-state">No earlier CSV imports for this branch.</p> : historyDates.filter((item) => item.date < date).map((item) => <div className="history-row" key={item.date}><span><strong>{item.date}</strong><small>{item.filename || 'CSV import'} · {item.item_rows} item rows · {item.flagged_rows} discrepancy rows</small></span><button className="history-open-button" onClick={() => { setDate(item.date); setActive('total'); setHistoryOpen(false); }}>View records</button></div>)}
        </div>}
      </section>
      <section className="csv-card"><div><span className="eyebrow">STEP 1 · TILL REPORT</span><h2>Upload one CSV file</h2><p>Choose the branch and date first. Every item row is saved for this selection.</p></div>
        <label className="file-button">{busy ? 'Working…' : 'Choose CSV'}<input type="file" accept=".csv,text/csv" disabled={!branch || busy} onChange={(e) => { const file = e.target.files?.[0]; if (file) submitCsv(file); e.target.value = ''; }} /></label>
        {csvName && <span className="filename">{csvName}</span>}
      </section>
      {dateWarning && <div className="warning"><span>{dateWarning.message} CSV dates: {dateWarning.csv_dates.join(', ')}</span><button onClick={() => pendingCsv && submitCsv(pendingCsv, true)}>Confirm and import</button><button className="quiet-button" onClick={() => { setDateWarning(null); setPendingCsv(null); }}>Cancel</button></div>}
      {error && <pre className="error-banner">{error}</pre>}
      {boxes.length > 0 && <section className="summary-section"><div className="section-title"><div><span className="eyebrow">CSV SUMMARY</span><h2>Verification overview</h2></div></div>
        <div className="summary-grid">{boxes.map((box) => <div key={box.key} className={`summary-box ${active === box.key ? 'is-active' : ''}`}>
          <button className="summary-select" aria-label={`Show ${box.title} rows`} onClick={() => setActive(active === box.key ? '' : box.key)}><span className="box-title">{box.title}</span><strong>{box.value}</strong><small>{box.note}</small></button>
          <button className="copy-button box-copy" title={`Copy ${box.title} details`} aria-label={`Copy ${box.title} details`} onClick={() => copySummary(box)}>{copiedKey === `box-${box.key}` ? 'Copied' : 'Copy'}</button>
        </div>)}</div>
        {active && <div className="detail-list"><div className="list-heading"><div><span className="eyebrow">{active.toUpperCase()} ROWS</span><h3>{active === 'total' ? 'All CSV item rows' : active === 'status' ? 'Flagged rows needing attention' : `${active[0].toUpperCase()}${active.slice(1)} items`}</h3></div><button className="quiet-button" onClick={() => setActive('')}>Close</button></div>
          {selectedRows.length === 0 ? <p className="empty-state">No matching CSV rows.</p> : selectedRows.map((row) => <button key={row.id} className="csv-row" onClick={() => showDetail(row, active)}><span><strong>{row.product}</strong><small>Qty {row.quantity} · {row.user_name} · {row.department} · {row.till}</small></span><span className="row-value">£{Number(row.sales_value || 0).toFixed(2)}</span><span className={`status-pill ${statusLabel(row, active).replace(' ', '-')}`}>{statusLabel(row, active)}{row.matches?.[active === 'promotions' ? 'promotion' : active]?.total > 1 && ` · ${row.matches[active === 'promotions' ? 'promotion' : active].verified} of ${row.matches[active === 'promotions' ? 'promotion' : active].total}`}</span></button>)}
        </div>}
      </section>}
      {unassigned.length > 0 && <section className="unassigned-section"><h2>Ticket screenshots needing an ID</h2>{unassigned.map((item) => <div className="history-row" key={item.filename}><span><strong>{item.filename}</strong><small>{item.issue}</small></span><button className="history-open-button" onClick={() => resolveScreenshot(item)}>Assign ticket ID</button></div>)}</section>}
      <section className="evidence-section"><div className="section-title"><div><span className="eyebrow">STEP 2 · EVIDENCE</span><h2>Upload tickets and dockets</h2><p>Matching runs automatically after each batch is saved.</p></div></div><div className="upload-grid">
        {[['ticket','Ticket screenshots','Upload screenshots'],['docket','Docket photos','Upload dockets']].map(([kind,title,button]) => {
          const count = uploadedFiles.filter((item) => item.kind === kind).length;
          return <div key={kind} className="evidence-upload"><span className="eyebrow">{kind === 'ticket' ? 'TICKETS' : 'DOCKETS'}</span><strong>{title}</strong><small>PNG, JPG or WEBP · up to 30 images</small><button className="uploaded-count-button" disabled={!branch} onClick={() => { setManagingKind(kind); setPreviewUpload(null); }}>{count} {kind === 'ticket' ? 'ticket' : 'docket'}{count === 1 ? '' : 's'} uploaded · View / manage</button><label className="file-button secondary">{button}<input type="file" accept="image/*" multiple disabled={!branch || !summary || busy} onChange={(e) => { const files = Array.from(e.target.files || []); if (files.length) uploadImages(kind, files); e.target.value = ''; }} /></label>{uploads[kind] && <small className="upload-result">{uploads[kind]}</small>}{uploadBatches[kind]?.jobs?.map((job) => <div className="file-progress" key={job.job_id || job.filename}><span>{job.filename}</span><span className={`status-pill ${job.status}`}>{job.status}</span><small>{job.message}{job.provider ? ` · ${job.provider}` : ''}{job.error ? ` · ${job.error}` : ''}</small></div>)}</div>;
        })}
       </div></section>
      {tickets.length > 0 && <section className="ticket-data-section"><div className="section-title"><div><span className="eyebrow">SAVED EXTRACTION</span><h2>Ticket data <span className="entry-count">{tickets.length}</span></h2><p>Extracted ticket fields and item rows for {branch} · {date}.</p></div></div>
        <div className="data-table-scroll"><table className="ticket-data-table"><thead><tr>
          <th>Ticket number</th><th>Restaurant</th><th>Date</th><th>Terminal</th><th>Table</th><th>Department</th><th>User</th><th>Payment status</th><th>Credit card amount</th><th>Items</th><th>Ticket total</th><th>Grand total</th><th>Charged</th>
        </tr></thead><tbody>{tickets.map((ticket) => {
          const items = parseJson(ticket.items);
          return <tr key={ticket.ticket_id}><td><strong>{ticket.ticket_id_display || `#${ticket.ticket_id}`}</strong></td><td>{ticket.restaurant || '—'}</td><td>{ticket.ticket_date || '—'}</td><td>{ticket.terminal || '—'}</td><td>{ticket.table_name || '—'}</td><td>{ticket.department || '—'}</td><td>{ticket.user_name || '—'}</td><td>{ticket.payment_status || '—'}</td><td>{ticket.credit_card_amount || '—'}</td><td>{items.length ? <details><summary>{items.length} item{items.length === 1 ? '' : 's'}</summary><div className="data-table-scroll nested-data-scroll"><table className="ticket-items-table"><thead><tr><th>Item</th><th>Modifier</th><th>Category</th><th>Price</th><th>Qty</th><th>Total</th><th>Void</th><th>Signals</th></tr></thead><tbody>{items.map((item, index) => {
            const signals = item.signals || {};
            const fired = [['row_tint', 'Row tint'], ['strikethrough_line', 'Strikethrough'], ['void_label_text', 'Void label']].filter(([key]) => signals[key] || item[key]);
            return <tr key={`${ticket.ticket_id}-${index}`} className={item.is_void ? 'data-void-row' : ''}><td>{item.item || item.name || '—'}</td><td>{item.modifier || '—'}</td><td>{item.category || '—'}</td><td>{item.price || item.unit_price || '—'}</td><td>{item.qty ?? item.quantity ?? '—'}</td><td>{item.total || '—'}</td><td>{item.is_void ? 'Yes' : 'No'}{item.void_confidence === 'low' && <small className="data-review-note">Spot-check</small>}</td><td>{fired.map(([, label]) => label).join(', ') || '—'}</td></tr>;
          })}</tbody></table></div></details> : '—'}</td><td>{ticket.ticket_total || '—'}</td><td>{ticket.grand_total || '—'}</td><td>{ticket.charged || '—'}</td></tr>;
        })}</tbody></table></div>
      </section>}
      {dockets.length > 0 && <section className="ticket-data-section"><div className="section-title"><div><span className="eyebrow">SAVED EXTRACTION</span><h2>Docket data <span className="entry-count">{dockets.length}</span></h2><p>Extracted docket fields, item lines, and void markers for {branch} · {date}.</p></div></div>
        <div className="data-table-scroll"><table className="ticket-data-table docket-data-table"><thead><tr><th>Order number</th><th>Date</th><th>Time</th><th>Department</th><th>Table</th><th>Covers</th><th>Staff</th><th>Extracted item text</th><th>Discrepancy</th><th>Handwritten reason</th><th>Review</th></tr></thead><tbody>{dockets.map((docket) => {
          const lines = parseJson(docket.item_lines);
          const conflicts = parseJson(docket.field_conflicts);
          const partial = parseJson(docket.partial_fields);
          return <tr key={docket.id}><td>{docket.docket_order_no || '—'}</td><td>{docket.docket_date || '—'}</td><td>{docket.docket_time || '—'}</td><td>{docket.department || '—'}</td><td>{docket.table_name || '—'}</td><td>{docket.covers ?? '—'}</td><td>{docket.staff_name || '—'}</td><td><strong>{docket.item || '—'}</strong>{lines.length > 0 && <details><summary>{lines.length} extracted item line{lines.length === 1 ? '' : 's'}</summary><div className="nested-data-scroll"><table className="ticket-items-table"><thead><tr><th>Qty</th><th>Item text</th><th>Modifier</th><th>Marker</th><th>Void</th></tr></thead><tbody>{lines.map((line, index) => <tr key={index} className={line.is_void ? 'data-void-row' : ''}><td>{line.quantity ?? line.qty ?? '—'}</td><td>{line.name || line.item || '—'}</td><td>{line.modifier || '—'}</td><td>{line.marker_type || '—'}</td><td>{line.is_void ? 'Yes' : 'No'}</td></tr>)}</tbody></table></div></details>}</td><td>{docket.discrepancy_type || lines.filter((line) => line.is_void || line.marker_type).map((line) => line.marker_type || 'VOID').join(', ') || '—'}</td><td>{docket.handwritten_reason || <span className="warning-badge">No description</span>}</td><td>{docket.review_required || conflicts.length || partial.length ? <><span className="status-pill needs-review">Needs review</span>{conflicts.map((item, i) => <small className="data-review-note" key={`c${i}`}>{item.field}: {(item.values || []).join(' / ')}</small>)}{partial.map((item) => <small className="data-review-note" key={item}>Partial: {item}</small>)}</> : <span className="status-pill verified">Saved</span>}</td></tr>;
        })}</tbody></table></div>
      </section>}
    </main>
    {detail && <div className="modal-backdrop" onClick={() => setDetail(null)}><section className="detail-modal" onClick={(e) => e.stopPropagation()}><div className="modal-head"><div><span className="eyebrow">{detail.key.toUpperCase()} · {detail.row.row_status.replace('_',' ')}</span><h2>{detail.row.product}</h2></div><div className="modal-actions"><button className="copy-button" onClick={copyDetail}>{copiedKey === 'detail' ? 'Copied' : 'Copy details'}</button><button className="quiet-button" onClick={() => setDetail(null)}>Close</button></div></div>
      <div className="evidence-columns"><article><h3>CSV row</h3><dl><dt>Product</dt><dd>{detail.row.product}</dd><dt>Quantity</dt><dd>{detail.row.quantity}</dd><dt>User</dt><dd>{detail.row.user_name}</dd><dt>Department</dt><dd>{detail.row.department}</dd><dt>Till</dt><dd>{detail.row.till}</dd><dt>Value</dt><dd>£{Number(detail.row.sales_value || 0).toFixed(2)}</dd><dt>Branch · date</dt><dd>{branch} · {detail.row.row_date}</dd></dl></article>
      {(detail.row.candidates || []).length ? detail.row.candidates.map((candidate, i) => {
        const ticket = candidate.ticket;
        const docket = candidate.docket;
        const parse = (value, fallback = []) => { try { return JSON.parse(value || JSON.stringify(fallback)); } catch { return fallback; } };
        const ticketImages = ticket ? parse(ticket.screenshot_filenames) : [];
        const docketImages = docket ? parse(docket.image_filenames, docket.image_filename ? [docket.image_filename] : []) : [];
        const itemLines = docket ? parse(docket.item_lines) : [];
        return <article key={i}>
          {ticket ? <><h3>Ticket · {ticket.ticket_id}{candidate.needs_review ? ' · Needs review' : ''}</h3><dl><dt>Branch</dt><dd>{ticket.restaurant || branch}</dd><dt>ID day / date</dt><dd>{ticket.ticket_id.slice(0, 6)} / {ticket.ticket_date || '—'}</dd><dt>Terminal</dt><dd>{ticket.terminal || '—'}</dd><dt>Table</dt><dd>{ticket.table_name || '—'}</dd><dt>Department</dt><dd>{ticket.department || '—'}</dd><dt>User</dt><dd>{ticket.user_name || '—'}</dd><dt>Payment</dt><dd>{ticket.payment_status || '—'}</dd><dt>Credit card</dt><dd>{ticket.credit_card_amount || '—'}</dd><dt>Matched item</dt><dd>{candidate.ticket_item?.name || '—'} · Qty {candidate.ticket_item?.quantity || '—'} · {candidate.ticket_item?.total || '—'} · Void {candidate.ticket_item?.is_void ? 'Yes' : 'No'}</dd><dt>Totals</dt><dd>Ticket {ticket.ticket_total || '—'} · Grand {ticket.grand_total || '—'} · Charged {ticket.charged || '—'}</dd></dl><h3>Ticket items</h3>{parse(ticket.items).map((item, itemIndex) => {
            const signals = item.signals || {};
            const firedSignals = [['row_tint', 'Row tint'], ['strikethrough_line', 'Strikethrough'], ['void_label_text', 'Void label']].filter(([key]) => signals[key]);
            return <p key={itemIndex} className="matched-item">{item.name} ? {item.category || '?'} ? Qty {item.quantity} ? Unit {item.price || '?'} ? Total {item.total} {item.is_void ? '? VOID' : ''}{item.modifier && <small>Modifier: {item.modifier}</small>}{item.void_confidence === 'low' && <small className="warning-badge">Low-confidence void; spot-check</small>}{firedSignals.map(([, label]) => <small key={label} className="evidence-signal">{label}</small>)}</p>;
          })}{parse(ticket.review_flags).map((flag) => <span className="warning-badge" key={flag}>{flag}</span>)}<div className="thumbnail-row">{ticketImages.map((filename) => <img key={filename} className="evidence-thumb" src={`/api/images/ticket_screenshots/${filename}`} alt={`Ticket screenshot ${filename}`} />)}</div></> : <h3>Ticket · Pending match</h3>}
          {docket ? <><h3>Docket · Order {docket.docket_order_no}</h3><dl><dt>Date / time</dt><dd>{docket.docket_date || '—'} {docket.docket_time || ''}</dd><dt>Department / staff</dt><dd>{docket.department || '—'} · {docket.staff_name || '—'}</dd><dt>Table / covers</dt><dd>{docket.table_name || '—'} · {docket.covers || '—'}</dd><dt>Items</dt><dd>{itemLines.map((line) => `${line.quantity || line.qty || ''} ${line.name || ''}${line.is_void ? ' (VOID)' : ''}`).join('; ') || docket.item || '—'}</dd><dt>Description</dt><dd>{docket.handwritten_reason || <span className="warning-badge">No description</span>} · Confidence {docket.description_confidence ?? '—'}</dd></dl>{parse(docket.field_conflicts).map((conflict, n) => <span className="warning-badge" key={n}>{conflict.field}: {conflict.values.join(' / ')}</span>)}{parse(docket.partial_fields).map((field) => <span className="warning-badge" key={field}>Partial: {field}</span>)}<div className="thumbnail-row">{docketImages.map((filename) => <img key={filename} className="evidence-thumb" src={`/api/images/dockets/${filename}`} alt={`Docket photo ${filename}`} />)}</div></> : <h3>Docket · Pending match</h3>}
        </article>;
      }): <p className="empty-state">No unique matched ticket and docket yet. Current status: {detail.row.row_status.replace('_',' ')}.</p>}</div>
    </section></div>}
    {managingKind && <div className="modal-backdrop" onClick={() => { setManagingKind(''); setPreviewUpload(null); }}><section className="detail-modal upload-manager-modal" onClick={(e) => e.stopPropagation()}><div className="modal-head"><div><span className="eyebrow">SAVED EVIDENCE</span><h2>{managingKind === 'ticket' ? 'Uploaded ticket images' : 'Uploaded docket images'} <span className="entry-count">{managedFiles.length}</span></h2></div><button className="quiet-button" onClick={() => { setManagingKind(''); setPreviewUpload(null); }}>Close</button></div>
      {managedFiles.length ? <div className="uploaded-image-grid">{managedFiles.map((item) => <article className="uploaded-image-card" key={`${item.kind}-${item.stored_filename}`}><button className="upload-preview-button" onClick={() => setPreviewUpload(item)}><img src={item.url} alt={`${item.kind} upload ${item.original_filename}`} /></button><div className="uploaded-image-info"><strong title={item.original_filename}>{item.original_filename}</strong><small>{item.provider || item.status} · {item.message}</small><label className="replace-upload-button">Replace<input type="file" accept="image/*" disabled={busy} onChange={(e) => { const file = e.target.files?.[0]; if (file) replaceUploadedFile(item, file); e.target.value = ''; }} /></label></div><button className="delete-upload-button" disabled={item.status === 'queued' || item.status === 'processing'} onClick={() => deleteUploadedFile(item)}>Delete</button></article>)}</div> : <p className="empty-state">No saved images for this branch and date.</p>}
      {previewUpload && <div className="manager-preview"><strong>{previewUpload.original_filename}</strong><img src={previewUpload.url} alt={`Full preview of ${previewUpload.original_filename}`} /></div>}
    </section></div>}
    <footer>TIL System <span>Restaurant operations workspace</span></footer>
  </div>;
}
