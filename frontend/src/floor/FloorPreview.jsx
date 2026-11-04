import { useContext } from 'react';
import { Icon } from '../design/icons.jsx';
import WorkspaceProvider from './WorkspaceProvider.jsx';
import { WorkspaceContext } from './WorkspaceContext.js';
import { BRANCHES, SECTIONS, formatBusinessDate, localBusinessDate } from './workspaceState.js';
import './floorApp.css';
import ImportsProvider from './ImportsProvider.jsx';
import ImportsPage from './ImportsPage.jsx';
import { useImports } from './ImportsContext.js';
import TicketsPage from './TicketsPage.jsx';
import VerificationPage from './VerificationPage.jsx';
import OverviewPage from './OverviewPage.jsx';
import ReportsPage from './ReportsPage.jsx';

function WorkspaceSelectors() {
  const { branch, businessDate, dispatch } = useContext(WorkspaceContext);
  const { state: imports } = useImports();
  const today = localBusinessDate();
  return <header className="hf-header">
    <div className="hf-header-title"><strong>Restaurant workspace</strong><span>Today: {formatBusinessDate(today)}</span></div>
    <div className="hf-selectors">
      <label htmlFor="hf-branch">Restaurant branch<select id="hf-branch" value={branch} disabled={imports.busy} onChange={event => dispatch({ type: 'branch', value: event.target.value })}><option value="">Choose branch</option>{BRANCHES.map(name => <option key={name} value={name}>{name}</option>)}</select></label>
      <label htmlFor="hf-business-date">Business date<input id="hf-business-date" type="date" required value={businessDate} disabled={imports.busy} onChange={event => { if (event.target.validity.valid) dispatch({ type: 'businessDate', value: event.target.value }); }} /><span className="hf-date-note">{imports.busy ? 'Available after the current request completes' : businessDate === today ? 'Same as today' : 'Different from today'}</span></label>
    </div>
  </header>;
}

function SectionPreview() {
  const { section } = useContext(WorkspaceContext);
  const current = SECTIONS.find(item => item.id === section);
  return <>
    <div className="hf-page-head"><div><p className="hf-eyebrow">Haveli / The Floor</p><h1>{current.label}</h1><p>{current.description}</p></div></div>
    {section === 'overview' && <OverviewPage />}
    {section === 'imports' && <ImportsPage />}
    {section === 'tickets' && <TicketsPage />}
    {section === 'verification' && <VerificationPage />}
    {section === 'reports' && <ReportsPage />}
  </>;
}

function FloorShell() {
  const { section, dispatch } = useContext(WorkspaceContext);
  return <div className="haveli-floor-app">
    <a className="hf-skip" href="#hf-main">Skip to main content</a>
    <aside className="hf-sidebar"><a className="hf-brand" href="/"><span className="hf-brand-mark">H</span><span>Haveli</span></a>
      <nav className="hf-nav" aria-label="Primary navigation">{SECTIONS.map(item => <a key={item.id} href={`#${item.id}`} aria-current={section === item.id ? 'page' : undefined} onClick={() => dispatch({ type: 'section', value: item.id })}><Icon name={item.icon} size={18} /><span>{item.label}</span></a>)}</nav>
    </aside>
    <div className="hf-shell"><WorkspaceSelectors /><main id="hf-main" className="hf-content" tabIndex="-1"><SectionPreview /><footer className="hf-footer">Haveli Ticket Management</footer></main></div>
  </div>;
}

export default function FloorPreview() {
  return <WorkspaceProvider><ImportsProvider><FloorShell /></ImportsProvider></WorkspaceProvider>;
}
