import { recordArray } from './ticketRecords.js';
import { rowsForCategory, originalStatusLabel } from './verificationData.js';

export function summaryCopyText(box, rows, branch, date) {
  return [
    `Haveli Ticket Management — ${box.title} details`,
    `Branch: ${branch || '—'}`, `Date: ${date}`, box.value, box.note, '',
    ...rowsForCategory(rows, box.key).map(row => `${row.product} | Qty ${row.quantity} | ${row.user_name} | ${row.department} | ${row.till} | £${Number(row.sales_value || 0).toFixed(2)} | ${originalStatusLabel(row, box.key)}`),
  ].join('\n');
}

export function verificationCopyText(row, category, branch, date) {
  const key = category === 'promotions' ? 'promotion' : category;
  const lines = [
    `Haveli Ticket Management — ${key.toUpperCase()} detail`,
    `Branch: ${branch}`, `Date: ${row.row_date || date}`, `Item: ${row.product}`,
    `Quantity: ${row.quantity}`, `User: ${row.user_name}`, `Department: ${row.department}`,
    `Till: ${row.till}`, `Value: £${Number(row.sales_value || 0).toFixed(2)}`,
    `Status: ${row.row_status?.replace('_', ' ') || 'pending'}`,
  ];
  for (const candidate of row.candidates || []) {
    const ticket = candidate.ticket, item = candidate.ticket_item, docket = candidate.docket;
    if (ticket) lines.push('', `Ticket ${ticket.ticket_id}`, `Terminal: ${ticket.terminal || '—'}`, `Table: ${ticket.table_name || '—'}`, `Ticket item: ${item?.name || '—'} | Qty ${item?.quantity || item?.qty || '—'} | Total ${item?.total || '—'} | Void ${item?.is_void ? 'Yes' : 'No'}`);
    if (docket) lines.push('', `Docket order ${docket.docket_order_no || '—'}`, `Date/time: ${docket.docket_date || '—'} ${docket.docket_time || ''}`, `Department/staff: ${docket.department || '—'} / ${docket.staff_name || '—'}`, `Description: ${docket.handwritten_reason || 'No description'}`);
  }
  return lines.join('\n');
}

export function emptyTicketCopyText(ticket) {
  const items = recordArray(ticket.items), flags = recordArray(ticket.review_flags), screenshots = recordArray(ticket.screenshot_filenames);
  return [
    'Empty Ticket Details', '--------------------',
    `Ticket ID: ${ticket.ticket_id_display || `#${ticket.ticket_id}`}`,
    `Restaurant: ${ticket.restaurant || '—'}`, `Branch: ${ticket.selected_branch || '—'}`,
    `Date: ${ticket.ticket_date || '—'}`, `Terminal: ${ticket.terminal || '—'}`, `Table: ${ticket.table_name || '—'}`,
    `Department: ${ticket.department || '—'}`, `User: ${ticket.user_name || '—'}`,
    `Payment Status: ${ticket.payment_status || '—'}`, `Credit Card Amount: ${ticket.credit_card_amount || '—'}`,
    `Ticket Total: ${ticket.ticket_total || '—'}`, `Grand Total: ${ticket.grand_total || '—'}`, `Charged: ${ticket.charged || '—'}`,
    `Items Count: ${items.length}`, `Review Flags: ${flags.length > 0 ? flags.join(', ') : 'None'}`,
    `Screenshots: ${screenshots.length > 0 ? screenshots.join(', ') : 'None'}`,
  ].join('\n');
}

export function unpaidTicketCopyText(ticket) {
  return [
    'Unpaid Ticket Details', '---------------------', `Ticket ID: ${ticket.ticket_id}`,
    `Terminal: ${ticket.terminal || '—'}`, `Department: ${ticket.department || '—'}`, `User: ${ticket.user || '—'}`,
    `Date: ${ticket.date || '—'}`, `Time: ${ticket.time || '—'}`, `Service: ${ticket.service || '—'}`,
    `Total: £${Number(ticket.total || 0).toFixed(2)}`, `Method: ${ticket.method || '—'}`,
    `Given: £${Number(ticket.given || 0).toFixed(2)}`, `Change: £${Number(ticket.change || 0).toFixed(2)}`,
  ].join('\n');
}
