import { test } from 'node:test';
import assert from 'node:assert/strict';
import { verificationBoxes, rowsForCategory, categoryStatus, filterVerificationRows } from './verificationData.js';

const rows = [
  { id: 1, product: 'Burger', user_name: 'Alice', department: 'Bar', till: 'T1', void_count: 1, cancel_count: 0, promotion_count: 1, row_status: 'needs_review', matches: { void: { status: 'verified' }, promotion: { status: 'partial' } } },
  { id: 2, product: 'Chips', user_name: 'Bob', department: 'Kitchen', till: 'T2', void_count: 0, cancel_count: 1, promotion_count: 0, row_status: 'verified' },
  { id: 3, product: 'Tea', user_name: 'Alice', department: 'Bar', till: 'T1', void_count: 0, cancel_count: 0, promotion_count: 0, row_status: 'pending' },
  { id: 4, product: 'Rice', user_name: 'Bob', department: 'Kitchen', till: 'T2', void_count: 1, cancel_count: 0, promotion_count: 0, row_status: 'partial' },
];

test('all five original category filters retain their row-level semantics', () => {
  assert.deepEqual(rowsForCategory(rows, 'total'), rows);
  assert.deepEqual(rowsForCategory(rows, 'void').map(row => row.id), [1, 4]);
  assert.deepEqual(rowsForCategory(rows, 'cancel').map(row => row.id), [2]);
  assert.deepEqual(rowsForCategory(rows, 'promotions').map(row => row.id), [1]);
  assert.deepEqual(rowsForCategory(rows, 'status').map(row => row.id), [1, 4]);
});

test('matching filters distinguish category-level matches from whole-row outcomes', () => {
  assert.equal(categoryStatus(rows[0], 'void'), 'verified');
  assert.equal(categoryStatus(rows[0], 'promotions'), 'partial');
  assert.equal(categoryStatus(rows[0], 'status'), 'needs_review');
  assert.deepEqual(filterVerificationRows(rowsForCategory(rows, 'void'), { category: 'void', status: 'verified', query: 'ALICE' }), [rows[0]]);
  assert.deepEqual(filterVerificationRows(rows, { query: 'T2', status: 'partial', category: 'status' }), [rows[3]]);
  assert.deepEqual(filterVerificationRows(rows, { query: 'does-not-exist' }), []);
});

test('summary uses backend counts and preserves the missing-promotion-column state', () => {
  const summary = { item_rows: 12, quantity: 20, void: { flagged_rows: 3, amount: 45.5, verified: 1, total: 3 }, cancel: { flagged_rows: 0, amount: 0, verified: 0, total: 0 }, promotions: { flagged_rows: 0, amount: 0, verified: 0, total: 0 }, promotions_in_file: false, status: { label: '1 of 3 verified', verified: 1, total: 3 } };
  const snapshot = JSON.stringify(summary);
  const boxes = verificationBoxes(summary);
  assert.deepEqual(boxes.map(box => box.key), ['total', 'void', 'cancel', 'promotions', 'status']);
  assert.equal(boxes[1].note, '£45.50 · 1 of 3 verified');
  assert.equal(boxes[3].value, 'Not in file');
  assert.equal(boxes[3].note, 'Promotion column not present');
  assert.equal(boxes[4].value, '1 of 3 verified');
  assert.equal(JSON.stringify(summary), snapshot);
  assert.deepEqual(verificationBoxes(null), []);
});
