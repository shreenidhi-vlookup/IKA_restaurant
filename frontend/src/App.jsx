import { useState, useEffect } from 'react';
import './App.css';
import { uploadTicketScreenshotBatch, uploadDocketImageBatch, uploadSalesReport } from './api/upload';
import { exportDockets, exportTickets, getDockets, getRestaurants, getTickets, processSalesReport } from './api/records';
import { getEntries, updateEntry } from './api/entries';

const today = () => new Date().toISOString().slice(0, 10);
const money = (value) => (value === null || value === undefined ? '—' : Number(value).toFixed(2));
const count = (value) => (value === null || value === undefined ? '—' : value);

// Fallback options shown only while the table is empty; real options are
// derived from the restaurant values the backend actually returns.
function App() {
  const [ticketUploadLoading, setTicketUploadLoading] = useState(false);
  const [ticketUploadError, setTicketUploadError] = useState(null);
  const [ticketUploadItems, setTicketUploadItems] = useState([]);
  const [showTicketData, setShowTicketData] = useState(false);
  const [ticketUploadData, setTicketUploadData] = useState([]);
  const [docketUploadLoading, setDocketUploadLoading] = useState(false);
  const [docketUploadError, setDocketUploadError] = useState(null);
  const [docketUploadItems, setDocketUploadItems] = useState([]);
  const [showDocketData, setShowDocketData] = useState(false);
  const [docketUploadData, setDocketUploadData] = useState([]);
  const [comparisonExcelFile, setComparisonExcelFile] = useState(null);
  const [comparisonLongSlipFile, setComparisonLongSlipFile] = useState(null);
  const activeView = 'tickets';
  const [tickets, setTickets] = useState([]);
  const [dockets, setDockets] = useState([]);
  const [restaurants, setRestaurants] = useState([]);
  const [selectedRestaurant, setSelectedRestaurant] = useState('');
  const [selectedDate, setSelectedDate] = useState(today());
  const [selectedTicket, setSelectedTicket] = useState(null);
  const [comparisonCopyStatus, setComparisonCopyStatus] = useState('');
  const [recordsLoading, setRecordsLoading] = useState(false);
  const [recordsError, setRecordsError] = useState(null);
  // Sales report (long slip + Excel) upload state
  const [salesReportLoading, setSalesReportLoading] = useState(false);
  const [salesReportError, setSalesReportError] = useState(null);
  const [salesReportSaved, setSalesReportSaved] = useState(null);
  const [salesReportConflict, setSalesReportConflict] = useState(null);
  // Process dashboard state
  const [processLoading, setProcessLoading] = useState(false);
  const [processError, setProcessError] = useState(null);
  const [dashboard, setDashboard] = useState(null);
  // Description prompt state
  const [descriptionPromptOpen, setDescriptionPromptOpen] = useState(false);
  const [editingEntryId, setEditingEntryId] = useState(null);
  const [descriptionValue, setDescriptionValue] = useState('');
  const [descriptionSaving, setDescriptionSaving] = useState(false);
  const [descriptionError, setDescriptionError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([getTickets(), getDockets(), getRestaurants()])
      .then(([ticketData, docketData, branchData]) => {
        if (cancelled) return;
        setTickets(ticketData);
        setDockets(docketData);
        setRestaurants(branchData);
      })
      .catch((err) => {
        if (!cancelled) setRecordsError(err.message);
      })
      .finally(() => {
        if (!cancelled) setRecordsLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  // Changing the branch or day invalidates the last saved report and the last
  // Process result, so a stale dashboard is never shown against a new scope.
  const handleScopeChange = (setter) => (value) => {
    setter(value);
    setSalesReportSaved(null);
    setSalesReportConflict(null);
    setSalesReportError(null);
    setDashboard(null);
    setProcessError(null);
  };

  const handleSalesReportUpload = async (confirm) => {
    if (!selectedRestaurant) {
      setSalesReportError('Select a branch before uploading the sales report.');
      return;
    }
    if (!comparisonLongSlipFile && !comparisonExcelFile) {
      setSalesReportError('Select a long slip bill image, an Excel report, or both.');
      return;
    }
    setSalesReportLoading(true);
    setSalesReportError(null);
    if (!confirm) setSalesReportConflict(null);

    try {
      const result = await uploadSalesReport(
        comparisonLongSlipFile,
        comparisonExcelFile,
        selectedRestaurant,
        selectedDate,
        confirm || '',
      );
      if (result.conflict) {
        setSalesReportConflict(result.conflict);
        setSalesReportSaved(null);
        return;
      }
      setSalesReportSaved(result);
      setSalesReportConflict(null);
      setDashboard(null);
    } catch (err) {
      setSalesReportError(err.message);
    } finally {
      setSalesReportLoading(false);
    }
  };

  const handleProcess = async () => {
    if (!selectedRestaurant) {
      setProcessError('Select a branch before running Process.');
      return;
    }
    setProcessLoading(true);
    setProcessError(null);
    try {
      const payload = await processSalesReport(selectedRestaurant, selectedDate);
      setDashboard(payload);
    } catch (err) {
      setProcessError(err.message);
      setDashboard(null);
    } finally {
      setProcessLoading(false);
    }
  };

  // Helper function to get entry ID for a record (ticket or docket)
  const getEntryIdForRecord = async (record) => {
    if (activeView === 'dockets') {
      // For dockets, the API response includes the id field
      return record.id;
    } else {
      // For tickets, we need to find the associated entry by ticket_number
      try {
        const entries = await getEntries({ ticketNumber: record.ticket_id });
        if (entries.length > 0) {
          // Return the first entry's ID (ordered by created_at descending per getEntries)
          return entries[0].id;
        } else {
          // No entries found for this ticket
          throw new Error(`No entries found for ticket ${record.ticket_id}`);
        }
      } catch (err) {
        console.error(`Failed to get entry ID for ticket ${record.ticket_id}:`, err);
        throw err;
      }
    }
  };

  const handleTicketScreenshotUpload = async (files) => {
    setTicketUploadLoading(true);
    setTicketUploadError(null);
    const items = files.map((file, index) => ({
      id: `${file.name}-${file.lastModified}-${index}`,
      name: file.name,
      status: 'uploading',
      message: 'Parsing ticket screenshots...'
    }));
    setTicketUploadItems(items);

    try {
      const result = await uploadTicketScreenshotBatch(files);
      const failed = result.failed || [];
      const succeeded = result.succeeded || [];

      setTicketUploadItems(
        files.map((file, index) => {
          const failedItem = failed.find((item) => item.filename === file.name || item.original_filename === file.name);
          const successItem = succeeded.find((item) => item.original_filename === file.name);
          if (failedItem) {
            return { id: `${file.name}-${file.lastModified}-${index}`, name: file.name, status: 'error', message: failedItem.reason };
          }
          if (successItem) {
            return { id: `${file.name}-${file.lastModified}-${index}`, name: file.name, status: 'success', message: 'Saved successfully' };
          }
          return { id: `${file.name}-${file.lastModified}-${index}`, name: file.name, status: 'uploading', message: 'Queued' };
        })
      );
      if (failed.length > 0) {
        setTicketUploadError(`Some ticket screenshots failed: ${failed.map((item) => item.filename).join(', ')}`);
      }
      const refreshedTickets = await getTickets();
      setTickets(refreshedTickets);
      setTicketUploadData(refreshedTickets);
      setShowTicketData(true);
    } catch (err) {
      setTicketUploadItems(prev => prev.map(item => ({ ...item, status: 'error', message: err.message })));
      setTicketUploadError(err.message);
    } finally {
      setTicketUploadLoading(false);
    }
  };

  const handleDocketUpload = async (files) => {
    setDocketUploadLoading(true);
    setDocketUploadError(null);
    const items = files.map((file, index) => ({
      id: `${file.name}-${file.lastModified}-${index}`,
      name: file.name,
      status: 'uploading',
      message: 'Saving docket batch...'
    }));
    setDocketUploadItems(items);

    try {
      const result = await uploadDocketImageBatch(files);
      const failed = result.failed || [];
      const succeeded = result.succeeded || [];

      setDocketUploadItems(
        files.map((file, index) => {
          const failedItem = failed.find((item) => item.filename === file.name || item.original_filename === file.name);
          const successItem = succeeded.find((item) => item.original_filename === file.name);
          if (failedItem) {
            return { id: `${file.name}-${file.lastModified}-${index}`, name: file.name, status: 'error', message: failedItem.reason };
          }
          if (successItem) {
            return { id: `${file.name}-${file.lastModified}-${index}`, name: file.name, status: 'success', message: 'Saved successfully' };
          }
          return { id: `${file.name}-${file.lastModified}-${index}`, name: file.name, status: 'uploading', message: 'Queued' };
        })
      );
      if (failed.length > 0) {
        setDocketUploadError(`Some dockets failed to save: ${failed.map((item) => item.filename).join(', ')}`);
      }
      const refreshedDockets = await getDockets();
      setDockets(refreshedDockets);
      setDocketUploadData(refreshedDockets);
      setShowDocketData(true);
    } catch (err) {
      setDocketUploadItems(prev => prev.map(item => ({ ...item, status: 'error', message: err.message })));
      setDocketUploadError(err.message);
    } finally {
      setDocketUploadLoading(false);
    }
  };

  const recordRows = activeView === 'tickets' ? tickets : dockets;
  const branchOptions = restaurants.map((entry) => entry.branch);
  // The backend maps till restaurant names onto the selected branch; the
  // ticket/docket tables are filtered by that same name list.
  const branchRestaurantNames = restaurants
    .filter((entry) => entry.branch === selectedRestaurant)
    .flatMap((entry) => entry.restaurant_names);
  const inSelectedBranch = (record) => branchRestaurantNames.includes(record.restaurant);
  const filteredTickets = selectedRestaurant ? tickets.filter(inSelectedBranch) : [];
  const filteredDockets = selectedRestaurant ? dockets.filter(inSelectedBranch) : [];

  const requireRestaurant = () => {
    if (!selectedRestaurant) {
      setTicketUploadError('Select a restaurant before uploading ticket screenshots.');
      return false;
    }
    return true;
  };

  const matchingDockets = selectedTicket
    ? dockets.filter((docket) => String(docket.order_number || '') === String(selectedTicket.ticket_id || '').match(/(\d+)$/)?.[1])
    : [];
  const selectedVoidItems = selectedTicket?.items?.filter((item) => item.is_void) || [];
  const comparisonMismatch = selectedTicket && (
    selectedVoidItems.length > 0 && matchingDockets.length === 0
    || matchingDockets.some((docket) => docket.discrepancy_type !== 'void')
  );

  const handleSelectTicket = (ticket) => {
    setSelectedTicket(ticket);
    setComparisonCopyStatus('');
  };

  const handleRecordsExport = async (view) => {
    try {
      if (view === 'tickets') await exportTickets();
      if (view === 'dockets') await exportDockets();
    } catch (err) {
      alert(`Error exporting parsed data: ${err.message}`);
    }
  };

  const handleCopyComparisonData = async () => {
    if (!selectedTicket) return;
    const structuredData = {
      ticket: {
        ticket_id: selectedTicket.ticket_id,
        restaurant: selectedTicket.restaurant,
        date: selectedTicket.date,
        ticket_total: selectedTicket.ticket_total,
        payment_status: selectedTicket.payment_status,
        items: selectedTicket.items?.map((item) => ({
          item: item.item,
          total: item.total,
          qty: item.qty,
          is_void: item.is_void
        })) || []
      },
      dockets: matchingDockets.map((docket) => ({
        order_number: docket.order_number,
        item: docket.item,
        discrepancy_type: docket.discrepancy_type,
        handwritten_reason: docket.description
      })),
      comparison_mismatch: Boolean(comparisonMismatch)
    };

    try {
      if (!navigator.clipboard) throw new Error('Clipboard access is not available in this browser.');
      await navigator.clipboard.writeText(JSON.stringify(structuredData, null, 2));
      setComparisonCopyStatus('Copied');
      window.setTimeout(() => setComparisonCopyStatus(''), 1800);
    } catch (err) {
      alert(`Failed to copy comparison data: ${err.message}`);
    }
  };

  const renderDashboard = (data) => (
    <div className="dashboard">
      <div className="dashboard-header">
        <div>
          <p className="eyebrow">Reconciliation dashboard</p>
          <h3>{data.restaurant} · {data.report_date || 'no date'}</h3>
          <p className="comparison-copy">Run at {data.generated_at}</p>
        </div>
        {data.report && (
          <div className="dashboard-sources">
            <span className={`source-chip ${data.bill.uploaded ? 'on' : 'off'}`}>Bill (slip image): {data.bill.uploaded ? data.bill.extraction_method : 'not uploaded'}</span>
            <span className={`source-chip ${data.excel.uploaded ? 'on' : 'off'}`}>Excel report: {data.excel.uploaded ? `${data.excel.void_rows} void rows` : 'not uploaded'}</span>
            <span className={`source-chip ${data.cross_verified ? 'on' : 'off'}`}>
              {data.report.cross_verified ? 'Slip and Excel cross-verified' : 'Not cross-verified'}
            </span>
          </div>
        )}
      </div>

      {data.missing.length > 0 && (
        <div className="dashboard-missing" role="status">
          <strong>Not ready to reconcile.</strong>
          <p>Still missing for {data.restaurant} on {data.report_date || 'the selected day'}:</p>
          <ul>{data.missing.map((item) => <li key={item}>{item}</li>)}</ul>
        </div>
      )}

      <div className="dashboard-stat-grid">
        <div className="dashboard-stat">
          <span className="dashboard-stat-label">Void items in tickets</span>
          <strong>{count(data.counts.void_items_in_tickets)}</strong>
          <small>source: Tickets</small>
        </div>
        <div className="dashboard-stat">
          <span className="dashboard-stat-label">Dockets filed on this day</span>
          <strong>{count(data.counts.dockets)}</strong>
          <small>source: Dockets · date-only, they carry no restaurant</small>
        </div>
        <div className="dashboard-stat">
          <span className="dashboard-stat-label">Total matched voids</span>
          <strong>{count(data.counts.matched)}</strong>
          <small>source: Tickets ↔ Dockets</small>
        </div>
        <div className="dashboard-stat">
          <span className="dashboard-stat-label">Dockets used in matches</span>
          <strong>{count(data.counts.dockets_used_in_matches)}</strong>
          <small>
            {data.counts.matched_dockets_filed_on_another_day
              ? `${data.counts.matched_dockets_filed_on_another_day} carry a different printed date from the working day`
              : 'all carry this working day’s date'}
          </small>
        </div>
        <div className="dashboard-stat">
          <span className="dashboard-stat-label">Unresolved voids</span>
          <strong>{count(data.totals.unresolved)}</strong>
          <small>slip reported − matched</small>
        </div>
        <div className="dashboard-stat">
          <span className="dashboard-stat-label">Needs review</span>
          <strong>{count(data.counts.needs_review)}</strong>
          <small>ambiguous docket matches</small>
        </div>
        <div className={`dashboard-stat ${data.totals.anomaly ? 'dashboard-stat-anomaly' : ''}`}>
          <span className="dashboard-stat-label">Anomaly</span>
          <strong>{data.totals.anomaly ? 'Matched exceeds reported' : 'None'}</strong>
          <small>{data.totals.anomaly ? 'more pairs found than the slip reports' : 'matched never exceeds reported'}</small>
        </div>
      </div>

      <article className="dashboard-panel">
        <h3>Voids in the long slip (Bill)</h3>
        {data.bill.uploaded ? (
          <table className="dashboard-table">
            <thead><tr>
              <th>Department</th><th>Voids count</th><th>Voids amount</th>
              <th>Discounts</th><th>Promotions</th><th>Cancelled</th>
            </tr></thead>
            <tbody>
              {data.departments.map((department) => (
                <tr key={department.name} className={department.anomaly ? 'dashboard-row-anomaly' : ''}>
                  <td>{department.name}</td>
                  <td>{count(department.bill.voids_count)}</td>
                  <td>{money(department.bill.voids_amount)}</td>
                  <td>{count(department.bill.discounts_count)} / {money(department.bill.discounts_amount)}</td>
                  <td>{count(department.bill.promotions_count)} / {money(department.bill.promotions_amount)}</td>
                  <td>{count(department.bill.cancelled_count)} / {money(department.bill.cancelled_amount)}</td>
                </tr>
              ))}
              <tr className="dashboard-total-row">
                <td>Total</td>
                <td>{count(data.totals.bill.voids_count)}</td>
                <td>{money(data.totals.bill.voids_amount)}</td>
                <td>{count(data.totals.bill.discounts_count)} / {money(data.totals.bill.discounts_amount)}</td>
                <td>{count(data.totals.bill.promotions_count)} / {money(data.totals.bill.promotions_amount)}</td>
                <td>{count(data.totals.bill.cancelled_count)} / {money(data.totals.bill.cancelled_amount)}</td>
              </tr>
            </tbody>
          </table>
        ) : (
          <p className="dashboard-empty">Empty state: the long slip bill image has not been uploaded for {data.restaurant}.</p>
        )}
      </article>

      <article className="dashboard-panel">
        <h3>Voids in Excel</h3>
        {data.excel.uploaded ? (
          <>
            <div className="dashboard-stat-grid">
              <div className="dashboard-stat">
                <span className="dashboard-stat-label">Excel void rows</span>
                <strong>{count(data.excel.void_rows)}</strong>
                <small>rows whose adjustment type starts with Void</small>
              </div>
              <div className="dashboard-stat">
                <span className="dashboard-stat-label">Excel void amount</span>
                <strong>{money(data.excel.voids_amount)}</strong>
                <small>sum of void-row amounts</small>
              </div>
              <div className="dashboard-stat">
                <span className="dashboard-stat-label">Rows with no adjustment type</span>
                <strong>{count(data.excel.unfilled_rows)}</strong>
                <small>blank — never counted as voids, so the log is incomplete</small>
              </div>
              <div className="dashboard-stat">
                <span className="dashboard-stat-label">Rows skipped as out of scope</span>
                <strong>{count(data.excel.skipped_rows)}</strong>
                <small>other branches or other days in the same file</small>
              </div>
            </div>
            <table className="dashboard-table">
              <thead><tr><th>Bill number</th><th>Item</th><th>Amount</th><th>Adjustment type</th><th>Found in tickets</th></tr></thead>
              <tbody>
                {[...data.excel.void_bills_found, ...data.excel.void_bills_not_found].map((row, index) => (
                  <tr key={`${row.bill_number}-${index}`} className={row.found_in_tickets ? '' : 'dashboard-row-unmatched'}>
                    <td><strong>{row.bill_number || '—'}</strong></td>
                    <td>{row.item || '—'}</td>
                    <td>{money(row.amount)}</td>
                    <td>{row.adjustment_type || '—'}</td>
                    <td>{row.found_in_tickets ? 'Yes' : 'No'}</td>
                  </tr>
                ))}
                {data.excel.void_bills_found.length + data.excel.void_bills_not_found.length === 0 && (
                  <tr><td colSpan="5" className="empty-table">No void rows for this branch and day.</td></tr>
                )}
              </tbody>
            </table>
            <p className="dashboard-note">
              Excel void bills found in the uploaded tickets: {data.counts.excel_void_bills_found} ·
              not found: {data.counts.excel_void_bills_not_found}
            </p>
          </>
        ) : (
          <p className="dashboard-empty">Empty state: the Excel Daily Exception Report has not been uploaded for {data.restaurant}.</p>
        )}
      </article>

      <article className="dashboard-panel">
        <h3>Bill vs Excel check</h3>
        {data.bill_vs_excel.state === 'unavailable' ? (
          <p className="dashboard-empty">Only one of the two sources is stored, so there is nothing to compare.</p>
        ) : (
          <>
            <div className={`comparison-result ${data.bill_vs_excel.mismatches.length ? 'comparison-mismatch' : 'comparison-match'}`}>
              <strong>{data.bill_vs_excel.mismatches.length ? 'Mismatch' : 'Match'}</strong>
              <span>
                {data.bill_vs_excel.state === 'match'
                  ? 'The slip and the Excel report agree on the void amount.'
                  : 'The void amounts disagree, so the operator chose which source to store.'}
              </span>
            </div>
            <table className="dashboard-table">
              <thead><tr><th>Check</th><th>Bill (slip)</th><th>Excel</th><th>Difference</th></tr></thead>
              <tbody>
                <tr>
                  <td>Void amount (primary check)</td>
                  <td>{money(data.bill_vs_excel.slip.voids_amount)}</td>
                  <td>{money(data.bill_vs_excel.excel.voids_amount)}</td>
                  <td>
                    {data.bill_vs_excel.mismatches
                      .filter((mismatch) => mismatch.metric === 'voids amount')
                      .map((mismatch) => money(mismatch.difference))
                      .join(', ') || money(0)}
                  </td>
                </tr>
                <tr>
                  <td>Void count (not scored)</td>
                  <td>{count(data.bill_vs_excel.count_comparison.slip)}</td>
                  <td>{count(data.bill_vs_excel.count_comparison.excel)}</td>
                  <td>{count(data.bill_vs_excel.count_comparison.difference)}</td>
                </tr>
              </tbody>
            </table>
            <p className="dashboard-note">Scope: {data.bill_vs_excel.scope}. {data.bill_vs_excel.count_comparison.note}.</p>
          </>
        )}
      </article>

      <article className="dashboard-panel">
        <h3>Reconciliation by department</h3>
        <table className="dashboard-table">
          <thead><tr>
            <th>Department</th><th>Reported (Bill)</th><th>Void items in tickets</th>
            <th>Matched</th><th>Unresolved</th><th>Status</th>
          </tr></thead>
          <tbody>
            {data.departments.map((department) => (
              <tr key={department.name} className={department.anomaly ? 'dashboard-row-anomaly' : ''}>
                <td>{department.name}</td>
                <td>{count(department.bill.voids_count)}</td>
                <td>{count(department.void_items_in_tickets)}</td>
                <td>{count(department.matched)}</td>
                <td>{count(department.unresolved)}</td>
                <td>{department.anomaly ? 'Anomaly' : department.unresolved ? 'Outstanding' : 'Reconciled'}</td>
              </tr>
            ))}
            <tr className="dashboard-total-row">
              <td>Total</td>
              <td>{count(data.totals.bill.voids_count)}</td>
              <td>{count(data.totals.void_items_in_tickets)}</td>
              <td>{count(data.totals.matched)}</td>
              <td>{count(data.totals.unresolved)}</td>
              <td>{data.totals.anomaly ? 'Anomaly' : data.totals.unresolved ? 'Outstanding' : 'Reconciled'}</td>
            </tr>
          </tbody>
        </table>
      </article>

      <div className="dashboard-two-column">
        <article className="dashboard-panel">
          <h3>Unmatched ticket voids ({data.counts.unmatched_ticket_voids})</h3>
          {data.unmatched_ticket_voids.length === 0 ? (
            <p className="dashboard-empty">Every void item in the uploaded tickets found a docket.</p>
          ) : (
            <table className="dashboard-table">
              <thead><tr><th>Ticket</th><th>Department</th><th>Item</th><th>Total</th><th>Why</th></tr></thead>
              <tbody>
                {data.unmatched_ticket_voids.map((row, index) => (
                  <tr key={`${row.ticket_id}-${index}`}>
                    <td><strong>{row.ticket_id}</strong></td>
                    <td>{row.department || '—'}</td>
                    <td>{row.item || '—'}</td>
                    <td>{money(row.total)}</td>
                    <td>{row.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </article>

        <article className="dashboard-panel">
          <h3>Unmatched dockets ({data.counts.unmatched_dockets})</h3>
          {data.unmatched_dockets.length === 0 ? (
            <p className="dashboard-empty">Every uploaded docket was paired with a ticket void.</p>
          ) : (
            <table className="dashboard-table">
              <thead><tr><th>Order no</th><th>Date</th><th>Item</th><th>Type</th><th>Photo</th></tr></thead>
              <tbody>
                {data.unmatched_dockets.map((row, index) => (
                  <tr key={`${row.order_number}-${index}`}>
                    <td><strong>{row.order_number || '—'}</strong></td>
                    <td>{row.date || '—'}</td>
                    <td>{row.item || '—'}</td>
                    <td>{row.discrepancy_type || '—'}</td>
                    <td>{row.image_filename || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="dashboard-note">{data.coverage.dockets}</p>
        </article>
      </div>

      <article className="dashboard-panel">
        <h3>Discounts and promotions — not yet reconciled</h3>
        <p className="dashboard-note">{data.coverage.discounts}</p>
        <table className="dashboard-table">
          <thead><tr><th>Department (from the Bill)</th><th>Discounts</th><th>Promotions</th><th>Cancelled</th></tr></thead>
          <tbody>
            {data.departments.map((department) => (
              <tr key={department.name}>
                <td>{department.name}</td>
                <td>{count(department.discounts.reported_count)} / {money(department.discounts.reported_amount)}</td>
                <td>{count(department.promotions.reported_count)} / {money(department.promotions.reported_amount)}</td>
                <td>{count(department.cancelled.count)} / {money(department.cancelled.amount)}</td>
              </tr>
            ))}
            <tr className="dashboard-total-row">
              <td>Total (Bill)</td>
              <td>{count(data.totals.discounts.reported_count)} / {money(data.totals.discounts.reported_amount)}</td>
              <td>{count(data.totals.promotions.reported_count)} / {money(data.totals.promotions.reported_amount)}</td>
              <td>{count(data.totals.cancelled.count)} / {money(data.totals.cancelled.amount)}</td>
            </tr>
          </tbody>
        </table>
        {data.excel.uploaded ? (
          <table className="dashboard-table">
            <thead><tr><th>Excel (branch + day, no department column)</th><th>Rows</th><th>Amount</th></tr></thead>
            <tbody>
              <tr>
                <td>Discounts</td>
                <td>{count(data.excel.discount_rows)}</td>
                <td>{money(data.excel.discounts_amount)}</td>
              </tr>
              <tr>
                <td>Promotions</td>
                <td>{count(data.excel.promotion_rows)}</td>
                <td>{money(data.excel.promotions_amount)}</td>
              </tr>
            </tbody>
          </table>
        ) : (
          <p className="dashboard-empty">Empty state: the Excel Daily Exception Report has not been uploaded, so no Excel discount or promotion figures are available.</p>
        )}
      </article>
    </div>
  );

  const renderTicketTable = (rows, label) => (
    <div className="upload-data-table">
      <p className="eyebrow">{label}</p>
      <div className="table-scroll">
        <table className="entries-table parsed-table">
          <thead><tr>
            <th className="ticket-id-header">Ticket Number</th><th>Uploaded</th><th>Restaurant</th><th>Date</th><th>Terminal</th>
            <th>Table</th><th>Department</th><th>User</th><th>Payment Status</th><th>Status</th><th>Credit Card Amount</th><th>Items</th><th>Ticket Total</th><th>Grand Total</th><th>Charged</th>
          </tr></thead>
          <tbody>
            {rows.length === 0 ? <tr><td colSpan="15" className="empty-table">No parsed ticket screenshots yet.</td></tr> : rows.map((ticket) => {
              const statusClass = ticket.status === 'needs_description' ? 'needs-description-row' : '';
              return (
                <tr
                  key={ticket.ticket_id}
                  className={`ticket-select-row ${selectedTicket?.ticket_id === ticket.ticket_id ? 'selected-ticket-row' : ''} ${statusClass}`}
                  onClick={async () => {
                    if (ticket.status === 'needs_description') {
                      try {
                        const entryId = await getEntryIdForRecord(ticket);
                        setEditingEntryId(entryId);
                        setDescriptionValue(ticket.description || '');
                        setDescriptionPromptOpen(true);
                      } catch (err) {
                        setDescriptionError(`Failed to load entry for ticket ${ticket.ticket_id}: ${err.message}`);
                        setEditingEntryId(null);
                        setDescriptionValue('');
                        setDescriptionPromptOpen(true);
                      }
                    } else {
                      handleSelectTicket(ticket);
                    }
                  }}
                  tabIndex="0"
                  onKeyDown={async (event) => {
                    if (event.key === 'Enter') {
                      if (ticket.status === 'needs_description') {
                        try {
                          const entryId = await getEntryIdForRecord(ticket);
                          setEditingEntryId(entryId);
                          setDescriptionValue(ticket.description || '');
                          setDescriptionPromptOpen(true);
                        } catch (err) {
                          setDescriptionError(`Failed to load entry for ticket ${ticket.ticket_id}: ${err.message}`);
                          setEditingEntryId(null);
                          setDescriptionValue('');
                          setDescriptionPromptOpen(true);
                        }
                      } else {
                        handleSelectTicket(ticket);
                      }
                    }
                  }}
                >
                  <td className="ticket-id-cell"><strong>{ticket.ticket_id || 'Missing ticket ID'}</strong></td>
                  <td>{ticket.uploaded_at ? new Date(`${ticket.uploaded_at}Z`).toLocaleString() : '—'}</td>
                  <td>{ticket.restaurant || '—'}</td>
                  <td>{ticket.date || '—'}</td>
                  <td>{ticket.terminal || '—'}</td>
                  <td>{ticket.table || '—'}</td>
                  <td>{ticket.department || '—'}</td>
                  <td>{ticket.user || '—'}</td>
                  <td>{ticket.payment_status || '—'}</td>
                  <td className={`status-cell ${ticket.status}`}>{ticket.status || '—'}</td>
                  <td>{ticket.credit_card_amount || '—'}</td>
                  <td>{ticket.items?.length ? `${ticket.items.length} item${ticket.items.length === 1 ? '' : 's'}` : '—'}</td>
                  <td>{ticket.ticket_total || '—'}</td>
                  <td>{ticket.grand_total || '—'}</td>
                  <td>{ticket.charged || '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );

  const renderDocketTable = (rows, label) => (
    <div className="upload-data-table">
      <p className="eyebrow">{label}</p>
      <div className="table-scroll">
        <table className="entries-table parsed-table">
          <thead><tr><th>Order No</th><th>Date</th><th>Time</th><th>Item</th><th>Discrepancy Type</th><th>Status</th><th>Handwritten Reason</th></tr></thead>
          <tbody>
            {rows.length === 0 ? <tr><td colSpan="7" className="empty-table">No parsed dockets yet.</td></tr> : rows.map((docket) => {
              const statusClass = docket.status === 'needs_description' ? 'needs-description-row' : '';
              return (
                <tr
                  key={docket.id}
                  className={`${docket.review_required ? 'parsed-review-row' : ''} ${statusClass}`}
                  onClick={async () => {
                    if (docket.status === 'needs_description') {
                      try {
                        const entryId = await getEntryIdForRecord(docket);
                        setEditingEntryId(entryId);
                        setDescriptionValue(docket.description || '');
                        setDescriptionPromptOpen(true);
                      } catch (err) {
                        setDescriptionError(`Failed to load entry for docket ${docket.order_number}: ${err.message}`);
                        setEditingEntryId(null);
                        setDescriptionValue('');
                        setDescriptionPromptOpen(true);
                      }
                    }
                  }}
                  tabIndex="0"
                  onKeyDown={async (event) => {
                    if (event.key === 'Enter' && docket.status === 'needs_description') {
                      try {
                        const entryId = await getEntryIdForRecord(docket);
                        setEditingEntryId(entryId);
                        setDescriptionValue(docket.description || '');
                        setDescriptionPromptOpen(true);
                      } catch (err) {
                        setDescriptionError(`Failed to load entry for docket ${docket.order_number}: ${err.message}`);
                        setEditingEntryId(null);
                        setDescriptionValue('');
                        setDescriptionPromptOpen(true);
                      }
                    }
                  }}
                >
                  <td><strong>{docket.order_number || '—'}</strong></td>
                  <td>{docket.date || '—'}</td>
                  <td>{docket.time || '—'}</td>
                  <td>{docket.item || '—'}</td>
                  <td><span className={`badge badge-${docket.discrepancy_type || 'unknown'}`}>{docket.discrepancy_type || 'unknown'}</span></td>
                  <td className={`status-cell ${docket.status}`}>{docket.status || '—'}</td>
                  <td className="handwritten-cell">{docket.description || '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand-lockup">
          <div className="brand-mark">T</div>
          <div>
            <p className="eyebrow">Restaurant operations</p>
            <h1>TIL System</h1>
          </div>
        </div>
        <div className="header-meta">
          <span className="live-dot" />
          <span>Workspace active</span>
        </div>
      </header>
      <main className="app-main">
        <section className="welcome-row">
          <div>
            <p className="eyebrow">Daily reconciliation</p>
            <h2>Keep every bill accounted for.</h2>
            <p className="welcome-copy">Review discrepancies, add context, and keep your restaurant records moving.</p>
          </div>
          <div className="date-chip">Today <strong>{new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</strong></div>
        </section>

        <>

        <section className="restaurant-filter-section">
          <div>
            <p className="eyebrow">Step 1</p>
            <h2>Choose a branch and day</h2>
            <p className="filter-copy">Everything below is scoped to this branch and working day, the same scope the tickets and dockets are matched on.</p>
          </div>
          <div className="branch-filter-fields">
            <label className="restaurant-filter-field">
              <span>Branch</span>
              <select value={selectedRestaurant} onChange={(event) => handleScopeChange(setSelectedRestaurant)(event.target.value)}>
                <option value="">Select a branch</option>
                {branchOptions.map((branch) => <option key={branch} value={branch}>{branch}</option>)}
              </select>
            </label>
            <label className="restaurant-filter-field">
              <span>Working day</span>
              <input type="date" value={selectedDate} onChange={(event) => handleScopeChange(setSelectedDate)(event.target.value)} />
            </label>
          </div>
        </section>

        <section className="comparison-source-panel" aria-labelledby="comparison-source-title">
          <div className="comparison-source-copy">
            <p className="eyebrow">Step 2 — comparison sources</p>
            <h2 id="comparison-source-title">Upload the long slip and the Excel report</h2>
            <p>
              The <strong>long slip bill</strong> is the till's printed Work Period Report: per-department void,
              discount, promotion and cancelled totals. The <strong>Excel report</strong> is the Daily Exception
              Report: one row per voided, discounted or promoted item. Upload either on its own, or both to
              cross-verify them against each other.
            </p>
          </div>
          <div className="comparison-source-actions">
            <div className="comparison-source-control">
              <input
                id="comparison-long-slip-upload"
                className="file-picker"
                type="file"
                accept="image/*"
                onChange={(event) => {
                  const [file] = Array.from(event.target.files || []);
                  if (file) setComparisonLongSlipFile(file);
                  event.target.value = '';
                }}
              />
              <label className="source-upload-button" htmlFor="comparison-long-slip-upload">
                <span className="source-upload-button-icon">IMG</span>
                Upload long bill slip
              </label>
              <span className={`source-file-selection ${comparisonLongSlipFile ? 'has-file' : ''}`} title={comparisonLongSlipFile?.name || ''}>
                {comparisonLongSlipFile ? `Selected: ${comparisonLongSlipFile.name}` : 'Long bill slip image'}
              </span>
            </div>
            <div className="comparison-source-control">
              <input
                id="comparison-excel-upload"
                className="file-picker"
                type="file"
                accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                onChange={(event) => {
                  const [file] = Array.from(event.target.files || []);
                  if (file) setComparisonExcelFile(file);
                  event.target.value = '';
                }}
              />
              <label className="source-upload-button" htmlFor="comparison-excel-upload">
                <span className="source-upload-button-icon">XLS</span>
                Upload Excel
              </label>
              <span className={`source-file-selection ${comparisonExcelFile ? 'has-file' : ''}`} title={comparisonExcelFile?.name || ''}>
                {comparisonExcelFile ? `Selected: ${comparisonExcelFile.name}` : 'Daily Exception Report (.xlsx)'}
              </span>
            </div>
          </div>
          <div className="comparison-source-footer">
            <button
              className="primary-action-button"
              onClick={() => handleSalesReportUpload('')}
              disabled={salesReportLoading || !selectedRestaurant || (!comparisonLongSlipFile && !comparisonExcelFile)}
            >
              {salesReportLoading ? 'Saving...' : 'Save comparison sources'}
            </button>
            <p className="comparison-source-note">
              {selectedRestaurant
                ? `Saved against ${selectedRestaurant} · ${selectedDate}`
                : 'Select a branch to enable saving.'}
            </p>
          </div>
          {salesReportLoading && <p className="upload-progress">Extracting the sales report...</p>}
          {salesReportError && <p className="upload-error">{salesReportError}</p>}
          {salesReportSaved && (
            <div className="sales-report-saved" role="status">
              <strong>Saved</strong>
              <span>{salesReportSaved.restaurant} · {salesReportSaved.report_date || 'no date on the slip'} · source {salesReportSaved.source}</span>
              <span>
                Extraction {salesReportSaved.extraction_method}
                {salesReportSaved.cross_verified ? ' · slip and Excel cross-verified' : ''}
                {salesReportSaved.confirmed_source ? ` · ${salesReportSaved.confirmed_source} confirmed by the operator` : ''}
              </span>
              {salesReportSaved.excel && (
                <span>
                  Excel: {salesReportSaved.excel.void_rows} void rows · {salesReportSaved.excel.unfilled_rows} rows with no adjustment type
                  {salesReportSaved.excel.skipped_rows ? ` · ${salesReportSaved.excel.skipped_rows} rows skipped as out of scope` : ''}
                </span>
              )}
              <table className="saved-department-table">
                <thead><tr>
                  <th>Department</th><th>Voids</th><th>Discounts</th><th>Promotions</th><th>Cancelled</th>
                </tr></thead>
                <tbody>
                  {salesReportSaved.departments.map((department) => (
                    <tr key={department.name}>
                      <td>{department.name}</td>
                      <td>{count(department.voids_count)} / {money(department.voids_amount)}</td>
                      <td>{count(department.discounts_count)} / {money(department.discounts_amount)}</td>
                      <td>{count(department.promotions_count)} / {money(department.promotions_amount)}</td>
                      <td>{count(department.cancelled_count)} / {money(department.cancelled_amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {salesReportConflict && (
            <div className="sales-report-conflict" role="alert">
              <strong>{salesReportConflict.message}</strong>
              <p>Nothing has been saved. Choose which source to store:</p>
              <ul>
                {(salesReportConflict.mismatches || []).map((mismatch) => (
                  <li key={`${mismatch.metric}-${mismatch.slip}-${mismatch.excel}`}>
                    {mismatch.metric}: slip {money(mismatch.slip)} vs Excel {money(mismatch.excel)}
                    {' '}(difference {money(mismatch.difference)})
                  </li>
                ))}
              </ul>
              <div className="button-group">
                <button className="primary-action-button" onClick={() => handleSalesReportUpload('slip')} disabled={salesReportLoading}>
                  Store the long slip
                </button>
                <button className="primary-action-button" onClick={() => handleSalesReportUpload('excel')} disabled={salesReportLoading}>
                  Store the Excel report
                </button>
              </div>
            </div>
          )}
        </section>

        <section className="bulk-upload-grid">
          <div className="upload-section bulk-panel">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Ticket screenshots</p>
                <h2>Upload screenshots in bulk</h2>
              </div>
              <span className="section-icon">IMG</span>
            </div>
            <label className={`upload-dropzone ${!selectedRestaurant ? 'upload-disabled' : ''}`} htmlFor="ticket-screenshot-upload">
              <span className="upload-icon">＋</span>
              <span className="upload-title">Select ticket screenshots</span>
              <span className="upload-hint">PNG, JPG or WEBP · Up to 30 screenshots</span>
              <span className="upload-button">Browse screenshots</span>
            </label>
            <input
              id="ticket-screenshot-upload"
              className="file-picker"
              type="file"
              accept="image/*"
              multiple
              onChange={(e) => {
                const files = Array.from(e.target.files);
                if (files.length > 0 && requireRestaurant()) {
                  handleTicketScreenshotUpload(files);
                  e.target.value = '';
                }
              }}
              disabled={ticketUploadLoading || !selectedRestaurant}
            />
            {ticketUploadLoading && <p className="upload-progress">Parsing ticket screenshots...</p>}
            {ticketUploadError && <p className="upload-error">{ticketUploadError}</p>}
            {ticketUploadItems.length > 0 && (
              <div className="upload-status-list" aria-live="polite">
                {ticketUploadItems.map(item => (
                  <div className={`upload-status-item ${item.status}`} key={item.id}>
                    <span className="upload-status-icon">{item.status === 'uploading' ? '...' : item.status === 'success' ? 'OK' : '!'}</span>
                    <span className="upload-file-name">{item.name}</span>
                    <span className="upload-file-message">{item.message}</span>
                  </div>
                ))}
              </div>
            )}
            {ticketUploadItems.some((item) => item.status === 'success') && (
              <button className="show-data-button" onClick={() => setShowTicketData((visible) => !visible)}>
                {showTicketData ? 'Hide data' : 'Show data'}
              </button>
            )}
            {showTicketData && ticketUploadData.filter(inSelectedBranch).length > 0 && renderTicketTable(ticketUploadData.filter(inSelectedBranch), 'Uploaded ticket data')}
          </div>

          <div className="upload-section bulk-panel">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Bulk docket</p>
                <h2>Discrepancy images</h2>
              </div>
              <span className="section-icon">IMG</span>
            </div>
            <label className={`upload-dropzone ${!selectedRestaurant ? 'upload-disabled' : ''}`} htmlFor="docket-upload">
              <span className="upload-icon">＋</span>
              <span className="upload-title">Choose docket batch</span>
              <span className="upload-hint">PNG, JPG or WEBP · Up to 30 images</span>
              <span className="upload-button">Browse images</span>
            </label>
            <input
              id="docket-upload"
              className="file-picker"
              type="file"
              accept="image/*"
              multiple
              onChange={(e) => {
                const files = Array.from(e.target.files);
                if (files.length > 0 && requireRestaurant()) {
                  handleDocketUpload(files);
                  e.target.value = '';
                }
              }}
              disabled={docketUploadLoading || !selectedRestaurant}
            />
            {docketUploadLoading && <p className="upload-progress">Saving dockets...</p>}
            {docketUploadError && <p className="upload-error">{docketUploadError}</p>}
            {docketUploadItems.length > 0 && (
              <div className="upload-status-list" aria-live="polite">
                {docketUploadItems.map(item => (
                  <div className={`upload-status-item ${item.status}`} key={item.id}>
                    <span className="upload-status-icon">{item.status === 'uploading' ? '...' : item.status === 'success' ? 'OK' : '!'}</span>
                    <span className="upload-file-name">{item.name}</span>
                    <span className="upload-file-message">{item.message}</span>
                  </div>
                ))}
              </div>
            )}
            {docketUploadItems.some((item) => item.status === 'success') && (
              <button className="show-data-button" onClick={() => {
                setShowDocketData((visible) => !visible);
              }}>
                {showDocketData ? 'Hide data' : 'Show data'}
              </button>
            )}
            {showDocketData && docketUploadData.filter(inSelectedBranch).length > 0 && renderDocketTable(docketUploadData.filter(inSelectedBranch), 'Uploaded docket data')}
          </div>
        </section>
        <section className="process-section" aria-labelledby="process-title">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Step 3</p>
              <h2 id="process-title">Process this branch and day</h2>
              <p className="filter-copy">
                Runs the reconciliation for {selectedRestaurant || 'the selected branch'} on {selectedDate} and
                opens the dashboard. Every figure comes from the backend, recalculated on each run.
              </p>
            </div>
            <button className="primary-action-button" onClick={handleProcess} disabled={processLoading || !selectedRestaurant}>
              {processLoading ? 'Processing...' : 'Process'}
            </button>
          </div>
          {processError && <p className="upload-error">{processError}</p>}
          {dashboard && renderDashboard(dashboard)}
        </section>

        <section id="records-section" className="parsed-record-section">
          <div className="section-heading table-heading">
            <div>
              <p className="eyebrow">Parsed data</p>
              <h2>Tickets and dockets <span className="entry-count">{tickets.length + dockets.length}</span></h2>
            </div>
            <button className="export-button" onClick={() => handleRecordsExport(activeView)} disabled={recordsLoading || recordRows.length === 0}>
              <span>↓</span> Export {activeView === 'tickets' ? 'tickets' : 'dockets'} CSV
            </button>
          </div>
          {recordsLoading && <p className="loading-state">Loading parsed {activeView}...</p>}
          {recordsError && <p className="error-state">Error: {recordsError}</p>}
          <div className="combined-record-tables">
            {activeView === 'tickets' ? renderTicketTable(filteredTickets, 'Ticket data') : renderDocketTable(filteredDockets, 'Docket data')}
          </div>
        </section>
        </>
        {selectedTicket && (
          <section className="comparison-view">
            <div className="section-heading comparison-heading">
              <div>
                <p className="eyebrow">Ticket comparison</p>
                <h2>{selectedTicket.ticket_id}</h2>
                <p className="comparison-copy">Compare the selected ticket against the docket discrepancy images for this order.</p>
              </div>
              <div className="button-group">
                <button className="show-data-button" onClick={() => handleSelectTicket(null)}>Back to tickets</button>
                <button className="show-data-button" onClick={handleCopyComparisonData}>{comparisonCopyStatus || 'Copy data'}</button>
              </div>
            </div>
            <div className={`comparison-result ${comparisonMismatch ? 'comparison-mismatch' : 'comparison-match'}`}>
              <strong>{comparisonMismatch ? 'Mismatch found' : 'No mismatch found'}</strong>
              <span>{comparisonMismatch ? 'Review the highlighted ticket or docket information.' : 'The selected ticket and docket evidence are aligned.'}</span>
            </div>
            <div className="comparison-grid">
              <article className="comparison-panel">
                <p className="eyebrow">Ticket row information</p>
                <dl className="comparison-details">
                  <dt>Restaurant</dt><dd>{selectedTicket.restaurant || '—'}</dd>
                  <dt>Date</dt><dd>{selectedTicket.date || '—'}</dd>
                  <dt>Ticket total</dt><dd>{selectedTicket.ticket_total || '—'}</dd>
                  <dt>Payment status</dt><dd>{selectedTicket.payment_status || '—'}</dd>
                </dl>
                <div className="comparison-items">
                  {selectedTicket.items?.map((item, index) => (
                    <div className={item.is_void ? 'comparison-item mismatch-highlight' : 'comparison-item'} key={`${selectedTicket.ticket_id}-${index}`}>
                      <strong>{item.item || 'Unnamed item'}</strong>
                      <span>{item.total || '—'} · Qty {item.qty || '—'}</span>
                      {item.is_void && <em>VOID</em>}
                    </div>
                  ))}
                </div>
              </article>
              <article className="comparison-panel">
                <p className="eyebrow">Bulk docket discrepancy images</p>
                {matchingDockets.length === 0 ? (
                  <div className="comparison-empty mismatch-highlight">No docket evidence matches order {selectedTicket.ticket_id.match(/(\d+)$/)?.[1] || '—'}.</div>
                ) : matchingDockets.map((docket) => (
                  <div className={`docket-comparison-card ${docket.discrepancy_type !== 'void' ? 'mismatch-highlight' : ''}`} key={docket.id}>
                    <div className="comparison-card-heading"><strong>Order {docket.order_number}</strong><span className="badge badge-void">{docket.discrepancy_type || 'unknown'}</span></div>
                    <p>{docket.item || 'Docket item not parsed'}</p>
                    <span>{docket.description || 'No handwritten reason captured'}</span>
                    {docket.image_filename && <small>{docket.image_filename}</small>}
                  </div>
                ))}
              </article>
            </div>
          </section>
        )}
        {/* Description Prompt Modal */}
        {descriptionPromptOpen && (
          <div className="description-modal-backdrop" onClick={() => {
            if (descriptionPromptOpen) {
              setDescriptionPromptOpen(false);
              setEditingEntryId(null);
              setDescriptionValue('');
              setDescriptionError(null);
            }
          }}>
            <div className="description-modal-content" onClick={(e) => e.stopPropagation()}>
              <div className="description-modal-header">
                <h2>Add Description</h2>
                <button className="description-modal-close" onClick={() => {
                  setDescriptionPromptOpen(false);
                  setEditingEntryId(null);
                  setDescriptionValue('');
                  setDescriptionError(null);
                }}>
                  ×
                </button>
              </div>
              <div className="description-modal-body">
                <p className="description-modal-instructions">
                  Enter a description for this entry. This will help clarify the record for future reference.
                </p>
                <div className="description-modal-form">
                  <label htmlFor="description-input">
                    Description:
                  </label>
                  <textarea
                    id="description-input"
                    value={descriptionValue}
                    onChange={(e) => setDescriptionValue(e.target.value)}
                    placeholder="Enter description here..."
                    className="description-input"
                    rows="4"
                  />
                  {descriptionError && (
                    <p className="description-modal-error">{descriptionError}</p>
                  )}
                </div>
              </div>
              <div className="description-modal-footer">
                <button
                  className="description-modal-button"
                  onClick={async () => {
                    setDescriptionSaving(true);
                    setDescriptionError(null);
                    try {
                      await updateEntry(editingEntryId, { description: descriptionValue });
                      setDescriptionPromptOpen(false);
                      setEditingEntryId(null);
                      setDescriptionValue('');
                      // Refresh the relevant data
                      if (activeView === 'tickets') {
                        const refreshedTickets = await getTickets();
                        setTickets(refreshedTickets);
                      } else {
                        const refreshedDockets = await getDockets();
                        setDockets(refreshedDockets);
                      }
                    } catch (err) {
                      setDescriptionError(`Failed to save description: ${err.message}`);
                    } finally {
                      setDescriptionSaving(false);
                    }
                  }}
                  disabled={descriptionSaving}
                >
                  {descriptionSaving ? 'Saving...' : 'Save Description'}
                </button>
                <button
                  className="description-modal-button description-modal-button-secondary"
                  onClick={() => {
                    setDescriptionPromptOpen(false);
                    setEditingEntryId(null);
                    setDescriptionValue('');
                    setDescriptionError(null);
                  }}
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        )}
      </main>
      <footer className="app-footer">
        <span>TIL System</span>
        <span>Restaurant operations workspace</span>
      </footer>
    </div>
  );
}

export default App;