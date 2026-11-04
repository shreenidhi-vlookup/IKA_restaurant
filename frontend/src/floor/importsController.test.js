import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createImportsController, imageSelection } from './importsController.js';
import { workflowReport } from './workflowReport.js';

const branch = 'Haweli Restaurant Southall', date = '2026-11-03';
const file = (name, type = 'image/jpeg') => new File(['test bytes'], name, { type });
const image = { kind: 'ticket', stored_filename: 'ticket-old.jpg', original_filename: 'old.jpg', status: 'done' };
const active = { batch_id: 'batch-1', total: 1, jobs: [{ job_id: 'job-1', filename: 'new.jpg', status: 'queued' }] };

test('Overview unpaid count and details reset on branch and business-date changes', async t => {
  const result = { total_tickets: 3, unpaid_count: 1, unpaid_tickets: [{ ticket_id: '0007', method: 'Unpaid', total: 0 }] };
  const { controller } = fixture(t, url => url === '/ticket-report' ? result : undefined);
  await controller.setContext(branch, date);
  await controller.uploadReport(file('report.csv', 'text/csv'));
  assert.equal(workflowReport(controller.getSnapshot()).unpaidTicketCount, 1);
  await controller.setContext('Haweli Restaurant Norbury', date);
  assert.equal(workflowReport(controller.getSnapshot()).unpaidTicketCount, null);
  assert.equal(controller.getSnapshot().ticketReport, null);
  await controller.uploadReport(file('report.csv', 'text/csv'));
  assert.equal(workflowReport(controller.getSnapshot()).unpaidTicketCount, 1);
  await controller.setContext('Haweli Restaurant Norbury', '2026-11-04');
  assert.equal(workflowReport(controller.getSnapshot()).unpaidTicketCount, null);
  assert.equal(controller.getSnapshot().ticketReport, null);
});

test('Reports history loads without opening Imports history and errors allow retry', async t => {
  let fail = true;
  const { controller } = fixture(t, url => {
    if (!url.startsWith('/verification/dates?')) return;
    if (fail) throw new Error('History unavailable');
    return { dates: [{ date, item_rows: 2 }] };
  });
  await controller.setContext(branch, date);
  await controller.loadHistory();
  assert.equal(controller.getSnapshot().historyError, 'History unavailable');
  assert.equal(controller.getSnapshot().error, '');
  assert.equal(controller.getSnapshot().historyLoading, false);
  fail = false;
  await controller.loadHistory();
  assert.equal(controller.getSnapshot().historyLoaded, true);
  assert.equal(controller.getSnapshot().historyOpen, false);
  assert.equal(controller.getSnapshot().historyError, '');
  assert.equal(controller.getSnapshot().history[0].date, date);
});

test('successful CSV reimport invalidates cached history counts', async t => {
  const { controller } = fixture(t, url => url.startsWith('/verification/dates?') ? { dates: [{ date, item_rows: 1 }] } : url === '/csv' ? { saved_rows: 3 } : undefined);
  await controller.setContext(branch, date);
  await controller.loadHistory();
  assert.equal(controller.getSnapshot().historyLoaded, true);
  await controller.uploadCsv(file('till.csv', 'text/csv'));
  assert.equal(controller.getSnapshot().historyLoaded, false);
});
function fixture(t, handler = () => undefined, hasImport = true, settings = {}) {
  const calls = [], scheduled = new Map(); let timerId = 0;
  const request = async (url, options = {}) => {
    calls.push({ url, options });
    const result = await handler(url, options);
    if (result !== undefined) return result;
    if (url.startsWith('/verification?')) return { has_import: hasImport, rows: [], summary: { item_rows: 12 } };
    if (url.startsWith('/uploads?') || url.startsWith('/tickets/unassigned?') || url.startsWith('/tickets?') || url.startsWith('/dockets?')) return [];
    throw new Error(`Unexpected request: ${url}`);
  };
  const controller = createImportsController({ request, schedule: callback => { scheduled.set(++timerId, callback); return timerId; }, cancel: id => scheduled.delete(id), wait: async () => {}, ...settings });
  t.after(() => controller.stop());
  return { controller, calls, scheduled };
}

test('loads only selected branch/date records and sends API-compatible values', async t => {
  const { controller, calls } = fixture(t);
  await controller.setContext(branch, date);
  assert.equal(calls.length, 5);
  for (const { url, options } of calls) {
    assert.equal(new URL(url, 'http://test').searchParams.get('branch'), branch);
    assert.equal(new URL(url, 'http://test').searchParams.get('selected_date'), date);
    assert.ok(options.signal instanceof AbortSignal);
  }
  assert.equal(controller.getSnapshot().verification.has_import, true);
});

test('no branch sends no requests; evidence cannot bypass the till-import prerequisite', async t => {
  const { controller, calls } = fixture(t, undefined, false);
  await controller.setContext('', date);
  await controller.uploadReport(file('report.csv', 'text/csv'));
  assert.equal(calls.length, 0);
  assert.match(controller.getSnapshot().error, /Select a restaurant/);
  await controller.setContext(branch, date);
  await controller.uploadImages('ticket', [file('photo.jpg')]);
  assert.equal(calls.filter(call => call.options.method === 'POST').length, 0);
  assert.match(controller.getSnapshot().error, /Import a till CSV/);
});

test('CSV date mismatch retains the file, waits for confirmation and then refreshes', async t => {
  const submitted = [];
  const { controller } = fixture(t, (url, options) => {
    if (url !== '/csv') return;
    submitted.push(options.body);
    return options.body.get('confirm_date_mismatch') === 'true' ? { saved_rows: 24 } : { confirmation_required: true, csv_dates: ['2026-11-02'], message: 'Different date' };
  });
  await controller.setContext(branch, date);
  const csv = file('till.csv', 'text/csv');
  await controller.uploadCsv(csv);
  assert.equal(controller.getSnapshot().pendingCsv.file, csv);
  assert.equal(submitted.length, 1);
  assert.equal(controller.getSnapshot().csvName, '');
  await controller.uploadCsv(controller.getSnapshot().pendingCsv.file, true);
  assert.equal(submitted[1].get('confirm_date_mismatch'), 'true');
  assert.equal(submitted[1].get('branch'), branch);
  assert.equal(submitted[1].get('selected_date'), date);
  assert.equal(submitted[1].get('file').name, 'till.csv');
  assert.equal(controller.getSnapshot().pendingCsv, null);
  assert.match(controller.getSnapshot().notice, /24 till rows imported/);
});

test('cancelling a pending CSV performs no additional request', async t => {
  const { controller, calls } = fixture(t, url => url === '/csv' ? { confirmation_required: true } : undefined);
  await controller.setContext(branch, date);
  await controller.uploadCsv(file('till.csv', 'text/csv'));
  const count = calls.length;
  controller.cancelCsv();
  assert.equal(controller.getSnapshot().pendingCsv, null);
  assert.equal(calls.length, count);
});

test('ticket-report results retain all unpaid fields and reset on context changes', async t => {
  const result = { total_tickets: 5, unpaid_count: 1, unpaid_tickets: [{ ticket_id: '0012', terminal: 'T1', department: 'Bar', user: 'Alice', date, time: '12:00', service: 'Lunch', total: 0, method: 'Unpaid', given: 0, change: 0 }] };
  const { controller, calls } = fixture(t, url => url === '/ticket-report' ? result : undefined);
  await controller.setContext(branch, date);
  await controller.uploadReport(file('ticket-report.csv', 'text/csv'));
  assert.equal(controller.getSnapshot().ticketReport, result);
  assert.equal(calls.find(call => call.url === '/ticket-report').options.body.get('branch'), branch);
  await controller.setContext(branch, '2026-11-04');
  assert.equal(controller.getSnapshot().ticketReport, null);
  assert.equal(controller.getSnapshot().ticketReportName, '');
});

test('mixed image selection preserves valid files and explains wrong-section names', async t => {
  const selection = imageSelection('ticket', [file('ticket.jpg'), file('docket.jpg')]);
  assert.equal(selection.accepted.length, 1);
  assert.match(selection.warning, /Docket photos/);
  const { controller, calls } = fixture(t, url => url === '/upload/tickets' ? active : undefined);
  await controller.setContext(branch, date);
  await controller.uploadImages('ticket', [file('a.jpg'), file('b.jpg'), file('docket.jpg')]);
  const body = calls.find(call => call.url === '/upload/tickets').options.body;
  assert.deepEqual(body.getAll('files').map(item => item.name), ['a.jpg', 'b.jpg']);
  assert.equal(body.get('selected_date'), date);
  assert.equal(controller.getSnapshot().batches[0].jobs[0].status, 'queued');
  assert.match(controller.getSnapshot().warnings.ticket, /docket.jpg/);
});

test('more than 30 images is rejected before submission', async t => {
  const { controller, calls } = fixture(t);
  await controller.setContext(branch, date);
  await controller.uploadImages('docket', Array.from({ length: 31 }, (_, index) => file(`${index}.jpg`)));
  assert.match(controller.getSnapshot().error, /at most 30/);
  assert.equal(calls.some(call => call.options.method === 'POST'), false);
});

test('polls jobs to completion and retains per-file failure/provider messages', async t => {
  const completed = { ...active, jobs: [{ ...active.jobs[0], status: 'failed', provider: 'tesseract_ocr', message: 'Held for review', error: 'Document type uncertain' }] };
  const { controller, scheduled } = fixture(t, url => url === '/upload/tickets' ? active : url === '/upload/jobs/batch-1' ? completed : undefined);
  await controller.setContext(branch, date);
  await controller.uploadImages('ticket', [file('new.jpg')]);
  assert.equal(scheduled.size, 1);
  await [...scheduled.values()][0]();
  assert.equal(controller.getSnapshot().batches[0].jobs[0].error, 'Document type uncertain');
  assert.equal(controller.getSnapshot().batches[0].jobs[0].provider, 'tesseract_ocr');
  assert.equal(scheduled.size, 0);
});

test('replacement deletes the original only after confirmed extraction success', async t => {
  let polls = 0;
  const { controller, calls } = fixture(t, (url, options) => {
    if (url === '/upload/tickets') return active;
    if (url === '/upload/jobs/batch-1') return { ...active, jobs: [{ ...active.jobs[0], status: ++polls > 1 ? 'done' : 'processing', provider: polls > 1 ? 'tesseract_ocr' : null }] };
    if (options.method === 'DELETE') { assert.equal(polls, 2); return { deleted: true }; }
  });
  await controller.setContext(branch, date);
  await controller.replaceFile(image, file('new.jpg'));
  assert.equal(calls.filter(call => call.options.method === 'DELETE').length, 1);
  assert.equal(calls.find(call => call.options.method === 'DELETE').url, '/uploads/ticket/ticket-old.jpg');
  assert.match(controller.getSnapshot().notice, /replaced old.jpg/);
  assert.equal(controller.getSnapshot().busy, false);
});

test('failed, duplicate or provider-less replacements retain the original', async t => {
  for (const job of [
    { status: 'failed', error: 'OCR failed' },
    { status: 'done', message: 'Duplicate, skipped' },
    { status: 'done', provider: null },
  ]) {
    const { controller, calls } = fixture(t, url => url === '/upload/tickets' ? { ...active, jobs: [job] } : undefined);
    await controller.setContext(branch, date);
    await controller.replaceFile(image, file('new.jpg'));
    assert.equal(calls.some(call => call.options.method === 'DELETE'), false);
    assert.equal(controller.getSnapshot().busy, false);
    assert.match(controller.getSnapshot().error || controller.getSnapshot().notice, /original|Original/);
  }
});

test('context changes ignore late data and invalidate pending confirmations', async t => {
  let release;
  const pending = new Promise(resolve => { release = resolve; });
  const { controller } = fixture(t, url => url.startsWith('/verification?') && url.includes('2026-11-03') ? pending : undefined);
  const oldLoad = controller.setContext(branch, date);
  await controller.setContext('Haweli Ilford Ltd', '2026-11-04');
  release({ has_import: true, summary: { item_rows: 999 } });
  await oldLoad;
  assert.equal(controller.getSnapshot().branch, 'Haweli Ilford Ltd');
  assert.equal(controller.getSnapshot().businessDate, '2026-11-04');
  assert.equal(controller.getSnapshot().verification.summary.item_rows, 12);
  assert.equal(controller.getSnapshot().pendingCsv, null);
});

test('context changes during replacement do not delete the original', async t => {
  let release;
  const requestFinished = new Promise(resolve => { release = resolve; });
  const { controller, calls } = fixture(t, url => url === '/upload/tickets' ? requestFinished : undefined);
  await controller.setContext(branch, date);
  const replacement = controller.replaceFile(image, file('new.jpg'));
  await controller.setContext(branch, '2026-11-04');
  release({ ...active, jobs: [{ status: 'done', provider: 'tesseract_ocr' }] });
  await replacement;
  assert.equal(calls.some(call => call.options.method === 'DELETE'), false);
  assert.equal(controller.getSnapshot().notice, '');
});

test('deletion blocks active jobs and refreshes after terminal-image deletion', async t => {
  const { controller, calls } = fixture(t, (_, options) => options.method === 'DELETE' ? { deleted: true } : undefined);
  await controller.setContext(branch, date);
  await controller.deleteFile({ ...image, status: 'processing' });
  assert.equal(calls.some(call => call.options.method === 'DELETE'), false);
  await controller.deleteFile(image);
  assert.equal(calls.filter(call => call.options.method === 'DELETE').length, 1);
  assert.match(controller.getSnapshot().notice, /deleted/);
});

test('screenshot assignment preserves mismatch confirmation before saving', async t => {
  const { controller, calls } = fixture(t, (url, options) => {
    if (url !== '/tickets/resolve') return;
    if (options.body.get('confirm_mismatch') === 'false') throw new Error(JSON.stringify({ confirmation_required: true, warnings: ['Ticket ID day differs'] }));
    return { ticket_id: '261102-12' };
  });
  await controller.setContext(branch, date);
  const item = { filename: 'unassigned.jpg' };
  await controller.resolveScreenshot(item, '261102-12');
  assert.equal(controller.getSnapshot().pendingResolution.ticketId, '261102-12');
  await controller.resolveScreenshot(item, '261102-12', true);
  const sent = calls.filter(call => call.url === '/tickets/resolve').at(-1).options.body;
  assert.equal(sent.get('confirm_mismatch'), 'true');
  assert.equal(sent.get('filename'), 'unassigned.jpg');
  assert.equal(controller.getSnapshot().pendingResolution, null);
});

test('history is read-only, branch-scoped and can be hidden without another request', async t => {
  const dates = [{ date: '2026-11-02', filename: 'saved.csv', item_rows: 10, flagged_rows: 2 }];
  const { controller, calls } = fixture(t, url => url.startsWith('/verification/dates?') ? { dates } : undefined);
  await controller.setContext(branch, date);
  await controller.toggleHistory();
  assert.deepEqual(controller.getSnapshot().history, dates);
  assert.equal(controller.getSnapshot().historyOpen, true);
  const count = calls.length;
  await controller.toggleHistory();
  assert.equal(controller.getSnapshot().historyOpen, false);
  assert.equal(calls.length, count);
});

test('request errors clear busy state and permit retry without inventing success', async t => {
  const { controller } = fixture(t, url => { if (url === '/ticket-report') throw new Error('CSV must be UTF-8 encoded'); });
  await controller.setContext(branch, date);
  await controller.uploadReport(file('report.csv', 'text/csv'));
  assert.equal(controller.getSnapshot().busy, false);
  assert.equal(controller.getSnapshot().ticketReport, null);
  assert.equal(controller.getSnapshot().notice, '');
  assert.match(controller.getSnapshot().error, /UTF-8/);
});

test('replacement wait limit retains the original while leaving the server job visible', async t => {
  const { controller, calls } = fixture(t, url => url === '/upload/tickets' ? active : undefined, true, { replacementTimeout: 0 });
  await controller.setContext(branch, date);
  await controller.replaceFile(image, file('new.jpg'));
  assert.equal(calls.some(call => call.options.method === 'DELETE'), false);
  assert.equal(controller.getSnapshot().busy, false);
  assert.equal(controller.getSnapshot().batches[0].jobs[0].status, 'queued');
  assert.match(controller.getSnapshot().error, /original is retained/);
});

test('a polling network error does not silently stop checking active extraction', async t => {
  const { controller, scheduled } = fixture(t, url => {
    if (url === '/upload/tickets') return active;
    if (url === '/upload/jobs/batch-1') throw new Error('Network unavailable');
  });
  await controller.setContext(branch, date);
  await controller.uploadImages('ticket', [file('new.jpg')]);
  await [...scheduled.values()][0]();
  assert.match(controller.getSnapshot().error, /checked again/);
  assert.equal(scheduled.size, 1);
  controller.stop();
  assert.equal(scheduled.size, 0);
});

test('real ticket and docket payloads are shared and refresh after import completion', async t => {
  let extracted = false;
  const ticketRows = [{ ticket_id: '261103-0012', items: '[]', screenshot_filenames: '["photo.jpg"]' }];
  const docketRows = [{ id: 12, docket_order_no: '0012', item_lines: '[]', partial_fields: '["table"]' }];
  const { controller } = fixture(t, url => {
    if (url.startsWith('/tickets?')) return extracted ? ticketRows : [];
    if (url.startsWith('/dockets?')) return extracted ? docketRows : [];
    if (url === '/upload/tickets') { extracted = true; return { ...active, jobs: [{ status: 'done', provider: 'tesseract_ocr' }] }; }
  });
  await controller.setContext(branch, date);
  assert.deepEqual(controller.getSnapshot().tickets, []);
  await controller.uploadImages('ticket', [file('photo.jpg')]);
  assert.equal(controller.getSnapshot().tickets, ticketRows);
  assert.equal(controller.getSnapshot().dockets, docketRows);
  assert.equal(controller.getSnapshot().tickets[0].ticket_id, '261103-0012');
});

test('late ticket/docket responses cannot populate a newly selected business date', async t => {
  let releaseTicket, releaseDocket;
  const oldTickets = new Promise(resolve => { releaseTicket = resolve; });
  const oldDockets = new Promise(resolve => { releaseDocket = resolve; });
  const { controller } = fixture(t, url => {
    if (url.startsWith('/tickets?')) return url.includes(date) ? oldTickets : [{ ticket_id: '261104-0001' }];
    if (url.startsWith('/dockets?')) return url.includes(date) ? oldDockets : [{ id: 2 }];
  });
  const oldLoad = controller.setContext(branch, date);
  await controller.setContext(branch, '2026-11-04');
  releaseTicket([{ ticket_id: '261103-9999' }]); releaseDocket([{ id: 9999 }]);
  await oldLoad;
  assert.deepEqual(controller.getSnapshot().tickets, [{ ticket_id: '261104-0001' }]);
  assert.deepEqual(controller.getSnapshot().dockets, [{ id: 2 }]);
});
