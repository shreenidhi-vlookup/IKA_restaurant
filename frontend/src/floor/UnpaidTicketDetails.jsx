import FloorDialog from './FloorDialog.jsx';
import CopyButton from './CopyButton.jsx';
import { unpaidTicketCopyText } from './copyFormats.js';
import './imports.css';

const money = value => `£${Number(value || 0).toFixed(2)}`;

export default function UnpaidTicketDetails({ ticket, onClose }) {
  return <FloorDialog title={`Unpaid ticket ${ticket.ticket_id}`} onClose={onClose} actions={<CopyButton label="Copy Details" getText={() => unpaidTicketCopyText(ticket)} />}><dl className="hf-unpaid-detail">{[['Ticket ID', ticket.ticket_id], ['Terminal', ticket.terminal], ['Department', ticket.department], ['User', ticket.user], ['Date', ticket.date], ['Time', ticket.time], ['Service', ticket.service], ['Total', money(ticket.total)], ['Method', ticket.method], ['Given', money(ticket.given)], ['Change', money(ticket.change)]].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || '—'}</dd></div>)}</dl></FloorDialog>;
}
