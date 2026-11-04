import { useContext, useState } from 'react';
import { WorkspaceContext } from './WorkspaceContext.js';
import { useImports } from './ImportsContext.js';
import { formatBusinessDate } from './workspaceState.js';
import { displayValue as value, recordArray, ticketFlags, ticketItems, docketLines } from './ticketRecords.js';
import { verificationBoxes, rowsForCategory, categoryStatus, filterVerificationRows } from './verificationData.js';
import { summaryCopyText, verificationCopyText } from './copyFormats.js';
import CopyButton from './CopyButton.jsx';
import FloorDialog from './FloorDialog.jsx';
import { FieldList, TicketItemTable, DocketItemTable, ReviewNotes, EvidenceGallery } from './TicketsPage.jsx';
import './verification.css';

const money = amount => `£${Number(amount || 0).toFixed(2)}`;
const label = status => (status || 'pending').replaceAll('_', ' ');
function MatchStatus({ status }) { return <span className={`hf-match-status hf-match-status--${status || 'pending'}`}>{label(status)}</span>; }

function CandidateEvidence({ candidate, index, branch }) {
  const { ticket, ticket_item: item, docket, docket_item: docketItem } = candidate;
  return <section className="hf-match-candidate"><header><h3>Evidence pair {index + 1}</h3>{candidate.needs_review && <MatchStatus status="needs_review" />}</header>
    <div className="hf-match-pair"><article><h4>{ticket ? `Ticket · ${ticket.ticket_id}` : 'Ticket · Pending match'}</h4>{ticket ? <>
      <FieldList fields={[
        ['Branch', ticket.restaurant || branch], ['Ticket ID day', ticket.ticket_id?.slice(0, 6)], ['Ticket date', ticket.ticket_date], ['Terminal', ticket.terminal], ['Table', ticket.table_name], ['Department', ticket.department], ['User', ticket.user_name], ['Payment', ticket.payment_status], ['Credit card', ticket.credit_card_amount], ['Ticket total', ticket.ticket_total], ['Grand total', ticket.grand_total], ['Charged', ticket.charged],
      ]} />
      <div className="hf-matched-line"><h4>Matched ticket item</h4>{item ? <p>{value(item.name || item.item)} · Qty {value(item.quantity ?? item.qty)} · Total {value(item.total)} · Void {item.is_void ? 'Yes' : 'No'}</p> : <p>No matched ticket item.</p>}</div>
      {ticketFlags(ticket).length > 0 && <ul className="hf-match-warnings">{ticketFlags(ticket).map((flag, key) => <li key={key}>{String(flag)}</li>)}</ul>}
      <details className="hf-match-items"><summary>All ticket items ({ticketItems(ticket).length})</summary>{ticketItems(ticket).length ? <TicketItemTable ticket={ticket} /> : <p>No items extracted.</p>}</details>
      <EvidenceGallery record={ticket} kind="ticket" />
    </> : <p className="hf-muted">No supporting ticket has been matched by the backend.</p>}</article>
    <article><h4>{docket ? `Docket · Order ${value(docket.docket_order_no)}` : 'Docket · Pending match'}</h4>{docket ? <>
      <FieldList fields={[
        ['Date', docket.docket_date], ['Time', docket.docket_time], ['Department', docket.department], ['Staff', docket.staff_name], ['Table', docket.table_name], ['Covers', docket.covers], ['Extracted items', docketLines(docket).map(line => `${line.quantity ?? line.qty ?? ''} ${line.name || line.item || ''}${line.is_void ? ' (VOID)' : ''}`).join('; ') || docket.item], ['Description', docket.handwritten_reason || 'No description'], ['Description confidence', docket.description_confidence],
      ]} />
      {docketItem && <div className="hf-matched-line"><h4>Matched docket item</h4><p>{value(docketItem.name || docketItem.item)} · Qty {value(docketItem.quantity ?? docketItem.qty)} · Marker {value(docketItem.marker_type)} · Void {docketItem.is_void ? 'Yes' : 'No'}</p></div>}
      <ReviewNotes docket={docket} />
      <details className="hf-match-items"><summary>All docket lines ({docketLines(docket).length})</summary>{docketLines(docket).length ? <DocketItemTable docket={docket} /> : <p>No item lines extracted.</p>}</details>
      <EvidenceGallery record={docket} kind="docket" />
    </> : <p className="hf-muted">No supporting docket has been matched by the backend.</p>}</article></div>
  </section>;
}

function RowEvidence({ row, category, branch, businessDate }) {
  const candidates = recordArray(row.candidates);
  return <div className="hf-match-evidence"><section className="hf-panel"><header><h2>{row.product}</h2><MatchStatus status={row.row_status} /></header><div className="hf-panel-body">
    <FieldList fields={[
      ['CSV product', row.product], ['Quantity', row.quantity], ['User', row.user_name], ['Department', row.department], ['Till', row.till], ['Value', money(row.sales_value)], ['Branch', branch], ['CSV row date', row.row_date || businessDate], ['Selected business date', businessDate],
    ]} />
    <div className="hf-record-scroll" role="region" aria-label="Discrepancy matching results" tabIndex="0"><table><thead><tr><th scope="col">Check</th><th scope="col">CSV count</th><th scope="col">Matched units</th><th scope="col">Required units</th><th scope="col">Result</th></tr></thead><tbody>{[['void', 'Void'], ['cancel', 'Cancel'], ['promotion', 'Promotion']].map(([key, title]) => <tr key={key}><th scope="row">{title}</th><td>{value(row[`${key}_count`])}</td><td>{value(row.matches?.[key]?.verified)}</td><td>{value(row.matches?.[key]?.total)}</td><td><MatchStatus status={row.matches?.[key]?.status} /></td></tr>)}</tbody></table></div>
    <div className="hf-match-detail-actions"><CopyButton getText={() => verificationCopyText(row, category, branch, businessDate)} label="Copy details" /><a className="hf-record-link" href="#imports">Add or manage evidence in Imports →</a></div>
    <p className="hf-muted">Matching is calculated by the backend. No manual approval or resolution is available.</p>
  </div></section>
    {candidates.length ? candidates.map((candidate, index) => <CandidateEvidence key={`${row.id}-${index}`} candidate={candidate} index={index} branch={branch} />) : <section className="hf-panel"><div className="hf-panel-body"><h3>No unique matched ticket and docket yet</h3><p className="hf-muted">Current status: {label(row.row_status)}. Upload or correct the evidence in Imports, then refresh matching.</p></div></section>}
  </div>;
}

function VerificationWorkspace() {
  const { branch, businessDate } = useContext(WorkspaceContext);
  const { state, controller } = useImports();
  const [category, setCategory] = useState('status');
  const [selected, setSelected] = useState(null);
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('all');
  const [dialogOpen, setDialogOpen] = useState(false);
  const current = state.branch === branch && state.businessDate === businessDate;
  const data = current ? state.verification : null;
  const rows = data?.rows || [];
  const boxes = verificationBoxes(data?.has_import ? data.summary : null);
  const categoryRows = category ? rowsForCategory(rows, category) : [];
  const visible = filterVerificationRows(categoryRows, { query, status, category });
  const active = visible.find(row => row.id === selected) || visible[0];
  const title = boxes.find(box => box.key === category)?.title;
  function chooseCategory(key) { setCategory(category === key ? '' : key); setSelected(null); setQuery(''); setStatus('all'); setDialogOpen(false); }

  return <div className="hf-verification">
    <p className="hf-live-note"><strong>Live matching</strong> · {branch || 'Choose a branch'} · {formatBusinessDate(businessDate)}<span>CSV rows, candidate tickets and dockets from the existing verification API. Counts refer to CSV rows, not unique tickets.</span></p>
    <div className="hf-record-toolbar"><p className="hf-muted">Review backend results and compare the original evidence.</p><button type="button" className="hf-secondary" disabled={!branch || !current || state.loading || state.busy} onClick={() => controller.refresh()}>Refresh matching</button></div>
    {!branch ? <section className="hf-panel"><div className="hf-panel-body"><h2>Choose a restaurant branch</h2><p className="hf-muted">Select the branch and business date to load saved verification.</p></div></section> : !current || state.loading ? <p role="status">Loading verification results…</p> : <>
      {state.error && <div className="hf-import-error" role="alert"><p>{state.error}</p><button type="button" className="hf-secondary" disabled={state.busy} onClick={() => controller.refresh()}>Retry loading records</button></div>}
      {!data?.has_import ? <section className="hf-panel"><div className="hf-panel-body"><h2>{state.error ? 'Verification could not be loaded' : 'No till import for this business date'}</h2><p className="hf-muted">{state.error ? 'Retry loading the selected workspace.' : 'Import a till CSV before comparing it with ticket and docket evidence.'}</p><a className="hf-primary" href="#imports">Open Imports</a></div></section> : <>
        <div className="hf-verification-summary" aria-label="Verification summary categories">{boxes.map(box => <section className={`hf-verification-box${category === box.key ? ' is-selected' : ''}`} key={box.key}><button type="button" className="hf-category-button" aria-pressed={category === box.key} aria-label={`Show ${box.title} rows`} onClick={() => chooseCategory(box.key)}><span>{box.title}</span><strong>{box.value}</strong><small>{box.note}</small></button><CopyButton label={`Copy ${box.title}`} getText={() => summaryCopyText(box, rows, branch, businessDate)} /></section>)}</div>
        <p className="hf-match-copy-note">Category copies include all rows in that category, independent of search and status filters. The Status category lists flagged rows still needing attention.</p>
        {!category ? <section className="hf-panel"><div className="hf-panel-body">Choose a summary category to review its CSV rows.</div></section> : <div className="hf-match-layout">
          <section className="hf-panel hf-match-queue"><header><h2>{title} rows</h2><button type="button" className="hf-secondary" onClick={() => { setCategory(''); setDialogOpen(false); }}>Close list</button></header>
            <div className="hf-match-filters"><label>Search CSV rows<input value={query} onChange={event => { setQuery(event.target.value); setSelected(null); }} placeholder="Product, user, department or till" /></label><label>Matching status<select value={status} onChange={event => { setStatus(event.target.value); setSelected(null); }}>{[['all', 'All statuses'], ['pending', 'Pending'], ['partial', 'Partial'], ['needs_review', 'Needs review'], ['verified', 'Verified'], ['not_flagged', 'Not flagged']].map(([id, text]) => <option key={id} value={id}>{text}</option>)}</select></label><button type="button" className="hf-secondary" onClick={() => { setQuery(''); setStatus('all'); }}>Clear filters</button><span>{visible.length} of {categoryRows.length} rows</span></div>
            <ul>{visible.map(row => <li key={row.id}><button type="button" aria-pressed={active?.id === row.id} onClick={() => setSelected(row.id)}><strong>{row.product}</strong><small>Qty {value(row.quantity)} · {value(row.user_name)} · {value(row.department)} · {value(row.till)}</small><span className="hf-match-row-meta"><span>{money(row.sales_value)}</span><MatchStatus status={categoryStatus(row, category)} /></span>{row.matches?.[category === 'promotions' ? 'promotion' : category]?.total > 1 && <small>{row.matches[category === 'promotions' ? 'promotion' : category].verified} of {row.matches[category === 'promotions' ? 'promotion' : category].total} units matched</small>}</button></li>)}{!visible.length && <li className="hf-panel-body">{categoryRows.length ? 'No matching CSV rows. Try clearing the filters.' : 'No matching CSV rows in this category.'}</li>}</ul>
          </section>
          <div className="hf-match-detail">{active ? <><button type="button" className="hf-secondary hf-open-detail" onClick={() => setDialogOpen(true)}>Open evidence detail window</button><RowEvidence key={`${active.id}-${category}`} row={active} category={category} branch={branch} businessDate={businessDate} /></> : <section className="hf-panel"><div className="hf-panel-body">{category === 'status' && !categoryRows.length ? 'No flagged CSV rows need attention. Choose Total to inspect all imported rows.' : 'Select a CSV row to inspect matching and evidence.'}</div></section>}</div>
        </div>}
        {dialogOpen && active && <FloorDialog title={`${title} · ${active.product}`} onClose={() => setDialogOpen(false)} actions={<CopyButton getText={() => verificationCopyText(active, category, branch, businessDate)} label="Copy details" />}><RowEvidence key={`${active.id}-${category}-dialog`} row={active} category={category} branch={branch} businessDate={businessDate} /></FloorDialog>}
      </>}
    </>}
  </div>;
}

export default function VerificationPage() {
  const { branch, businessDate } = useContext(WorkspaceContext);
  return <VerificationWorkspace key={`${branch}\0${businessDate}`} />;
}
