import { useContext } from 'react';
import { WorkspaceContext } from './WorkspaceContext.js';
import { useImports } from './ImportsContext.js';
import { formatBusinessDate } from './workspaceState.js';

export default function LiveWorkspace({ children }) {
  const { branch, businessDate } = useContext(WorkspaceContext);
  const { state, controller } = useImports();
  if (!branch) return <section className="hf-panel"><div className="hf-panel-body"><h2>Choose a restaurant branch</h2><p className="hf-muted">Select a branch and business date to load real records.</p></div></section>;
  if (state.branch !== branch || state.businessDate !== businessDate || state.loading) return <p role="status">Loading the selected workspace…</p>;
  return <>
    <p className="hf-live-note"><strong>Live workspace</strong> · {branch} · {formatBusinessDate(businessDate)}<span>All counts use the selected branch and the existing API’s business-date rules.</span></p>
    <div className="hf-record-toolbar"><span className="hf-muted">{state.verification ? 'Saved records from the existing backend' : 'Records have not loaded'}</span><button type="button" className="hf-secondary" disabled={state.busy} onClick={() => controller.refresh()}>Refresh records</button></div>
    {state.error && <div className="hf-import-error" role="alert"><p>{state.error}</p><p>{state.verification ? 'Showing the last successfully loaded records. Refresh to check for updates.' : 'No counts are shown until records can be loaded.'}</p><button type="button" className="hf-secondary" disabled={state.busy} onClick={() => controller.refresh()}>Retry loading records</button></div>}
    {state.verification && children}
  </>;
}
