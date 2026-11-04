import { useContext, useState } from 'react';
import { WorkspaceContext } from './WorkspaceContext.js';
import { useImports } from './ImportsContext.js';
import { workflowReport } from './workflowReport.js';
import LiveWorkspace from './LiveWorkspace.jsx';
import UnpaidTicketDetails from './UnpaidTicketDetails.jsx';
import './workflow.css';

function Panel({ title, href, action, children }) { return <section className="hf-panel hf-workflow-panel"><header><h2>{title}</h2>{href && <a className="hf-workflow-link" href={href}>{action || 'Open →'}</a>}</header>{children}</section>; }

function OverviewWorkspace() {
  const { state } = useImports();
  const [unpaid, setUnpaid] = useState(null);
  const report = workflowReport(state);
  return <LiveWorkspace><div className="hf-workload-cards">{[
    ['#imports', report.processing.length, 'Images processing'], ['#verification', report.outstanding.length, 'CSV rows to verify'], ['#imports', report.unassigned.length, 'Unassigned screenshots'], ['#verification', report.incomplete.length, 'Rows without an evidence pair'],
  ].map(([href, count, label]) => <a key={label} href={href}><strong>{count}</strong><span>{label}</span><span aria-hidden="true">↗</span></a>)}</div>
    <div className="hf-overview-grid"><Panel title="Daily workflow checks"><p className="hf-workflow-note">Read-only checks derived from loaded records. These are not a saved close-of-day sign-off.</p><ul className="hf-workflow-checks">{report.checks.map(check => <li key={check.label}><div><strong>{check.label}</strong><p>{check.detail}</p></div><a href={check.href} className={`hf-workflow-state is-${check.status}`}>{check.status === 'complete' ? 'Satisfied' : check.status === 'unknown' ? 'Not available' : 'Needs attention'} →</a></li>)}</ul></Panel>
      <Panel title="Outstanding CSV work" href="#verification" action="Open Verification →"><p className="hf-workflow-note">{report.hasImport ? `${report.outstanding.length} flagged rows still need attention.` : 'Import a till report to see outstanding verification.'}</p><ul className="hf-workflow-list">{report.outstanding.slice(0, 6).map(row => <li key={row.id}><a href="#verification"><strong>{row.product}</strong><span>Qty {row.quantity} · {row.user_name || 'User not extracted'} · {(row.row_status || 'pending').replaceAll('_', ' ')}</span></a></li>)}{report.hasImport && !report.outstanding.length && <li>No outstanding flagged CSV rows.</li>}</ul></Panel>
    </div>
    <Panel title="Saved image activity" href="#imports" action="Open Imports →"><div className="hf-workflow-table" role="region" aria-label="Recent image activity" tabIndex="0"><table><thead><tr><th scope="col">Image</th><th scope="col">Type</th><th scope="col">Processing state</th><th scope="col">Detail</th></tr></thead><tbody>{report.files.slice(0, 8).map(file => <tr key={`${file.kind}-${file.stored_filename}`}><td>{file.original_filename}</td><td>{file.kind === 'ticket' ? 'Ticket screenshot' : 'Docket photo'}</td><td>{file.status === 'done' ? 'Extracted' : file.status}</td><td>{file.message}{file.error && <small>{file.error}</small>}</td></tr>)}{!report.files.length && <tr><td colSpan="4">No saved images for this upload business date.</td></tr>}</tbody></table></div></Panel>
    <div className="hf-overview-grid"><Panel title="Evidence needing attention" href="#imports" action="Manage evidence →"><ul className="hf-workflow-list">{report.unassigned.map(item => <li key={item.filename}><strong>{item.filename}</strong><p>{item.issue}</p></li>)}{report.failed.map(file => <li key={file.stored_filename}><strong>{file.original_filename}</strong><p>{file.error || file.message}</p></li>)}{!report.unassigned.length && !report.failed.length && <li>No unresolved screenshot IDs or failed saved-image jobs.</li>}</ul>{report.incomplete.length > 0 && <p className="hf-workflow-note">{report.incomplete.length} outstanding CSV rows have no candidate containing both a ticket and docket. Inspect them in Verification.</p>}</Panel>
      <Panel title="Extraction review" href="#tickets" action="Open Tickets →"><ul className="hf-workflow-list"><li><strong>Empty tickets: {report.unpaidTicketCount ?? 'Not available'}</strong><p>Unpaid tickets identified by the Ticket Report import.</p>{report.ticketReport ? <>{report.ticketReport.unpaid_tickets.length ? <details><summary>Review unpaid tickets ({report.unpaidTicketCount})</summary><ul className="hf-workflow-list">{report.ticketReport.unpaid_tickets.map((item, index) => <li key={`${item.ticket_id}-${index}`}><button type="button" className="hf-secondary" onClick={() => setUnpaid(item)}>View unpaid ticket {item.ticket_id}</button></li>)}</ul></details> : <p>No unpaid tickets in this report.</p>}<p>Results apply to this branch and business date for the current session.</p></> : <p><a href="#imports">Import a Ticket Report to see unpaid tickets.</a></p>}</li><li><strong>{report.reviewTickets.length} tickets with review flags</strong><p>OCR/extraction flags; separate from CSV matching.</p></li><li><strong>{report.reviewDockets.length} dockets needing review</strong><p>Partial fields, conflicts or extraction review indicators.</p></li></ul></Panel></div>
    {unpaid && <UnpaidTicketDetails ticket={unpaid} onClose={() => setUnpaid(null)} />}
    {report.batchFailures.length > 0 && <Panel title="Failed submissions in this session" href="#imports" action="Review batches →"><p className="hf-workflow-note">Includes files rejected before a saved image was created. These are not added to the saved-image counts.</p><ul className="hf-workflow-list">{report.batchFailures.map((job, index) => <li key={job.job_id || index}><strong>{job.filename}</strong><p>{job.message} · {job.error}</p></li>)}</ul></Panel>}
  </LiveWorkspace>;
}

export default function OverviewPage() {
  const { branch, businessDate } = useContext(WorkspaceContext);
  return <OverviewWorkspace key={`${branch}\0${businessDate}`} />;
}
