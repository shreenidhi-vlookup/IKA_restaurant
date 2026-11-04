import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { workflowReport } from './workflowReport.js';

test('Reports no-item count stays separate from Overview unpaid API results', () => {
  const paidWithoutItems = { ticket_id: '65', payment_status: 'Paid', items: [] };
  const unpaidWithItems = { ticket_id: '7', payment_status: 'Unpaid', items: [{ name: 'Tea' }] };
  const report = workflowReport({ tickets: [paidWithoutItems, unpaidWithItems], ticketReport: { unpaid_count: 3, unpaid_tickets: [{ ticket_id: '7' }, { ticket_id: '8' }, { ticket_id: '9' }] } });
  assert.deepEqual(report.emptyTickets, [paidWithoutItems]);
  assert.equal(report.unpaidTicketCount, 3);
  const reportsPage = readFileSync(new URL('./ReportsPage.jsx', import.meta.url), 'utf8');
  assert.match(reportsPage, /No items extracted: \{report.emptyTickets.length\}/);
  assert.doesNotMatch(reportsPage, /\{report.emptyTickets.length\} empty/);
  const overviewPage = readFileSync(new URL('./OverviewPage.jsx', import.meta.url), 'utf8');
  assert.match(overviewPage, /Empty tickets: \{report.unpaidTicketCount/);
  assert.doesNotMatch(overviewPage, /report.emptyTickets/);
});

test('Overview Empty tickets uses API unpaid_count regardless of extracted item lines', () => {
  const tickets = [{ items: [] }, { items: [] }];
  assert.equal(workflowReport({ tickets }).unpaidTicketCount, null);
  assert.equal(workflowReport({ tickets, ticketReport: { unpaid_count: 0, unpaid_tickets: [] } }).unpaidTicketCount, 0);
  const unpaid = { ticket_id: '0007', total: 0, method: 'Unpaid' };
  const result = workflowReport({ tickets, ticketReport: { unpaid_count: 1, unpaid_tickets: [unpaid] } });
  assert.equal(result.unpaidTicketCount, 1);
  assert.equal(result.ticketReport.unpaid_tickets[0], unpaid);
});

test('unavailable imports and unpaid reports remain unknown instead of reporting completion', () => {
  const report = workflowReport({});
  assert.equal(report.hasImport, false);
  assert.equal(report.ticketReport, undefined);
  assert.equal(report.checks.find(check => check.label === 'CSV verification').status, 'unknown');
  assert.equal(report.checks.find(check => check.label === 'Ticket report / unpaid').status, 'unknown');
  assert.deepEqual(report.rows, []);
});

test('workflow uses backend statuses and retains confirmed mismatched CSV dates', () => {
  const rows = [
    { id: 1, row_date: '2026-10-01', void_count: 1, cancel_count: 1, row_status: 'partial', candidates: [{ ticket: {}, docket: {} }] },
    { id: 2, promotion_count: 1, row_status: 'pending', candidates: [{ ticket: {} }] },
    { id: 3, void_count: 1, row_status: 'verified' },
    { id: 4, row_status: 'pending' },
  ];
  const report = workflowReport({ verification: { has_import: true, rows } });
  assert.equal(report.rows.length, 4);
  assert.deepEqual(report.outstanding.map(row => row.id), [1, 2]);
  assert.deepEqual(report.incomplete.map(row => row.id), [2]);
  assert.deepEqual(report.discrepancyTypes.map(item => item.count), [2, 1, 1]);
  assert.deepEqual(report.verificationStates.map(item => item.count), [1, 1, 0, 1]);
});

test('saved image counts and session failures remain separate; unpaid zero is a real result', () => {
  const report = workflowReport({ files: [{ status: 'done' }, { status: 'processing' }, { status: 'failed' }], batches: [{ kind: 'ticket', jobs: [{ status: 'failed' }] }], ticketReport: { total_tickets: 4, unpaid_count: 0 }, unassigned: [{ id: 1 }] });
  assert.equal(report.failed.length, 1);
  assert.equal(report.batchFailures.length, 1);
  assert.equal(report.processing.length, 1);
  assert.equal(report.extracted.length, 1);
  assert.equal(report.checks.find(check => check.label === 'Ticket report / unpaid').status, 'complete');
  assert.equal(report.checks.find(check => check.label === 'Screenshot IDs').status, 'attention');
});
