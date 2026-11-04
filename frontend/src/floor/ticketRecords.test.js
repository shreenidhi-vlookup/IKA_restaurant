import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { recordArray, displayValue, ticketItems, ticketFlags, docketNeedsReview, docketConflicts, docketPartialFields, docketDiscrepancy, voidSignals, evidenceFiles, filterTickets, filterDockets } from './ticketRecords.js';

const ticket = { ticket_id: '261103-0012', ticket_id_display: '#261103-0012', restaurant: 'Haweli Restaurant Southall', selected_branch: 'Haweli Restaurant Southall', ticket_date: '2026-11-03', terminal: 'T1', table_name: '4', department: 'Bar', user_name: 'Alice', payment_status: 'Paid', credit_card_amount: '10.00', ticket_total: '10.00', grand_total: '10.00', charged: '10.00', items: JSON.stringify([{ name: 'Burger', modifier: 'No onions', category: 'Food', price: '10.00', qty: '1', total: '10.00', is_void: true, signals: { row_tint: true, strikethrough_line: true }, void_confidence: 'low' }]), review_flags: JSON.stringify(['Low-confidence void']), screenshot_filenames: JSON.stringify(['ticket-a.jpg', 'ticket-b.jpg']) };
const empty = { ...ticket, ticket_id: '261103-0001', user_name: 'Bob', items: '[]', review_flags: '[]', payment_status: 'Unpaid' };
const docket = { id: 1, docket_order_no: '0012', staff_name: 'Alice', table_name: '4', department: 'Bar', item: 'Burger', item_lines: JSON.stringify([{ name: 'Burger', quantity: 1, is_void: true, marker_type: 'void' }]), handwritten_reason: 'Changed order', review_required: 0, field_conflicts: '[]', partial_fields: '[]', image_filename: 'docket-original.jpg', image_filenames: '[]' };

test('Tickets labels the no-item badge, filter and dialog without implying unpaid status', () => {
  const page = readFileSync(new URL('./TicketsPage.jsx', import.meta.url), 'utf8');
  assert.doesNotMatch(page, /['">]Empty tickets?['"<]/);
  assert.match(page, /<Flag>No items extracted<\/Flag>/);
  assert.match(page, /\['empty', 'No items extracted'\]/);
  assert.match(page, /'No items extracted · Ticket'/);
  const paidWithoutItems = { ...empty, payment_status: 'Paid' };
  const unpaidWithItems = { ...ticket, payment_status: 'Unpaid' };
  const records = [paidWithoutItems, unpaidWithItems];
  assert.deepEqual(filterTickets(records, { filter: 'empty' }), [paidWithoutItems]);
  assert.deepEqual(filterTickets(records, { payment: 'Unpaid' }), [unpaidWithItems]);
  assert.deepEqual(filterTickets(records, { filter: 'empty', payment: 'Paid' }), [paidWithoutItems]);
});

test('presentation adapters preserve full original records and leading-zero identifiers', () => {
  const before = JSON.stringify({ ticket, empty, docket });
  assert.equal(ticketItems(ticket)[0].modifier, 'No onions');
  assert.equal(ticketItems(ticket)[0].void_confidence, 'low');
  assert.deepEqual(ticketFlags(ticket), ['Low-confidence void']);
  assert.equal(filterTickets([ticket], { query: '0012' })[0].ticket_id, '261103-0012');
  assert.equal(docket.docket_order_no, '0012');
  evidenceFiles(ticket, 'ticket'); filterDockets([docket]);
  assert.equal(JSON.stringify({ ticket, empty, docket }), before);
});

test('array fields support stored JSON and arrays, with safe malformed-field fallbacks', () => {
  assert.deepEqual(recordArray('invalid'), []);
  assert.deepEqual(recordArray('{"not":"an array"}'), []);
  assert.deepEqual(recordArray(null), []);
  assert.deepEqual(recordArray(['flag']), ['flag']);
  assert.deepEqual(ticketItems(empty), []);
});

test('zero extracted values remain visible rather than becoming missing', () => {
  assert.equal(displayValue(0), '0');
  assert.equal(displayValue('0.00'), '0.00');
  assert.equal(displayValue(null), '—');
  assert.equal(displayValue(''), '—');
});

test('void evidence includes both nested and legacy top-level signals', () => {
  assert.deepEqual(voidSignals(ticketItems(ticket)[0]), ['Row tint', 'Strikethrough']);
  assert.deepEqual(voidSignals({ void_label_text: 1 }), ['Void label']);
});

test('ticket search and filters use extraction and payment fields, not invented verification statuses', () => {
  const rows = [ticket, empty];
  assert.deepEqual(filterTickets(rows, { query: 'no-such-ticket' }), []);
  assert.deepEqual(filterTickets(rows, { query: 'burger', filter: 'void', payment: 'Paid' }), [ticket]);
  assert.deepEqual(filterTickets(rows, { query: 'alice', filter: 'review' }), [ticket]);
  assert.deepEqual(filterTickets(rows, { query: 'Bar' }), rows);
  assert.deepEqual(filterTickets(rows, { filter: 'empty' }), [empty]);
  assert.deepEqual(filterTickets(rows, { payment: 'Unpaid' }), [empty]);
  assert.deepEqual(filterTickets(rows, { filter: 'empty', payment: 'Paid' }), []);
});

test('docket review is derived from all original review/conflict/partial indicators', () => {
  assert.equal(docketNeedsReview(docket), false);
  assert.equal(docketNeedsReview({ ...docket, review_required: 1 }), true);
  const conflict = { ...docket, field_conflicts: JSON.stringify([{ field: 'staff_name', values: ['Alice', 'Bob'] }]) };
  assert.equal(docketNeedsReview(conflict), true);
  assert.deepEqual(docketConflicts(conflict)[0].values, ['Alice', 'Bob']);
  const partial = { ...docket, partial_fields: '["covers"]' };
  assert.equal(docketNeedsReview(partial), true);
  assert.deepEqual(docketPartialFields(partial), ['covers']);
});

test('docket search and filters retain printed data and discrepancy fallbacks', () => {
  const missing = { ...docket, id: 2, handwritten_reason: '', review_required: 1 };
  assert.deepEqual(filterDockets([docket, missing], { query: 'ALICE', filter: 'review' }), [missing]);
  assert.deepEqual(filterDockets([docket, missing], { filter: 'missing-description' }), [missing]);
  assert.deepEqual(filterDockets([docket], { query: 'Burger', filter: 'marked' }), [docket]);
  assert.equal(docketDiscrepancy(docket), 'void');
  assert.equal(docketDiscrepancy({ ...docket, discrepancy_type: 'cancel' }), 'cancel');
  assert.equal(docketDiscrepancy({ item_lines: '[]' }), '—');
});

test('evidence preserves multiple image references and legacy docket filename fallback', () => {
  assert.deepEqual(evidenceFiles(ticket, 'ticket').map(file => file.url), ['/api/images/ticket_screenshots/ticket-a.jpg', '/api/images/ticket_screenshots/ticket-b.jpg']);
  assert.deepEqual(evidenceFiles(docket, 'docket'), [{ name: 'docket-original.jpg', url: '/api/images/dockets/docket-original.jpg' }]);
  assert.deepEqual(evidenceFiles({ ...docket, image_filenames: '["a.jpg","b.jpg","a.jpg"]' }, 'docket').map(file => file.name), ['a.jpg', 'b.jpg']);
  assert.equal(evidenceFiles({ screenshot_filenames: '["image name.jpg"]' }, 'ticket')[0].url, '/api/images/ticket_screenshots/image%20name.jpg');
  assert.deepEqual(evidenceFiles({}, 'ticket'), []);
});
