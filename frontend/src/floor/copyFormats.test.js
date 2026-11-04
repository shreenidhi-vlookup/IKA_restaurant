import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { summaryCopyText, verificationCopyText, emptyTicketCopyText, unpaidTicketCopyText } from './copyFormats.js';
import { verificationBoxes } from './verificationData.js';

// Execute only the original formatting functions, with a mocked clipboard. No App mounting or requests.
const source = readFileSync(new URL('../App.jsx', import.meta.url), 'utf8');
function block(start, end = '\n  };') {
  const index = source.indexOf(start);
  assert.ok(index >= 0, `Original function exists: ${start}`);
  const finish = source.indexOf(end, index);
  assert.ok(finish >= 0);
  return source.slice(index, finish + end.length);
}
const originalFormatters = [
  block('function parseJson(', '\n}'),
  block('const boxes = summary ?', '] : [];'),
  source.match(/const statusLabel = \(row, key\) => [^\n]+/)[0],
  source.match(/const rowsFor = \(key\) => [^\n]+/)[0],
  block('const copySummary = async'), block('const copyDetail = async'), block('const copyEmptyTicketDetail = async'), block('const copyUnpaidTicketDetail = async'),
].join('\n');
const branch = 'Haweli Restaurant Southall', date = '2026-11-03';
const ticket = { ticket_id: '261103-0012', ticket_id_display: '#261103-0012', restaurant: branch, selected_branch: branch, ticket_date: date, terminal: 'T1', table_name: '4', department: 'Bar', user_name: 'Alice', payment_status: 'Paid', credit_card_amount: '0.00', ticket_total: '0.00', grand_total: '0.00', charged: '0.00', items: '[]', review_flags: '["Check screenshot"]', screenshot_filenames: '["a.jpg","b.jpg"]' };
const docket = { docket_order_no: '0012', docket_date: date, docket_time: '19:05', department: 'Bar', staff_name: 'Alice', handwritten_reason: 'Customer changed order' };
const row = { id: 1, row_date: date, product: 'Burger', quantity: 2, user_name: 'Alice', department: 'Bar', till: 'T1', sales_value: 20, void_count: 1, cancel_count: 0, promotion_count: 1, row_status: 'needs_review', matches: { void: { status: 'verified' }, promotion: { status: 'partial' } }, candidates: [{ ticket, ticket_item: { name: 'Burger', qty: 2, total: '20.00', is_void: true }, docket }, { ticket: null, docket: { docket_order_no: '0022' } }, { ticket, ticket_item: null, docket: null }] };
const rows = [row, { ...row, id: 2, product: 'Tea', void_count: 0, promotion_count: 0, cancel_count: 1, row_status: 'verified', candidates: [] }, { ...row, id: 3, product: 'Water', void_count: 0, promotion_count: 0, cancel_count: 0, row_status: 'pending', sales_value: 0, candidates: [] }];
const summary = { item_rows: 3, quantity: 6, void: { flagged_rows: 1, amount: 20, verified: 1, total: 1 }, cancel: { flagged_rows: 1, amount: 20, verified: 1, total: 1 }, promotions: { flagged_rows: 1, amount: 20, verified: 0, total: 1 }, promotions_in_file: true, status: { label: '1 of 2 verified', verified: 1, total: 2 } };
const unpaid = { ticket_id: '000012', terminal: 'T1', department: 'Bar', user: 'Alice', date, time: '19:00', service: 'Dinner', total: 0, method: 'Unpaid', given: 0, change: 0 };

async function original(expression, overrides = {}) {
  const context = vm.createContext({ branch, date, rows, summary, detail: { row, key: 'void' }, emptyTicketDetail: ticket, unpaidTicketDetail: unpaid, ...overrides });
  vm.runInContext(`let captured; const window = { setTimeout() {} }; const setCopiedKey = () => {}; const setError = message => { throw new Error(message); }; const copyText = async text => { captured = text; }; ${originalFormatters}`, context);
  await vm.runInContext(expression, context);
  return vm.runInContext('captured', context);
}

for (const [index, key] of ['total', 'void', 'cancel', 'promotions', 'status'].entries()) {
  test(`original ${key} summary copy is preserved byte-for-byte`, async () => {
    assert.equal(summaryCopyText(verificationBoxes(summary)[index], rows, branch, date), await original(`copySummary(boxes[${index}])`));
  });
}
test('original CSV evidence-detail copy preserves every candidate, fallback and heading', async () => {
  assert.equal(verificationCopyText(row, 'void', branch, date), await original('copyDetail()'));
  assert.equal(verificationCopyText(row, 'promotions', branch, date), await original('copyDetail()', { detail: { row, key: 'promotion' } }));
  const missing = { ...row, row_date: '', candidates: [] };
  assert.equal(verificationCopyText(missing, 'total', branch, date), await original('copyDetail()', { detail: { row: missing, key: 'total' } }));
});
test('original empty-ticket copy preserves all fields, flags and filenames', async () => {
  assert.equal(emptyTicketCopyText(ticket), await original('copyEmptyTicketDetail()'));
  const blank = { ticket_id: '000012', items: 'invalid', review_flags: '[]', screenshot_filenames: '[]' };
  assert.equal(emptyTicketCopyText(blank), await original('copyEmptyTicketDetail()', { emptyTicketDetail: blank }));
});
test('original unpaid-ticket copy preserves IDs, zero totals and monetary formatting', async () => {
  assert.equal(unpaidTicketCopyText(unpaid), await original('copyUnpaidTicketDetail()'));
});
test('summary formatting retains the original absent-promotion-column output', async () => {
  const missing = { ...summary, promotions_in_file: false };
  assert.equal(summaryCopyText(verificationBoxes(missing)[3], rows, branch, date), await original('copySummary(boxes[3])', { summary: missing }));
});
