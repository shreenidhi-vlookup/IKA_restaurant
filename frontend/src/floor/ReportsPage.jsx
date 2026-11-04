import { useContext, useEffect } from 'react';
import { WorkspaceContext } from './WorkspaceContext.js';
import { useImports } from './ImportsContext.js';
import { workflowReport } from './workflowReport.js';
import { verificationBoxes } from './verificationData.js';
import { summaryCopyText } from './copyFormats.js';
import { displayValue } from './ticketRecords.js';
import CopyButton from './CopyButton.jsx';
import LiveWorkspace from './LiveWorkspace.jsx';
import ReportCharts from './ReportCharts.jsx';
import './workflow.css';

function Panel({ title, children }) { return <section className="hf-panel hf-workflow-panel"><header><h2>{title}</h2></header>{children}</section>; }
function Table({ label, headings, children }) { return <div className="hf-workflow-table" role="region" aria-label={label} tabIndex="0"><table><thead><tr>{headings.map(heading => <th key={heading} scope="col">{heading}</th>)}</tr></thead><tbody>{children}</tbody></table></div>; }

export default function ReportsPage() {
  const { branch, businessDate, dispatch } = useContext(WorkspaceContext);
  const { state, controller } = useImports();
  const ready = state.branch === branch && state.businessDate === businessDate;
  const report = workflowReport(state);
  const boxes = verificationBoxes(report.hasImport ? state.verification.summary : null);
  useEffect(() => {
    if (ready && branch && !controller.getSnapshot().historyLoaded) controller.loadHistory();
  }, [ready, branch, businessDate, controller]);

  return <LiveWorkspace>
    <Panel title="Daily workflow report"><p className="hf-workflow-note">Saved API records for the selected branch and business date. This report does not create a persisted close-of-day decision.</p><Table label="Daily workflow report" headings={['Workflow', 'Available records', 'Outstanding work']}>
      <tr><th scope="row">Till import</th><td>{report.hasImport ? `${report.rows.length} CSV rows · ${state.verification.summary.quantity} items` : 'No till import'}</td><td>{report.hasImport ? `${report.outstanding.length} flagged rows need attention` : 'Import a till CSV'}</td></tr>
      <tr><th scope="row">Image extraction</th><td>{report.extracted.length} extracted / {report.files.length} saved images</td><td>{report.processing.length} queued or processing · {report.failed.length} failed</td></tr>
      <tr><th scope="row">Tickets</th><td>{report.tickets.length} saved ticket records</td><td>No items extracted: {report.emptyTickets.length} · {report.reviewTickets.length} with extraction review flags</td></tr>
      <tr><th scope="row">Dockets</th><td>{report.dockets.length} saved docket records</td><td>{report.reviewDockets.length} with extraction review indicators</td></tr>
      <tr><th scope="row">Evidence matching</th><td>{report.unassigned.length} unassigned screenshots</td><td>{report.incomplete.length} outstanding CSV rows without a ticket/docket evidence pair</td></tr>
      <tr><th scope="row">Unpaid ticket report</th><td>{report.ticketReport ? `${report.ticketReport.total_tickets} tickets processed in this session` : 'Not imported in this session'}</td><td>{report.ticketReport ? `${report.ticketReport.unpaid_count} unpaid; inspect details in Imports` : 'Historical unpaid results are not persisted by the backend'}</td></tr>
    </Table></Panel>
    <Panel title="CSV verification summary">{report.hasImport ? <Table label="CSV verification categories" headings={['Category', 'Value', 'Detail', 'Copy']} >{boxes.map(box => <tr key={box.key}><th scope="row">{box.title}</th><td>{box.value}</td><td>{box.note}</td><td><CopyButton label={`Copy ${box.title}`} getText={() => summaryCopyText(box, report.rows, branch, businessDate)} /></td></tr>)}</Table> : <p className="hf-workflow-note">No till report has been imported for this business date.</p>}</Panel>
    <Panel title="Flagged CSV row record"><p className="hf-workflow-note">Matching statuses are backend-calculated. No manual reviewer or resolution history is invented.</p><Table label="Flagged CSV rows" headings={['Product / row date', 'User / department / till', 'Void', 'Cancel', 'Promotion', 'Overall status']} >{report.flagged.map(row => <tr key={row.id}><td><strong>{row.product}</strong><small>{row.row_date || businessDate}</small></td><td>{displayValue(row.user_name)}<small>{displayValue(row.department)} · {displayValue(row.till)}</small></td>{['void', 'cancel', 'promotion'].map(key => <td key={key}>{(row.matches?.[key]?.status || 'not_flagged').replaceAll('_', ' ')}<small>{row.matches?.[key]?.verified ?? 0} / {row.matches?.[key]?.total ?? 0} units</small></td>)}<td>{(row.row_status || 'pending').replaceAll('_', ' ')}</td></tr>)}{!report.flagged.length && <tr><td colSpan="6">{report.hasImport ? 'No flagged CSV rows.' : 'Import a till CSV to populate this record.'}</td></tr>}</Table><p className="hf-workflow-note"><a href="#verification">Inspect matching candidates and evidence in Verification →</a></p></Panel>
    <Panel title="Saved till import history"><p className="hf-workflow-note">All saved till-import dates for this branch. Charts below remain scoped to the currently selected business date.</p>{state.historyLoading && <p className="hf-workflow-note" role="status">Loading history…</p>}{state.historyError && <p className="hf-import-error" role="alert">History could not be loaded: {state.historyError}</p>}<div className="hf-workflow-history-actions"><button type="button" className="hf-secondary" disabled={state.historyLoading || state.busy} onClick={() => controller.loadHistory()}>Refresh history</button></div>{state.historyLoaded && <Table label="Branch till import history" headings={['Business date', 'Filename', 'Item rows', 'Flagged rows', 'View']} >{state.history.map(item => <tr key={item.date}><td>{item.date}{item.date === businessDate && <small>Selected date</small>}</td><td>{item.filename || 'Till CSV'}</td><td>{item.item_rows}</td><td>{item.flagged_rows}</td><td><button type="button" className="hf-secondary" disabled={state.busy || item.date === businessDate} onClick={() => dispatch({ type: 'businessDate', value: item.date })}>View records</button></td></tr>)}{!state.history.length && <tr><td colSpan="5">No saved till-import history for this branch.</td></tr>}</Table>}</Panel>
    <ReportCharts report={report} branch={branch} businessDate={businessDate} />
  </LiveWorkspace>;
}
