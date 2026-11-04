import { useContext, useState } from 'react';
import { Icon } from '../design/icons.jsx';
import { WorkspaceContext } from './WorkspaceContext.js';
import { useImports } from './ImportsContext.js';
import { formatBusinessDate } from './workspaceState.js';
import FloorDialog from './FloorDialog.jsx';
import './imports.css';
import UnpaidTicketDetails from './UnpaidTicketDetails.jsx';

const money = value => `£${Number(value || 0).toFixed(2)}`;
function Status({ value }) { return <span className={`hf-import-status hf-import-status--${value}`}>{value === 'done' ? 'Extracted' : value}</span>; }
function Panel({ title, action, children }) { return <section className="hf-panel hf-import-panel"><header><h2>{title}</h2>{action}</header>{children}</section>; }

function UnassignedRow({ item, busy, resolve }) {
  const [ticketId, setTicketId] = useState('');
  return <li><div><strong>{item.filename}</strong><p className="hf-muted">{item.issue}</p></div><form onSubmit={event => { event.preventDefault(); resolve(item, ticketId); }}><label>Ticket ID<input value={ticketId} onChange={event => setTicketId(event.target.value)} placeholder="YYMMDD-N" pattern="[0-9]{6}-[0-9]+" required disabled={busy} /></label><button type="submit" className="hf-secondary" disabled={busy}>Assign ticket ID</button></form></li>;
}

function ImageManager({ kind, state, controller, onClose }) {
  const [preview, setPreview] = useState(null);
  const files = state.files.filter(item => item.kind === kind);
  return <FloorDialog title={kind === 'ticket' ? 'Uploaded ticket images' : 'Uploaded docket images'} onClose={onClose}>
    <p className="hf-muted hf-dialog-note">{files.length} saved image(s) · {state.branch} · {formatBusinessDate(state.businessDate)}</p>
    {files.length ? <div className="hf-image-grid">{files.map(item => <article className="hf-image-card" key={item.stored_filename}>
      <button className="hf-image-preview" type="button" aria-label={`Preview ${item.original_filename}`} onClick={() => setPreview(item)}><img src={item.url} alt={item.original_filename} loading="lazy" /></button>
      <strong title={item.original_filename}>{item.original_filename}</strong><Status value={item.status} /><p>{item.provider || 'Awaiting extraction'} · {item.message}{item.error && ` · ${item.error}`}</p>
      <div className="hf-image-actions"><label className="hf-file-button hf-replace">{state.busy ? 'Working…' : 'Replace image'}<input type="file" accept="image/*" disabled={state.busy} onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file && window.confirm(`Replace ${item.original_filename || item.stored_filename} with ${file.name}? The old image is removed only after the new image extracts successfully.`)) { setPreview(null); controller.replaceFile(item, file); } }} /></label>
      <button type="button" className="hf-danger" disabled={state.busy || ['queued', 'processing'].includes(item.status)} onClick={() => { if (window.confirm(`Delete ${item.original_filename || item.stored_filename} and its saved extraction data?`)) { setPreview(null); controller.deleteFile(item); } }}>Delete</button></div>
    </article>)}</div> : <p className="hf-import-empty">No saved images for this branch and date.</p>}
    {preview && <div className="hf-full-image"><strong>{preview.original_filename}</strong><img src={preview.url} alt={`Full preview of ${preview.original_filename}`} /></div>}
    {state.busy && <p className="hf-import-message" role="status">Working… Please keep this tab open. The original image is retained until replacement extraction succeeds.</p>}
    {state.error && <p className="hf-import-error" role="alert">{state.error}</p>}
    {state.notice && <p className="hf-import-message" role="status">{state.notice}</p>}
  </FloorDialog>;
}

function ImportsWorkspace() {
  const { branch, businessDate, dispatch } = useContext(WorkspaceContext);
  const { state, controller } = useImports();
  const [dragging, setDragging] = useState('');
  const [manager, setManager] = useState('');
  const [unpaid, setUnpaid] = useState(null);
  const ready = state.branch === branch && state.businessDate === businessDate;
  const waiting = !ready || state.loading;
  const blocked = !branch || waiting || state.busy;
  const evidenceBlocked = blocked || !state.verification?.has_import;
  const blocker = !branch ? 'Select a restaurant branch first.' : waiting ? 'Loading the selected workspace…' : state.busy ? 'A request is in progress.' : !state.verification?.has_import ? 'Import a till CSV for this business date before adding evidence.' : '';
  const earlier = state.history.filter(item => item.date < businessDate);

  return <div className="hf-imports">
    <p className="hf-live-note"><strong>Live imports</strong> · {branch || 'Choose a branch'} · {formatBusinessDate(businessDate)}<span>These actions save real records in the existing backend. Inspect saved ticket and docket extraction in Tickets.</span></p>
    {!ready ? <p role="status">Loading workspace…</p> : <>
    <div className="hf-import-feedback" aria-live="polite">{state.loading && <p role="status">Loading saved imports and images…</p>}{state.busy && <p role="status">Working…</p>}{state.notice && <p className="hf-import-message" role="status">{state.notice}</p>}</div>
    {state.error && <div className="hf-import-error" role="alert"><p>{state.error}</p><button type="button" className="hf-secondary" disabled={!branch || state.busy || state.loading} onClick={() => controller.refresh()}>Retry loading records</button></div>}
    <div className="hf-import-toolbar"><button type="button" className="hf-secondary" disabled={!branch || state.historyLoading || state.busy} onClick={() => controller.toggleHistory()}>{state.historyLoading ? 'Loading records…' : state.historyOpen ? 'Hide previous records' : 'View previous records'}</button><button type="button" className="hf-secondary" disabled={!branch || state.busy || state.loading} onClick={() => controller.refresh()}>Refresh records</button></div>
    {state.historyError && <div className="hf-import-error" role="alert"><p>Import history could not be loaded: {state.historyError}</p><button type="button" className="hf-secondary" disabled={state.historyLoading || state.busy} onClick={() => controller.loadHistory(true)}>Retry history</button></div>}
    {state.historyOpen && <Panel title="Previous till imports"><p className="hf-import-note">Earlier than the selected business date. Ticket-report results are not saved in this history.</p>{earlier.length ? <ul className="hf-history-list">{earlier.map(item => <li key={item.date}><div><strong>{item.date}</strong><p>{item.filename || 'CSV import'} · {item.item_rows} item rows · {item.flagged_rows} discrepancy rows</p></div><button type="button" className="hf-secondary" disabled={state.busy} onClick={() => dispatch({ type: 'businessDate', value: item.date })}>View records</button></li>)}</ul> : <p className="hf-import-empty">No earlier CSV imports for this branch.</p>}</Panel>}
    <Panel title="1. Import reports"><div className="hf-import-grid">
      <article className="hf-upload-card"><Icon name="upload" size={23} /><h3>Till CSV</h3><p>TIL item report with Product Name, Quantity, Void, Cancel and optional Promotion columns.</p><label className="hf-file-button">{state.busy ? 'Working…' : 'Choose till CSV'}<input type="file" accept=".csv,text/csv" disabled={blocked} onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) controller.uploadCsv(file); }} /></label>{state.csvName && <p className="hf-file-name">{state.csvName}</p>}{state.verification?.has_import && <p className="hf-import-success">Till report saved · {state.verification.summary.item_rows} rows · {state.verification.summary.quantity} items. {state.verification.promotions_in_file ? 'Promotion column included.' : 'Promotion column not present.'}</p>}<p className="hf-import-note">Reimporting replaces till rows for this branch and business date.</p></article>
      <article className="hf-upload-card"><Icon name="ticket" size={23} /><h3>Ticket report CSV</h3><p>Ticket, Terminal, Department, User, Date, Time, Service, Total, Method, Given and Change columns. Used to detect unpaid tickets.</p><label className="hf-file-button">{state.busy ? 'Working…' : 'Choose ticket report'}<input type="file" accept=".csv,text/csv" disabled={blocked} onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) controller.uploadReport(file); }} /></label>{state.ticketReportName && <p className="hf-file-name">{state.ticketReportName}</p>}<p className="hf-import-note">Results stay available while navigating sections, but reset on branch/date change or reload.</p></article>
    </div>{(!branch || waiting || state.busy) && <p className="hf-import-note">{blocker}</p>}</Panel>
    {state.pendingCsv && <section className="hf-import-warning" role="alert" aria-label="CSV date mismatch"><h3>Confirm the CSV business date</h3><p>{state.pendingCsv.result.message}</p><p>Selected: {businessDate} · File dates: {state.pendingCsv.result.csv_dates.join(', ')} · {state.pendingCsv.file.name}</p><div className="hf-import-toolbar"><button type="button" className="hf-primary" disabled={state.busy} onClick={() => controller.uploadCsv(state.pendingCsv.file, true)}>Confirm and import</button><button type="button" className="hf-secondary" disabled={state.busy} onClick={() => controller.cancelCsv()}>Cancel</button></div></section>}
    {state.ticketReport && <Panel title="Ticket report results"><p className="hf-import-note">{state.ticketReport.total_tickets} tickets processed · {state.ticketReport.unpaid_count} unpaid · {branch} · {businessDate}. Session-only results.</p>{state.ticketReport.unpaid_tickets.length ? <div className="hf-import-table-wrap" role="region" aria-label="Unpaid ticket results" tabIndex="0"><table><thead><tr><th scope="col">Ticket ID</th><th scope="col">Total</th><th scope="col">Method</th><th scope="col">Details</th></tr></thead><tbody>{state.ticketReport.unpaid_tickets.map((item, index) => <tr key={`${item.ticket_id}-${index}`}><td>{item.ticket_id}</td><td>{money(item.total)}</td><td>{item.method}</td><td><button type="button" className="hf-secondary" onClick={() => setUnpaid(item)}>View details</button></td></tr>)}</tbody></table></div> : <p className="hf-import-empty">No unpaid tickets in this report.</p>}</Panel>}
    <Panel title="2. Upload tickets & dockets"><div className="hf-import-grid">{[['ticket', 'Ticket screenshots', 'Upload screenshots'], ['docket', 'Docket photos', 'Upload dockets']].map(([kind, title, label]) => <article key={kind} className={`hf-upload-card hf-image-drop${dragging === kind && !evidenceBlocked ? ' is-dragover' : ''}`} onDragOver={event => { event.preventDefault(); if (!evidenceBlocked && event.dataTransfer.types.includes('Files')) setDragging(kind); }} onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget)) setDragging(''); }} onDrop={event => { event.preventDefault(); setDragging(''); if (!evidenceBlocked) controller.uploadImages(kind, Array.from(event.dataTransfer.files)); }}>
      <Icon name="upload" size={23} /><h3>{title}</h3><p>PNG, JPG or WebP · Up to 30 images per batch · Select files or drag and drop here.</p><label className="hf-file-button">{state.busy ? 'Working…' : label}<input type="file" accept="image/png,image/jpeg,image/webp" multiple disabled={evidenceBlocked} onChange={event => { const files = Array.from(event.target.files || []); event.target.value = ''; controller.uploadImages(kind, files); }} /></label><button type="button" className="hf-secondary" disabled={!branch || waiting} onClick={() => setManager(kind)}>{state.files.filter(item => item.kind === kind).length} {kind} image(s) · View / manage</button>{evidenceBlocked && <p className="hf-import-note">{blocker}</p>}{dragging === kind && !evidenceBlocked && <p>Drop images to upload</p>}{state.warnings[kind] && <p className="hf-import-warning">{state.warnings[kind]}</p>}
    </article>)}</div></Panel>
    {state.batches.length > 0 && <Panel title="Submitted batches"><p className="hf-import-note">Extraction status is separate from ticket verification. Held, rejected and failed files show their server messages here.</p>{state.batches.map(batch => <div className="hf-batch" key={batch.batch_id}><h3>{batch.kind === 'ticket' ? 'Ticket screenshots' : 'Docket photos'}</h3><ul>{batch.jobs.map((job, index) => <li key={job.job_id || `${job.filename}-${index}`}><strong>{job.filename}</strong><Status value={job.status} /><p>{job.message}{job.provider && ` · ${job.provider}`}{job.error && ` · ${job.error}`}</p></li>)}</ul></div>)}</Panel>}
    <Panel title="Saved image activity"><div className="hf-import-table-wrap" role="region" aria-label="Saved evidence activity" tabIndex="0"><table><thead><tr><th scope="col">Image / type</th><th scope="col">Status</th><th scope="col">Processing detail</th><th scope="col">Manage</th></tr></thead><tbody>{state.files.map(item => <tr key={`${item.kind}-${item.stored_filename}`}><td><strong>{item.original_filename}</strong><small>{item.kind === 'ticket' ? 'Ticket screenshot' : 'Docket photo'}</small></td><td><Status value={item.status} /></td><td>{item.message}{item.provider && <small>{item.provider}</small>}{item.error && <small>{item.error}</small>}</td><td><button type="button" className="hf-secondary" onClick={() => setManager(item.kind)}>View / manage</button></td></tr>)}{!state.files.length && <tr><td colSpan="4">{branch ? 'No saved images for this branch and date.' : 'Select a branch to load saved images.'}</td></tr>}</tbody></table></div></Panel>
    {state.unassigned.length > 0 && <Panel title="Ticket screenshots needing an ID"><ul className="hf-unassigned-list">{state.unassigned.map(item => <UnassignedRow key={item.filename} item={item} busy={state.busy} resolve={controller.resolveScreenshot} />)}</ul></Panel>}
    {state.pendingResolution && <section className="hf-import-warning" role="alert"><h3>Confirm ticket branch or day mismatch</h3><p>{state.pendingResolution.warnings.join(' · ')}</p><p>Assign {state.pendingResolution.item.filename} to {state.pendingResolution.ticketId} anyway?</p><div className="hf-import-toolbar"><button type="button" className="hf-primary" disabled={state.busy} onClick={() => controller.resolveScreenshot(state.pendingResolution.item, state.pendingResolution.ticketId, true)}>Confirm assignment</button><button type="button" className="hf-secondary" disabled={state.busy} onClick={() => controller.cancelResolution()}>Cancel</button></div></section>}
    {manager && <ImageManager kind={manager} state={state} controller={controller} onClose={() => setManager('')} />}
    {unpaid && <UnpaidTicketDetails ticket={unpaid} onClose={() => setUnpaid(null)} />}
    </>}
  </div>;
}

export default function ImportsPage() {
  const { branch, businessDate } = useContext(WorkspaceContext);
  return <ImportsWorkspace key={`${branch}\0${businessDate}`} />;
}
