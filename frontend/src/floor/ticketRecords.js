// Presentation adapters for existing API records; raw values are never overwritten.
export function recordArray(value) {
  if (Array.isArray(value)) return value;
  try { const parsed = JSON.parse(value || '[]'); return Array.isArray(parsed) ? parsed : []; }
  catch { return []; }
}

export function displayValue(value) {
  return value === null || value === undefined || value === '' ? '—' : String(value);
}

export function ticketItems(ticket) { return recordArray(ticket.items); }
export function ticketFlags(ticket) { return recordArray(ticket.review_flags); }
export function docketLines(docket) { return recordArray(docket.item_lines); }
export function docketConflicts(docket) { return recordArray(docket.field_conflicts); }
export function docketPartialFields(docket) { return recordArray(docket.partial_fields); }
export function docketNeedsReview(docket) { return Boolean(docket.review_required || docketConflicts(docket).length || docketPartialFields(docket).length); }

export function voidSignals(item) {
  return [['row_tint', 'Row tint'], ['strikethrough_line', 'Strikethrough'], ['void_label_text', 'Void label']]
    .filter(([key]) => item.signals?.[key] || item[key]).map(([, label]) => label);
}

export function docketDiscrepancy(docket) {
  return docket.discrepancy_type || docketLines(docket).filter(line => line.is_void || line.marker_type).map(line => line.marker_type || 'VOID').join(', ') || '—';
}

export function evidenceFiles(record, kind) {
  const names = recordArray(kind === 'ticket' ? record.screenshot_filenames : record.image_filenames);
  const files = names.length ? names : kind === 'docket' && record.image_filename ? [record.image_filename] : [];
  return [...new Set(files.filter(name => typeof name === 'string' && name))].map(name => ({ name, url: `/api/images/${kind === 'ticket' ? 'ticket_screenshots' : 'dockets'}/${encodeURIComponent(name)}` }));
}

export function filterTickets(records, { query = '', filter = 'all', payment = 'all' } = {}) {
  const text = query.trim().toLocaleLowerCase();
  return records.filter(ticket => {
    const items = ticketItems(ticket);
    const matches = filter === 'all' || (filter === 'empty' && !items.length) || (filter === 'review' && ticketFlags(ticket).length > 0) || (filter === 'void' && items.some(item => item.is_void));
    const searchable = [ticket.ticket_id, ticket.ticket_id_display, ticket.restaurant, ticket.table_name, ticket.user_name, ticket.department, ticket.terminal, ...items.map(item => item.name || item.item)].join(' ').toLocaleLowerCase();
    return matches && (payment === 'all' || ticket.payment_status === payment) && (!text || searchable.includes(text));
  });
}

export function filterDockets(records, { query = '', filter = 'all' } = {}) {
  const text = query.trim().toLocaleLowerCase();
  return records.filter(docket => {
    const lines = docketLines(docket);
    const matches = filter === 'all' || (filter === 'review' && docketNeedsReview(docket)) || (filter === 'missing-description' && !docket.handwritten_reason) || (filter === 'marked' && (Boolean(docket.discrepancy_type) || lines.some(line => line.is_void || line.marker_type)));
    const searchable = [docket.docket_order_no, docket.table_name, docket.department, docket.staff_name, docket.item, docket.handwritten_reason, ...lines.map(line => line.name || line.item)].join(' ').toLocaleLowerCase();
    return matches && (!text || searchable.includes(text));
  });
}
