import { useId } from 'react';

const labels = { needs_review: 'Needs review', pending: 'Pending', partial: 'Partial', verified: 'Verified', queued: 'Queued', processing: 'Processing', failed: 'Failed', done: 'Extracted' };
function Bars({ title, rows }) {
  const total = rows.reduce((sum, row) => sum + row.count, 0);
  return <section className="hf-report-bars"><header><h4>{title}</h4><span>{total} total</span></header>{total ? <ul>{rows.filter(row => row.count > 0).map((row, index) => <li key={row.label}><div><span>{labels[row.label] || row.label}</span><strong>{row.count}</strong></div><span className="hf-report-track" aria-hidden="true"><span className={`hf-report-colour-${index % 3}`} style={{ width: `${row.count / total * 100}%` }} /></span></li>)}</ul> : <p className="hf-workflow-note">No records for this chart.</p>}</section>;
}

export default function ReportCharts({ report, branch, businessDate }) {
  const id = useId();
  const types = report.discrepancyTypes.filter(row => row.count > 0);
  const total = types.reduce((sum, row) => sum + row.count, 0);
  return <section className="hf-report-charts" aria-labelledby={`${id}-title`}><header><h2 id={`${id}-title`}>Branch report insights</h2><p>{branch} · {businessDate} · Real records from the report above</p></header><div className="hf-overview-grid">
    <section className="hf-panel hf-workflow-panel"><header><h3>Discrepancy types</h3></header><p className="hf-workflow-note">Each flagged CSV row/type counts once. A row with multiple flags appears in multiple types; this is not a ticket count.</p>{total ? <div className="hf-report-donut-layout"><figure><svg viewBox="0 0 160 160" role="img" aria-label={types.map(row => `${row.label}: ${row.count}`).join(', ')}><g transform="rotate(-90 80 80)">{types.map((row, index) => {
      const length = row.count / total * 100;
      const offset = types.slice(0, index).reduce((sum, item) => sum + item.count, 0) / total * 100;
      return <circle key={row.label} className={`hf-report-stroke-${index}`} cx="80" cy="80" r="58" fill="none" strokeWidth="22" pathLength="100" strokeDasharray={`${length} ${100 - length}`} strokeDashoffset={-offset}><title>{row.label}: {row.count}</title></circle>;
    })}</g><text x="80" y="78" textAnchor="middle" className="hf-report-total">{total}</text><text x="80" y="99" textAnchor="middle" className="hf-report-total-label">row/type checks</text></svg><figcaption>Selected branch and business date only</figcaption></figure><ul>{types.map((row, index) => <li key={row.label}><i aria-hidden="true" className={`hf-report-colour-${index}`} /><span>{row.label}</span><strong>{row.count}</strong></li>)}</ul></div> : <p className="hf-workflow-note">No flagged discrepancy types in this selection.</p>}</section>
    <section className="hf-panel hf-workflow-panel"><header><h3>Workflow status</h3></header><Bars title="Flagged CSV rows" rows={report.verificationStates} /><Bars title="Saved images" rows={report.imageStates} /><p className="hf-workflow-note">Image extraction completion is separate from verification. Unflagged CSV rows are excluded from the matching-status chart.</p></section>
  </div></section>;
}
