import { rowsForCategory } from './verificationData.js';
import { recordArray, ticketItems, ticketFlags, docketNeedsReview } from './ticketRecords.js';

// Derived solely from the current API snapshot. CSV row dates are deliberately not
// re-filtered: the original workflow permits confirmed date-mismatch imports.
export function workflowReport(state) {
  const hasImport = Boolean(state.verification?.has_import);
  const rows = hasImport ? state.verification.rows || [] : [];
  const flagged = rows.filter(row => row.void_count > 0 || row.cancel_count > 0 || row.promotion_count > 0);
  const outstanding = rowsForCategory(rows, 'status');
  const incomplete = outstanding.filter(row => !recordArray(row.candidates).some(candidate => candidate.ticket && candidate.docket));
  const files = state.files || [];
  const processing = files.filter(file => ['queued', 'processing'].includes(file.status));
  const failed = files.filter(file => file.status === 'failed');
  const extracted = files.filter(file => file.status === 'done');
  const unassigned = state.unassigned || [];
  const tickets = state.tickets || [], dockets = state.dockets || [];
  const ticketReport = state.ticketReport;
  const checks = [
    { label: 'Till report', status: hasImport ? 'complete' : 'attention', detail: hasImport ? `${rows.length} item rows loaded` : 'Import the till CSV for this business date', href: '#imports' },
    { label: 'Image processing', status: processing.length || failed.length ? 'attention' : files.length ? 'complete' : 'unknown', detail: files.length ? `${extracted.length} extracted · ${processing.length} processing · ${failed.length} failed` : 'No saved images for this upload date', href: '#imports' },
    { label: 'Screenshot IDs', status: unassigned.length ? 'attention' : 'complete', detail: unassigned.length ? `${unassigned.length} screenshots need an ID or confirmation` : 'No unresolved screenshots returned by the backend', href: '#imports' },
    { label: 'CSV verification', status: !hasImport ? 'unknown' : outstanding.length ? 'attention' : 'complete', detail: !hasImport ? 'Waiting for the till import' : flagged.length ? `${flagged.length - outstanding.length} of ${flagged.length} flagged rows verified` : 'No flagged CSV rows', href: '#verification' },
    { label: 'Ticket report / unpaid', status: !ticketReport ? 'unknown' : ticketReport.unpaid_count ? 'attention' : 'complete', detail: ticketReport ? `${ticketReport.total_tickets} tickets processed · ${ticketReport.unpaid_count} unpaid` : 'Not imported in this session; historical unpaid results are not stored', href: '#imports' },
  ];
  const verificationStates = ['pending', 'partial', 'needs_review', 'verified'].map(status => ({ label: status, count: flagged.filter(row => row.row_status === status).length }));
  const imageStates = ['queued', 'processing', 'failed', 'done'].map(status => ({ label: status, count: files.filter(file => file.status === status).length }));
  const discrepancyTypes = [['void', 'Void'], ['cancel', 'Cancel'], ['promotion', 'Promotion']].map(([key, label]) => ({ label, count: rows.filter(row => row[`${key}_count`] > 0).length }));
  return {
    hasImport, rows, flagged, outstanding, incomplete, processing, failed, extracted, unassigned, tickets, dockets, files, ticketReport, checks,
    unpaidTicketCount: ticketReport ? ticketReport.unpaid_count : null,
    emptyTickets: tickets.filter(ticket => !ticketItems(ticket).length),
    reviewTickets: tickets.filter(ticket => ticketFlags(ticket).length),
    reviewDockets: dockets.filter(docketNeedsReview),
    batchFailures: (state.batches || []).flatMap(batch => batch.jobs.filter(job => job.status === 'failed').map(job => ({ ...job, kind: batch.kind }))),
    verificationStates, imageStates, discrepancyTypes,
  };
}
