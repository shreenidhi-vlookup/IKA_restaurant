// Category and clipboard semantics are kept identical to the original App.jsx.
export function verificationBoxes(summary) {
  return summary ? [
    { key: 'total', title: 'Total', value: `${summary.item_rows} rows`, note: `${summary.quantity} items` },
    { key: 'void', title: 'Void', value: `${summary.void.flagged_rows} rows`, note: `£${summary.void.amount.toFixed(2)} · ${summary.void.verified} of ${summary.void.total} verified` },
    { key: 'cancel', title: 'Cancel', value: `${summary.cancel.flagged_rows} rows`, note: `£${summary.cancel.amount.toFixed(2)} · ${summary.cancel.verified} of ${summary.cancel.total} verified` },
    { key: 'promotions', title: 'Promotions', value: summary.promotions_in_file ? `${summary.promotions.flagged_rows} rows` : 'Not in file', note: summary.promotions_in_file ? `£${summary.promotions.amount.toFixed(2)} · ${summary.promotions.verified} of ${summary.promotions.total} verified` : 'Promotion column not present' },
    { key: 'status', title: 'Status', value: summary.status.label, note: `${summary.status.verified} of ${summary.status.total} flagged rows verified` },
  ] : [];
}

export function rowsForCategory(rows, key) {
  return rows.filter(row => key === 'total' ? true : key === 'status' ? (row.void_count > 0 || row.cancel_count > 0 || row.promotion_count > 0) && row.row_status !== 'verified' : row[`${key === 'promotions' ? 'promotion' : key}_count`] > 0);
}

export function originalStatusLabel(row, key) {
  return row.matches?.[key]?.status?.replace('_', ' ') || row.row_status?.replace('_', ' ') || 'pending';
}

export function categoryStatus(row, category) {
  return row.matches?.[category === 'promotions' ? 'promotion' : category]?.status || row.row_status || 'pending';
}

export function filterVerificationRows(rows, { query = '', status = 'all', category = 'status' } = {}) {
  const text = query.trim().toLocaleLowerCase();
  return rows.filter(row => (status === 'all' || categoryStatus(row, category) === status) && (!text || [row.product, row.user_name, row.department, row.till, row.row_date, row.id].join(' ').toLocaleLowerCase().includes(text)));
}
