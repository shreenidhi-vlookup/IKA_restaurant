import { apiFetch } from './client';

async function downloadCsv(endpoint, filename) {
  const response = await fetch(`/api${endpoint}`);
  if (!response.ok) throw new Error(`CSV export failed: ${response.statusText}`);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function getTickets() {
  return apiFetch('/tickets');
}

export function getDockets() {
  return apiFetch('/dockets');
}

export function getSalesReportReconciliation() {
  return apiFetch('/sales-reports/reconcile');
}

export function getSalesReports() {
  return apiFetch('/sales-reports');
}

// Branch names the operator selects, with the till's own restaurant names
// behind each. The UI must not hardcode branches or map names itself.
export function getRestaurants() {
  return apiFetch('/restaurants');
}

// The Process button's only data source. Every dashboard figure is computed
// by the backend; the UI renders this payload without counting or matching.
export function processSalesReport(restaurant, date) {
  return apiFetch('/sales-reports/process', {
    method: 'POST',
    body: JSON.stringify({ restaurant, date: date || null }),
  });
}

export function exportTickets() {
  return downloadCsv('/tickets/export', 'tickets.csv');
}

export function exportDockets() {
  return downloadCsv('/dockets/export', 'dockets.csv');
}

export function exportSalesReports() {
  return downloadCsv('/sales-reports/export', 'sales-reports.csv');
}