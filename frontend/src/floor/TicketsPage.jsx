import { useContext, useState } from 'react';
import { WorkspaceContext } from './WorkspaceContext.js';
import { useImports } from './ImportsContext.js';
import FloorDialog from './FloorDialog.jsx';
import { formatBusinessDate } from './workspaceState.js';
import { displayValue as value, ticketItems, ticketFlags, docketLines, docketConflicts, docketPartialFields, docketNeedsReview, docketDiscrepancy, voidSignals, evidenceFiles, filterTickets, filterDockets } from './ticketRecords.js';
import './tickets.css';
import CopyButton from './CopyButton.jsx';
import { emptyTicketCopyText } from './copyFormats.js';

function Flag({ children, positive = false }) { return <span className={`hf-record-flag${positive ? ' is-saved' : ''}`}>{children}</span>; }
function RecordTable({ label, children }) { return <div className="hf-record-scroll" role="region" aria-label={label} tabIndex="0"><table>{children}</table></div>; }
export function TicketItemTable({ ticket }) {
  return <RecordTable label={`Items for ticket ${ticket.ticket_id}`}><thead><tr>{['Item', 'Modifier', 'Category', 'Price', 'Qty', 'Total', 'Void', 'Signals'].map(label => <th scope="col" key={label}>{label}</th>)}</tr></thead><tbody>{ticketItems(ticket).map((item, index) => <tr key={index} className={item.is_void ? 'hf-void-item' : ''}><td>{value(item.item || item.name)}</td><td>{value(item.modifier)}</td><td>{value(item.category)}</td><td>{value(item.price ?? item.unit_price)}</td><td>{value(item.qty ?? item.quantity)}</td><td>{value(item.total)}</td><td>{item.is_void ? 'Yes' : 'No'}{item.void_confidence === 'low' && <small><Flag>Low confidence · Spot-check</Flag></small>}</td><td>{voidSignals(item).join(', ') || '—'}</td></tr>)}</tbody></RecordTable>;
}
export function DocketItemTable({ docket }) {
  return <RecordTable label={`Items for docket ${docket.docket_order_no || docket.id}`}><thead><tr>{['Qty', 'Item text', 'Modifier', 'Marker', 'Void'].map(label => <th scope="col" key={label}>{label}</th>)}</tr></thead><tbody>{docketLines(docket).map((line, index) => <tr key={index} className={line.is_void ? 'hf-void-item' : ''}><td>{value(line.quantity ?? line.qty)}</td><td>{value(line.name || line.item)}</td><td>{value(line.modifier)}</td><td>{value(line.marker_type)}</td><td>{line.is_void ? 'Yes' : 'No'}</td></tr>)}</tbody></RecordTable>;
}
export function FieldList({ fields }) { return <dl className="hf-record-fields">{fields.map(([label, field]) => <div key={label}><dt>{label}</dt><dd>{value(field)}</dd></div>)}</dl>; }
export function ReviewNotes({ docket }) {
  return <div className="hf-record-notes">{docket.review_reason && <p>{docket.review_reason}</p>}{docketConflicts(docket).map((conflict, index) => <p key={index}><strong>{value(conflict.field)}:</strong> {(Array.isArray(conflict.values) ? conflict.values : []).map(value).join(' / ')}</p>)}{docketPartialFields(docket).map(field => <p key={String(field)}>Partial: {value(field)}</p>)}</div>;
}
function EvidenceImage({ file, large = false }) {
  const [failed, setFailed] = useState(false);
  return failed ? <span className="hf-image-unavailable">Image unavailable. It may have expired or been removed; the extracted record is still shown.</span> : <img className={large ? 'hf-record-image-large' : 'hf-record-image'} src={file.url} alt={file.name} loading="lazy" onError={() => setFailed(true)} />;
}
export function EvidenceGallery({ record, kind }) {
  const [selected, setSelected] = useState(null);
  const files = evidenceFiles(record, kind);
  return <section className="hf-record-evidence"><h3>{kind === 'ticket' ? 'Ticket screenshots' : 'Docket images'} <span>{files.length}</span></h3>{files.length ? <><div className="hf-record-gallery">{files.map(file => <div key={file.name}><button type="button" className="hf-record-thumbnail" onClick={() => setSelected(file)} aria-label={`Enlarge ${file.name}`}><EvidenceImage file={file} /></button><small>{file.name}</small></div>)}</div>{selected && <figure className="hf-record-large-preview"><figcaption><strong>{selected.name}</strong><button type="button" className="hf-secondary" onClick={() => setSelected(null)}>Close image preview</button></figcaption><EvidenceImage key={selected.name} file={selected} large /></figure>}</> : <p className="hf-muted">No image filenames are linked to this record.</p>}<a className="hf-record-link" href="#imports">Manage uploaded evidence in Imports →</a></section>;
}

function TicketDetails({ ticket, onClose }) {
  const items = ticketItems(ticket), flags = ticketFlags(ticket);
  return <FloorDialog title={`${items.length ? 'Ticket' : 'No items extracted · Ticket'} ${ticket.ticket_id_display || `#${ticket.ticket_id}`}`} onClose={onClose} actions={!items.length && <CopyButton label="Copy Details" getText={() => emptyTicketCopyText(ticket)} />}>
    <FieldList fields={[
      ['Ticket ID', ticket.ticket_id_display || `#${ticket.ticket_id}`], ['Restaurant', ticket.restaurant], ['Branch', ticket.selected_branch], ['Date', ticket.ticket_date], ['Terminal', ticket.terminal], ['Table', ticket.table_name], ['Department', ticket.department], ['User', ticket.user_name], ['Payment status', ticket.payment_status], ['Credit card amount', ticket.credit_card_amount], ['Ticket total', ticket.ticket_total], ['Grand total', ticket.grand_total], ['Charged', ticket.charged], ['Items count', items.length], ['Review flags', flags.length ? flags.join(', ') : 'None'], ['Screenshot filenames', evidenceFiles(ticket, 'ticket').map(file => file.name).join(', ') || 'None'],
    ]} />
    <section className="hf-record-detail-section"><h3>Ticket items</h3>{items.length ? <TicketItemTable ticket={ticket} /> : <p className="hf-record-warning">No items extracted. Check the original screenshots before treating this as a complete ticket.</p>}</section>
    <EvidenceGallery record={ticket} kind="ticket" />
  </FloorDialog>;
}
function DocketDetails({ docket, onClose }) {
  return <FloorDialog title={`Docket · Order ${value(docket.docket_order_no)}`} onClose={onClose}>
    <FieldList fields={[
      ['Order number', docket.docket_order_no], ['Branch', docket.selected_branch], ['Date', docket.docket_date], ['Time', docket.docket_time], ['Department', docket.department], ['Table', docket.table_name], ['Covers', docket.covers], ['Staff', docket.staff_name], ['Extracted item text', docket.item], ['Discrepancy', docketDiscrepancy(docket)], ['Handwritten reason', docket.handwritten_reason || 'No description'], ['Description confidence', docket.description_confidence], ['Review', docketNeedsReview(docket) ? 'Needs review' : 'Saved'], ['Multiple docket views', docket.multiple_dockets ? 'Yes' : 'No'],
    ]} />
    <ReviewNotes docket={docket} />
    <section className="hf-record-detail-section"><h3>Extracted item lines</h3>{docketLines(docket).length ? <DocketItemTable docket={docket} /> : <p className="hf-muted">No item lines extracted.</p>}</section>
    <EvidenceGallery record={docket} kind="docket" />
  </FloorDialog>;
}

function TicketsWorkspace() {
  const { branch, businessDate } = useContext(WorkspaceContext);
  const { state, controller } = useImports();
  const [view, setView] = useState('tickets');
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [payment, setPayment] = useState('all');
  const [selected, setSelected] = useState(null);
  const current = state.branch === branch && state.businessDate === businessDate;
  const tickets = current ? state.tickets : [], dockets = current ? state.dockets : [];
  const filteredTickets = filterTickets(tickets, { query, filter, payment });
  const filteredDockets = filterDockets(dockets, { query, filter });
  const payments = [...new Set(tickets.map(ticket => ticket.payment_status).filter(Boolean))].sort();
  const activeTicket = selected?.kind === 'ticket' && tickets.find(ticket => ticket.ticket_id === selected.id);
  const activeDocket = selected?.kind === 'docket' && dockets.find(docket => docket.id === selected.id);
  const resetFilters = () => { setQuery(''); setFilter('all'); setPayment('all'); };
  const options = view === 'tickets' ? [['all', 'All records'], ['review', 'With review flags'], ['empty', 'No items extracted'], ['void', 'With void items']] : [['all', 'All records'], ['review', 'Needs review'], ['missing-description', 'Missing description'], ['marked', 'With discrepancy markers']];

  return <div className="hf-tickets">
    <p className="hf-live-note"><strong>Live records</strong> · {branch || 'Choose a branch'} · {formatBusinessDate(businessDate)}<span>Saved extraction from the existing backend. Payment and extraction flags are not manual verification decisions.</span></p>
    <div className="hf-record-toolbar"><div className="hf-record-switch" role="group" aria-label="Record type"><button type="button" className="hf-secondary" aria-pressed={view === 'tickets'} onClick={() => { setView('tickets'); resetFilters(); }}>Tickets ({tickets.length})</button><button type="button" className="hf-secondary" aria-pressed={view === 'dockets'} onClick={() => { setView('dockets'); resetFilters(); }}>Dockets ({dockets.length})</button></div><button type="button" className="hf-secondary" disabled={!branch || !current || state.loading || state.busy} onClick={() => controller.refresh()}>Refresh records</button></div>
    {!branch ? <section className="hf-panel"><div className="hf-panel-body"><h2>Choose a restaurant branch</h2><p className="hf-muted">Use the shared branch and business-date selectors to load real ticket and docket records.</p></div></section> : !current || state.loading ? <p role="status">Loading ticket and docket records…</p> : <>
      {state.error && <div className="hf-import-error" role="alert"><p>{state.error}</p><button type="button" className="hf-secondary" disabled={state.busy} onClick={() => controller.refresh()}>Retry loading records</button></div>}
      <section className="hf-panel"><header><h2>{view === 'tickets' ? 'Ticket register' : 'Docket register'}</h2><span className="hf-record-count">{view === 'tickets' ? `${filteredTickets.length} of ${tickets.length} tickets` : `${filteredDockets.length} of ${dockets.length} dockets`}</span></header>
        <div className="hf-record-filters"><label className="hf-record-search">Search {view}<input value={query} onChange={event => setQuery(event.target.value)} placeholder={view === 'tickets' ? 'Ticket ID, table, user, department or item' : 'Order, table, staff, department or item'} /></label><label>Show<select value={filter} onChange={event => setFilter(event.target.value)}>{options.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>{view === 'tickets' && <label>Payment status<select value={payment} onChange={event => setPayment(event.target.value)}><option value="all">All payment statuses</option>{payments.map(status => <option key={status} value={status}>{status}</option>)}</select></label>}<button type="button" className="hf-secondary" onClick={resetFilters}>Clear filters</button></div>
        <p className="hf-record-scope-note">{view === 'tickets' ? 'Tickets are selected by branch and the day encoded in their ticket ID.' : 'Dockets are selected by branch and upload business date. Their printed date can differ.'} All original extracted fields are available below and in the detail view.</p>
        {view === 'tickets' ? <RecordTable label="Saved ticket records"><caption className="hf-record-sr-only">{branch} · {businessDate} · Ticket extraction</caption><thead><tr>{['Ticket number', 'Restaurant', 'Date', 'Terminal', 'Table', 'Department', 'User', 'Payment status', 'Credit card amount', 'Items', 'Ticket total', 'Grand total', 'Charged', 'Details'].map(label => <th scope="col" key={label}>{label}</th>)}</tr></thead><tbody>{filteredTickets.map(ticket => <tr key={ticket.ticket_id}><th scope="row">{ticket.ticket_id_display || `#${ticket.ticket_id}`}{!ticketItems(ticket).length && <small><Flag>No items extracted</Flag></small>}{ticketFlags(ticket).length > 0 && <small><Flag>Review flags</Flag></small>}</th><td>{value(ticket.restaurant)}</td><td>{value(ticket.ticket_date)}</td><td>{value(ticket.terminal)}</td><td>{value(ticket.table_name)}</td><td>{value(ticket.department)}</td><td>{value(ticket.user_name)}</td><td>{value(ticket.payment_status)}</td><td>{value(ticket.credit_card_amount)}</td><td>{ticketItems(ticket).length ? <details><summary>{ticketItems(ticket).length} item(s)</summary><TicketItemTable ticket={ticket} /></details> : 'No items extracted'}</td><td>{value(ticket.ticket_total)}</td><td>{value(ticket.grand_total)}</td><td>{value(ticket.charged)}</td><td><button type="button" className="hf-secondary" onClick={() => setSelected({ kind: 'ticket', id: ticket.ticket_id })} aria-label={`View details for ticket ${ticket.ticket_id}`}>View details</button></td></tr>)}{!filteredTickets.length && <tr><td colSpan="14" className="hf-record-empty">{tickets.length ? 'No matching tickets. Try clearing the filters.' : state.error ? 'Ticket records could not be confirmed. Retry loading records.' : 'No saved tickets for this branch and ticket day. Add ticket screenshots in Imports.'}</td></tr>}</tbody></RecordTable> : <RecordTable label="Saved docket records"><caption className="hf-record-sr-only">{branch} · {businessDate} · Docket extraction</caption><thead><tr>{['Order number', 'Date', 'Time', 'Department', 'Table', 'Covers', 'Staff', 'Extracted item text', 'Discrepancy', 'Handwritten reason', 'Review', 'Details'].map(label => <th scope="col" key={label}>{label}</th>)}</tr></thead><tbody>{filteredDockets.map(docket => <tr key={docket.id}><th scope="row">{value(docket.docket_order_no)}</th><td>{value(docket.docket_date)}</td><td>{value(docket.docket_time)}</td><td>{value(docket.department)}</td><td>{value(docket.table_name)}</td><td>{value(docket.covers)}</td><td>{value(docket.staff_name)}</td><td><strong>{value(docket.item)}</strong>{docketLines(docket).length > 0 && <details><summary>{docketLines(docket).length} extracted item line(s)</summary><DocketItemTable docket={docket} /></details>}</td><td>{docketDiscrepancy(docket)}</td><td>{docket.handwritten_reason || <Flag>No description</Flag>}</td><td><Flag positive={!docketNeedsReview(docket)}>{docketNeedsReview(docket) ? 'Needs review' : 'Saved'}</Flag><ReviewNotes docket={docket} /></td><td><button type="button" className="hf-secondary" aria-label={`View details for docket ${value(docket.docket_order_no)}`} onClick={() => setSelected({ kind: 'docket', id: docket.id })}>View details</button></td></tr>)}{!filteredDockets.length && <tr><td colSpan="12" className="hf-record-empty">{dockets.length ? 'No matching dockets. Try clearing the filters.' : state.error ? 'Docket records could not be confirmed. Retry loading records.' : 'No saved dockets for this branch and upload date. Add docket photos in Imports.'}</td></tr>}</tbody></RecordTable>}
      </section>
    </>}
    {activeTicket && <TicketDetails ticket={activeTicket} onClose={() => setSelected(null)} />}
    {activeDocket && <DocketDetails docket={activeDocket} onClose={() => setSelected(null)} />}
  </div>;
}

export default function TicketsPage() {
  const { branch, businessDate } = useContext(WorkspaceContext);
  return <TicketsWorkspace key={`${branch}\0${businessDate}`} />;
}
